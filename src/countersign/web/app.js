// Countersign review console. No framework and no build step: one module, DOM built
// with `h()`. Text that comes from a document (supplier names, line descriptions) is
// always inserted as a text node, never as HTML.

const KEY_STORAGE = "countersign.apiKey";
const view = document.getElementById("view");
const toastElement = document.getElementById("toast");

const refreshTimers = [];
const objectUrls = [];
// Incremented each time another page is shown. A page keeps the value it started with
// and checks it after every wait: an answer that arrives for a page the reviewer has
// left must neither draw over the current one nor start a timer.
let renderToken = 0;
// The server renders at most this many pages of a document.
const MAX_PAGES = 12;

// ------------------------------------------------------------------------- helpers

function h(tag, attributes = {}, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name === "class") element.className = value;
    else if (name === "dataset") Object.assign(element.dataset, value);
    else if (name.startsWith("on")) element.addEventListener(name.slice(2), value);
    else if (name in element && name !== "list") element[name] = value;
    else element.setAttribute(name, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const key = localStorage.getItem(KEY_STORAGE);
  if (key) headers.set("X-API-Key", key);
  const init = { ...options, headers };
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(options.json);
  }
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // The body was not JSON: keep the status text.
    }
    throw new ApiError(detail, response.status);
  }
  return response;
}

const getJson = async (path) => (await api(path)).json();

function toast(message, kind = "info") {
  toastElement.textContent = message;
  toastElement.dataset.kind = kind;
  toastElement.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (toastElement.hidden = true), kind === "error" ? 7000 : 3500);
}

function money(value, currency) {
  if (value === null || value === undefined) return "";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "EUR" }).format(number);
  } catch {
    return `${number.toFixed(2)} ${currency || ""}`.trim();
  }
}

// A date without a time is a calendar day: read as local midnight, not as midnight UTC,
// which is the day before for anyone west of Greenwich.
const day = (value) => (value ? new Date(`${value}T00:00:00`).toLocaleDateString() : "");
const moment = (value) => (value ? new Date(value).toLocaleString() : "");
const percent = (value) => (value === null || value === undefined ? "n/a" : `${(value * 100).toFixed(0)} %`);

const STATUS_LABELS = {
  queued: "Queued",
  processing: "Processing",
  approved: "Approved",
  review: "Review",
  rejected: "Rejected",
  duplicate: "Duplicate",
  failed: "Failed",
};

const REASON_LABELS = {
  arithmetic: "Figures do not add up",
  bank_details: "Bank details",
  supplier: "Supplier",
  buyer: "Not addressed to us",
  purchase_order: "Purchase order",
  grounding: "Value not on the page",
  missing_field: "Missing field",
  invoice_number: "Invoice number",
  document_type: "Kind of document",
  not_invoice: "Not an invoice",
  duplicate: "Duplicate",
  dates: "Dates",
  currency: "Currency",
  extraction: "Unreadable value",
  consensus: "Two readings differ",
  extraction_failed: "Could not be read",
  unreadable: "Unreadable file",
  too_long: "Too long",
};

const TIER_LABELS = {
  "embedded-xml": "Embedded e-invoice (no model)",
  small: "Small model",
  large: "Large model, after escalation",
  reviewer: "Reviewer",
};

const chip = (kind, label) => h("span", { class: "chip", dataset: { kind } }, label);
const statusChip = (status) => chip(status === "rejected" ? "neutral" : status, STATUS_LABELS[status] || status);
const reasonChips = (reasons) =>
  h("div", { class: "chips" }, (reasons || []).map((reason) => chip("review", REASON_LABELS[reason] || reason)));

function setView(nodes, { wide = false } = {}) {
  view.className = wide ? "wide" : "";
  view.replaceChildren(...[nodes].flat().filter(Boolean));
}

function stopRefresh() {
  for (const timer of refreshTimers.splice(0)) clearInterval(timer);
  for (const url of objectUrls.splice(0)) URL.revokeObjectURL(url);
}

function refreshEvery(token, milliseconds, task) {
  if (token !== renderToken) return;
  refreshTimers.push(
    setInterval(() => {
      if (token === renderToken && !document.hidden) task().catch(() => {});
    }, milliseconds),
  );
}

function documentsTable(items, emptyText) {
  if (!items.length) return h("div", { class: "empty" }, emptyText);
  return h(
    "table",
    {},
    h(
      "thead",
      {},
      h(
        "tr",
        {},
        ["#", "Status", "Supplier", "Invoice", "Issued", "Total", "Stopped by", "Read by"].map((title) =>
          h("th", { class: title === "Total" ? "right" : "" }, title),
        ),
      ),
    ),
    h(
      "tbody",
      {},
      items.map((item) =>
        h(
          "tr",
          { class: "link", onclick: () => (location.hash = `#/documents/${item.id}`) },
          h("td", { class: "num muted" }, item.id),
          h("td", {}, statusChip(item.status)),
          h("td", {}, item.vendor_name || h("span", { class: "muted" }, item.filename)),
          h("td", { class: "mono" }, item.invoice_number || ""),
          h("td", { class: "num" }, day(item.issue_date)),
          h("td", { class: "num right" }, money(item.total_gross, item.currency)),
          h("td", {}, reasonChips(item.reasons)),
          h("td", { class: "muted" }, TIER_LABELS[item.kept_tier] || item.kept_tier || ""),
        ),
      ),
    ),
  );
}

// ------------------------------------------------------------------------ overview

function tile(label, value, hint) {
  return h(
    "div",
    { class: "card tile" },
    h("div", { class: "label" }, label),
    h("div", { class: "value" }, value),
    h("div", { class: "hint" }, hint || " "),
  );
}

function bars(entries, labels, kind) {
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  if (!total) return h("div", { class: "muted" }, "Nothing yet.");
  return h(
    "div",
    { class: "bars" },
    entries.map(([name, count]) =>
      h(
        "div",
        { class: "bar-row", dataset: { kind } },
        h("span", {}, labels[name] || name),
        h("div", { class: "bar" }, h("span", { style: `width: ${(count / total) * 100}%` })),
        h("span", { class: "num muted" }, count),
      ),
    ),
  );
}

async function upload(files) {
  let last = null;
  for (const file of files) {
    const form = new FormData();
    form.append("file", file);
    try {
      const received = await (await api("/api/documents", { method: "POST", body: form })).json();
      last = received.document;
      toast(received.created ? `${file.name} queued` : `${file.name} was already received`);
    } catch (error) {
      toast(`${file.name}: ${error.message}`, "error");
    }
  }
  if (files.length === 1 && last) location.hash = `#/documents/${last.id}`;
  else route();
}

function dropzone() {
  const input = h("input", {
    type: "file",
    accept: "application/pdf",
    multiple: true,
    hidden: true,
    onchange: () => upload([...input.files]),
  });
  const zone = h(
    "label",
    {
      class: "dropzone",
      ondragover: (event) => {
        event.preventDefault();
        zone.classList.add("over");
      },
      ondragleave: () => zone.classList.remove("over"),
      ondrop: (event) => {
        event.preventDefault();
        zone.classList.remove("over");
        upload([...event.dataTransfer.files]);
      },
    },
    h("strong", {}, "Drop supplier invoices here, or click to choose PDF files"),
    h("span", {}, "Each file is read, checked, then approved or sent to review."),
    input,
  );
  return zone;
}

async function overview() {
  const token = renderToken;
  let previous = "";
  const draw = async () => {
    const [stats, page] = await Promise.all([getJson("/api/stats"), getJson("/api/documents?limit=8")]);
    if (token !== renderToken) return;
    const snapshot = JSON.stringify([stats, page]);
    if (snapshot === previous) return;
    previous = snapshot;
    const status = stats.by_status;
    const waiting = status.queued + status.processing;
    setView([
      h("div", { class: "page-head" }, h("h1", {}, "Overview")),
      dropzone(),
      h(
        "div",
        { class: "grid tiles" },
        tile("Documents decided", stats.processed, waiting ? `${waiting} in the queue` : "queue empty"),
        tile(
          "Approved without a person",
          percent(stats.automation_rate),
          `${stats.approved_automatically} of ${stats.processed}`,
        ),
        tile("Waiting for review", status.review, `${stats.approved_by_reviewer} approved by a reviewer`),
        tile("Set aside", status.rejected + status.duplicate, `${status.duplicate} duplicates`),
        tile(
          "Model time per document",
          stats.mean_model_seconds === null ? "n/a" : `${stats.mean_model_seconds} s`,
          status.failed ? `${status.failed} failed` : stats.replay ? "replaying recorded answers" : "",
        ),
      ),
      h(
        "div",
        { class: "grid two" },
        h(
          "div",
          { class: "card" },
          h("h2", {}, "Why documents are waiting"),
          bars(Object.entries(stats.review_reasons), REASON_LABELS, "review"),
        ),
        h("div", { class: "card" }, h("h2", {}, "Who read them"), bars(Object.entries(stats.kept_tier), TIER_LABELS)),
      ),
      h(
        "div",
        { class: "card table-card" },
        documentsTable(page.items, "No document yet. Drop a PDF above, or load the sample set."),
      ),
    ]);
  };
  await draw();
  refreshEvery(token, 3000, draw);
}

// ----------------------------------------------------------------------- documents

async function documentList(status) {
  const token = renderToken;
  const state = { status: status || "", q: "" };
  const tableHolder = h("div", { class: "card table-card" });
  let previous = "";
  let asked = 0;
  const draw = async () => {
    const query = new URLSearchParams({ limit: "100" });
    if (state.status) query.set("status", state.status);
    if (state.q) query.set("q", state.q);
    const mine = ++asked;
    const page = await getJson(`/api/documents?${query}`);
    // Only the answer to the latest question is shown: a slower, older one is dropped.
    if (token !== renderToken || mine !== asked) return;
    const snapshot = JSON.stringify(page);
    if (snapshot === previous) return;
    previous = snapshot;
    tableHolder.replaceChildren(
      documentsTable(page.items, status === "review" ? "Nothing is waiting for review." : "No document matches."),
    );
  };
  const select = h(
    "select",
    {
      "aria-label": "Status",
      onchange: () => {
        state.status = select.value;
        draw();
      },
    },
    h("option", { value: "" }, "All statuses"),
    Object.entries(STATUS_LABELS).map(([value, label]) => h("option", { value }, label)),
  );
  let debounce = null;
  const search = h("input", {
    type: "search",
    placeholder: "Supplier, invoice number or file",
    "aria-label": "Search",
    oninput: () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        state.q = search.value;
        draw();
      }, 250);
    },
  });
  setView([
    h("div", { class: "page-head" }, h("h1", {}, status === "review" ? "Waiting for review" : "Documents")),
    status === "review" ? null : h("div", { class: "toolbar" }, search, select),
    tableHolder,
  ]);
  await draw();
  refreshEvery(token, 3000, draw);
}

// ------------------------------------------------------------------ document detail

const HEADER_FIELDS = [
  ["invoice_number", "Invoice number", "text"],
  ["document_type", "Kind", "kind"],
  ["issue_date", "Issued", "date"],
  ["due_date", "Due", "date"],
  ["supplier_name", "Supplier", "text"],
  ["supplier_vat_id", "Supplier VAT number", "text"],
  ["supplier_siret", "SIRET", "text"],
  ["supplier_iban", "IBAN on the document", "text"],
  ["po_number", "Purchase order", "text"],
  ["referenced_invoice", "Cancels invoice", "text"],
  ["currency", "Currency", "text"],
  ["total_net", "Net total", "decimal"],
  ["total_tax", "VAT", "decimal"],
  ["total_gross", "Gross total", "decimal"],
  ["allowance_total", "Discount", "decimal"],
  ["charge_total", "Shipping", "decimal"],
];
const LINE_FIELDS = ["description", "quantity", "unit_price", "amount", "vat_rate"];

function failuresByField(checks) {
  const byField = new Map();
  for (const check of checks) {
    if (check.passed || !check.blocking) continue;
    for (const field of check.fields) {
      const key = field.startsWith("lines") ? "lines" : field;
      if (!byField.has(key)) byField.set(key, []);
      byField.get(key).push(check.message);
    }
  }
  return byField;
}

function checkList(checks) {
  if (!checks.length) return h("div", { class: "muted" }, "No check was run.");
  const ordered = [...checks].sort((a, b) => Number(a.passed) - Number(b.passed));
  return h(
    "div",
    {},
    ordered.map((check) => {
      const state = check.passed ? "pass" : check.blocking ? "fail" : "warn";
      return h(
        "div",
        { class: "check", dataset: { state } },
        h("span", { class: "mark" }, check.passed ? "✓" : "✕"),
        h("div", {}, h("div", {}, check.message), h("div", { class: "id" }, check.id)),
      );
    }),
  );
}

function headline(document_) {
  const by = document_.decided_by;
  switch (document_.status) {
    case "approved":
      return by === "system" ? "Approved automatically: every check passed" : `Approved by ${by}`;
    case "review":
      return "Waiting for a reviewer";
    case "rejected":
      return by && by !== "system" ? `Rejected by ${by}` : "Set aside: not an invoice";
    case "duplicate":
      return "Set aside: this invoice was already received";
    case "failed":
      return "Processing failed";
    default:
      return "In the queue";
  }
}

async function documentDetail(id) {
  const token = renderToken;
  const document_ = await getJson(`/api/documents/${id}`);
  if (token !== renderToken) return;
  const editable = document_.status === "review";
  const invoice = structuredClone(document_.invoice) || { document_type: "invoice", lines: [], vat_breakdown: [] };
  let checks = document_.checks;

  const fieldElements = new Map();
  const checksHolder = h("div");
  const approveHint = h("span", { class: "muted" });
  const lineBody = h("tbody");
  const comment = h("textarea", { placeholder: "Comment (required to approve despite a failed check)" });

  const readInvoice = () => {
    const result = { ...invoice };
    for (const [name, , kind] of HEADER_FIELDS) {
      const value = fieldElements.get(name).input.value.trim();
      result[name] = value === "" ? null : kind === "decimal" ? value.replace(",", ".") : value;
    }
    result.lines = [...lineBody.children].map((row) => {
      const cells = row.querySelectorAll("input");
      const line = {};
      LINE_FIELDS.forEach((field, index) => {
        const value = cells[index].value.trim();
        line[field] = field === "description" ? value : value === "" ? null : value.replace(",", ".");
      });
      return line;
    });
    return result;
  };

  const paintChecks = () => {
    const failures = failuresByField(checks);
    for (const [name, element] of fieldElements) {
      const messages = failures.get(name);
      element.wrapper.dataset.state = messages ? "fail" : "ok";
      element.flag.textContent = messages ? "check failed" : "";
      element.wrapper.title = messages ? messages.join("\n") : "";
    }
    checksHolder.replaceChildren(checkList(checks));
    const blocking = checks.filter((check) => !check.passed && check.blocking).length;
    approveHint.textContent = blocking
      ? `${blocking} check${blocking > 1 ? "s" : ""} still fail${blocking > 1 ? "" : "s"}: approving needs a comment.`
      : "Every check passes.";
  };

  const failing = () => checks.filter((check) => !check.passed && check.blocking).map((check) => check.id);

  // The checks shown must be those of what the form holds now. Requests are numbered:
  // the answer to an earlier one, arriving late, is dropped.
  let recheckTimer = null;
  let rechecks = 0;
  let lastRecheck = Promise.resolve();
  const runRecheck = async () => {
    const mine = ++rechecks;
    try {
      const response = await api(`/api/documents/${id}/recheck`, { method: "POST", json: { invoice: readInvoice() } });
      const answer = await response.json();
      if (mine !== rechecks || token !== renderToken) return;
      checks = answer.checks;
      paintChecks();
    } catch (error) {
      if (mine === rechecks && error.status !== 422) toast(error.message, "error");
    }
  };
  const recheck = () => {
    clearTimeout(recheckTimer);
    recheckTimer = setTimeout(() => {
      recheckTimer = null;
      lastRecheck = runRecheck();
    }, 450);
  };
  // Before a decision: an edit still waiting for its recheck is checked now, and the
  // request under way is awaited.
  const settleChecks = async () => {
    if (recheckTimer !== null) {
      clearTimeout(recheckTimer);
      recheckTimer = null;
      lastRecheck = runRecheck();
    }
    await lastRecheck;
  };

  const fieldInput = (name, kind) => {
    const value = invoice[name] ?? "";
    if (kind === "kind") {
      return h(
        "select",
        { disabled: !editable, onchange: recheck },
        [
          ["invoice", "Invoice"],
          ["credit_note", "Credit note"],
          ["other", "Not an invoice"],
        ].map(([option, label]) => h("option", { value: option, selected: option === value }, label)),
      );
    }
    return h("input", {
      type: kind === "date" ? "date" : "text",
      inputMode: kind === "decimal" ? "decimal" : null,
      value,
      readOnly: !editable,
      oninput: recheck,
    });
  };

  const fields = h(
    "div",
    { class: "fields" },
    HEADER_FIELDS.map(([name, label, kind]) => {
      const input = fieldInput(name, kind);
      const flag = h("span");
      const wrapper = h("div", { class: "field" }, h("label", {}, h("span", {}, label), flag), input);
      fieldElements.set(name, { wrapper, input, flag });
      return wrapper;
    }),
  );

  const lineRow = (line = {}) => {
    const row = h(
      "tr",
      {},
      LINE_FIELDS.map((field) =>
        h(
          "td",
          {},
          h("input", {
            value: line[field] ?? "",
            readOnly: !editable,
            "aria-label": field,
            oninput: recheck,
          }),
        ),
      ),
      editable
        ? h(
            "td",
            {},
            h(
              "button",
              {
                class: "ghost",
                type: "button",
                title: "Remove this line",
                onclick: () => {
                  row.remove();
                  recheck();
                },
              },
              "✕",
            ),
          )
        : null,
    );
    return row;
  };
  lineBody.replaceChildren(...invoice.lines.map(lineRow));

  // One request at a time: a second click while the first is under way does nothing.
  let busy = false;
  const once = async (task) => {
    if (busy) return;
    busy = true;
    try {
      await task();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      busy = false;
    }
  };

  const act = (action) =>
    once(async () => {
      const body = { action, comment: comment.value };
      if (action === "approve") {
        // An approval overrides the failed checks the reviewer was shown, and only
        // those: if bringing the checks up to date reveals another, it is shown first.
        const shown = new Set(failing());
        await settleChecks();
        if (failing().some((check) => !shown.has(check))) {
          toast("The checks changed: look at them, then approve again.", "error");
          return;
        }
        body.invoice = readInvoice();
        body.acknowledged = failing();
      }
      try {
        await api(`/api/documents/${id}/decision`, { method: "POST", json: body });
      } catch (error) {
        // The server found a failed check that was not acknowledged: show its view.
        if (error.status === 409 && action === "approve") lastRecheck = runRecheck();
        throw error;
      }
      toast(action === "approve" ? "Approved and exported" : "Rejected");
      route();
    });

  const reprocess = () =>
    once(async () => {
      await api(`/api/documents/${id}/reprocess`, { method: "POST" });
      toast("Queued again");
      route();
    });

  // The pages are images rendered by the server: the browser never opens the supplier's
  // file. They are fetched rather than linked so that the API key travels with them.
  const pages = h("div", { class: "pages" });
  const pageCount = document_.page_count || 0;
  const loadPage = async (number, image) => {
    const response = await api(`/api/documents/${id}/pages/${number}`);
    const blob = await response.blob();
    if (token !== renderToken) return;
    const url = URL.createObjectURL(blob);
    objectUrls.push(url);
    image.src = url;
  };
  for (let number = 1; number <= pageCount; number += 1) {
    const image = h("img", { alt: `Page ${number} of ${document_.filename}` });
    pages.append(image);
    loadPage(number, image).catch(() =>
      image.replaceWith(h("div", { class: "empty" }, `Page ${number} could not be shown.`)),
    );
  }
  if (pageCount === 0) {
    // The page count is known once a worker has read the file. Until then, and for a
    // file no worker could read, pages are asked for one by one until there is none.
    (async () => {
      for (let number = 1; number <= MAX_PAGES && token === renderToken; number += 1) {
        const image = h("img", { alt: `Page ${number} of ${document_.filename}` });
        try {
          await loadPage(number, image);
        } catch {
          if (number === 1) pages.append(h("div", { class: "empty" }, "No page could be rendered from this file."));
          return;
        }
        pages.append(image);
      }
    })();
  }

  const bannerKind = { rejected: "neutral", queued: "neutral", processing: "neutral" }[document_.status] || document_.status;
  setView(
    [
      h(
        "div",
        { class: "page-head" },
        h("h1", {}, `Document ${document_.id}`, " ", h("span", { class: "muted" }, document_.filename)),
        h("a", { href: "#/documents" }, "All documents"),
      ),
      h(
        "div",
        { class: "detail" },
        h("div", { class: "card viewer" }, pages),
        h(
          "div",
          { class: "panel" },
          h(
            "div",
            { class: "card banner", dataset: { kind: bannerKind } },
            h("div", { class: "headline" }, statusChip(document_.status), headline(document_)),
            document_.reasons.length ? reasonChips(document_.reasons) : null,
            document_.note ? h("div", {}, document_.note) : null,
            document_.error ? h("div", { class: "mono" }, document_.error) : null,
            ["failed", "review"].includes(document_.status)
              ? h("div", { class: "actions" }, h("button", { type: "button", onclick: reprocess }, "Read it again"))
              : null,
          ),
          document_.invoice || editable
            ? h(
                "div",
                { class: "card" },
                h("h2", {}, editable ? "Invoice: correct what was misread" : "Invoice"),
                fields,
                h(
                  "table",
                  { class: "lines", style: "margin-top: 14px" },
                  h(
                    "thead",
                    {},
                    h(
                      "tr",
                      {},
                      ["Description", "Qty", "Unit price", "Amount", "VAT %"].map((title) => h("th", {}, title)),
                      editable ? h("th", { class: "remove", "aria-label": "Remove" }) : null,
                    ),
                  ),
                  lineBody,
                ),
                editable
                  ? h(
                      "button",
                      {
                        class: "ghost",
                        type: "button",
                        onclick: () => {
                          lineBody.append(lineRow());
                        },
                      },
                      "+ Add a line",
                    )
                  : null,
              )
            : null,
          editable
            ? h(
                "div",
                { class: "card" },
                h("h2", {}, "Decision"),
                comment,
                h(
                  "div",
                  { class: "actions", style: "margin-top: 10px" },
                  h("button", { class: "primary", type: "button", onclick: () => act("approve") }, "Approve"),
                  h("button", { class: "danger", type: "button", onclick: () => act("reject") }, "Reject"),
                  approveHint,
                ),
              )
            : null,
          h("div", { class: "card" }, h("h2", {}, "Checks"), checksHolder),
          h(
            "div",
            { class: "card" },
            h("h2", {}, "How it was read"),
            h(
              "div",
              { class: "timeline" },
              document_.attempts.length
                ? document_.attempts.map((attempt) =>
                    h(
                      "div",
                      { class: "entry" },
                      h("strong", {}, TIER_LABELS[attempt.tier]?.split(",")[0] || attempt.tier, attempt.kept ? " ← kept" : ""),
                      h(
                        "span",
                        { class: "muted" },
                        [
                          attempt.model,
                          attempt.mode === "vision" ? "from page images" : attempt.mode === "embedded" ? "from embedded XML" : "from text",
                          attempt.model ? `${attempt.duration_s.toFixed(1)} s` : null,
                          attempt.model ? `${attempt.prompt_tokens} + ${attempt.output_tokens} tokens` : null,
                          attempt.error ? `error: ${attempt.error}` : null,
                          attempt.checks.filter((check) => !check.passed && check.blocking).length
                            ? `${attempt.checks.filter((check) => !check.passed && check.blocking).length} failed checks`
                            : attempt.error
                              ? null
                              : "all checks passed",
                        ]
                          .filter(Boolean)
                          .join(" · "),
                      ),
                    ),
                  )
                : h("span", { class: "muted" }, "Not read yet."),
            ),
          ),
          h(
            "div",
            { class: "card" },
            h("h2", {}, "History"),
            h(
              "div",
              { class: "timeline" },
              document_.events.map((event) =>
                h(
                  "div",
                  { class: "entry" },
                  h("span", { class: "muted num" }, moment(event.at)),
                  h(
                    "span",
                    {},
                    h("strong", {}, event.action),
                    ` by ${event.actor}`,
                    event.detail.comment ? `: ${event.detail.comment}` : "",
                    event.detail.corrected?.length ? ` (corrected: ${event.detail.corrected.join(", ")})` : "",
                    event.detail.overridden_checks?.length
                      ? ` (approved despite: ${event.detail.overridden_checks.join(", ")})`
                      : "",
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    ],
    { wide: true },
  );
  paintChecks();
  if (["queued", "processing"].includes(document_.status)) {
    refreshEvery(token, 2000, async () => {
      const current = await getJson(`/api/documents/${id}`);
      if (token === renderToken && current.status !== document_.status) route();
    });
  }
}

// ------------------------------------------------------------------------ suppliers

async function suppliers() {
  const vendors = await getJson("/api/vendors");
  setView([
    h("div", { class: "page-head" }, h("h1", {}, "Suppliers on file")),
    h(
      "p",
      { class: "muted" },
      "The vendor master every document is checked against. A payment always goes to the account listed here, never to the one printed on an invoice.",
    ),
    h(
      "div",
      { class: "card table-card" },
      h(
        "table",
        {},
        h(
          "thead",
          {},
          h("tr", {}, ["Id", "Name", "Country", "Currency", "VAT number", "IBAN", "Order required"].map((t) => h("th", {}, t))),
        ),
        h(
          "tbody",
          {},
          vendors.map((vendor) =>
            h(
              "tr",
              {},
              h("td", { class: "mono" }, vendor.vendor_id),
              h("td", {}, vendor.name),
              h("td", {}, vendor.country),
              h("td", {}, vendor.currency),
              h("td", { class: "mono" }, vendor.vat_id || ""),
              h("td", { class: "mono" }, vendor.iban || ""),
              h("td", {}, vendor.po_required ? "yes" : ""),
            ),
          ),
        ),
      ),
    ),
  ]);
}

// --------------------------------------------------------------------------- shell

async function route() {
  stopRefresh();
  renderToken += 1;
  const path = location.hash.replace(/^#/, "") || "/";
  const [, section, id] = path.split("/");
  const current = section === "" ? "overview" : section;
  for (const link of document.querySelectorAll("#nav a")) {
    if (link.dataset.route === current) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  try {
    if (current === "overview") await overview();
    else if (current === "review") await documentList("review");
    else if (current === "documents" && id) await documentDetail(Number(id));
    else if (current === "documents") await documentList();
    else if (current === "suppliers") await suppliers();
    else setView(h("div", { class: "empty" }, "Page not found."));
  } catch (error) {
    if (error.status === 401) {
      setView(h("div", { class: "empty" }, "This server needs an API key. Use the “API key” button."));
    } else {
      setView(h("div", { class: "empty" }, error.message));
    }
  }
  view.focus({ preventScroll: true });
}

async function refreshShell() {
  const readiness = document.getElementById("readiness");
  try {
    const response = await fetch("/readyz");
    const state = await response.json();
    const down = Object.entries(state.models).filter(([, ready]) => !ready).map(([model]) => model);
    readiness.dataset.state = state.replay ? "replay" : state.ready ? "ready" : "down";
    readiness.textContent = state.replay
      ? "Replaying recorded answers"
      : state.ready
        ? "Models ready"
        : down.length
          ? `Unavailable: ${down.join(", ")}`
          : "Database unavailable";
  } catch {
    readiness.dataset.state = "down";
    readiness.textContent = "Server unreachable";
  }
  try {
    const page = await getJson("/api/documents?status=review&limit=1");
    const badge = document.getElementById("review-count");
    badge.textContent = page.total;
    badge.hidden = page.total === 0;
  } catch {
    // Not authenticated yet: the main view says so.
  }
}

document.getElementById("key-button").addEventListener("click", () => {
  const key = window.prompt("API key for this server (leave empty to forget it):", "");
  if (key === null) return;
  if (key) localStorage.setItem(KEY_STORAGE, key);
  else localStorage.removeItem(KEY_STORAGE);
  route();
  refreshShell();
});

window.addEventListener("hashchange", route);
route();
refreshShell();
setInterval(() => !document.hidden && refreshShell(), 10000);
