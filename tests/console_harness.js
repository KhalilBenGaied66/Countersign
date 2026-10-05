// Runs src/countersign/web/app.js, unmodified, against a small DOM stub, with the network
// and the timers under the control of a scenario. Each scenario drives the console
// through an interleaving a browser would only produce by chance, and prints what the
// reviewer would see as JSON.
//
//     node tests/console_harness.js <scenario>
//
// tests/test_api.py runs the scenarios and holds the expected results.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SCRIPT = path.join(__dirname, "..", "src", "countersign", "web", "app.js");

class StubNode {}

class StubText extends StubNode {
  constructor(text) {
    super();
    this.text = text;
  }
}

// Properties a real element has, so that `name in element` answers as in a browser.
const PROPERTIES = ["value", "type", "hidden", "href", "title", "disabled", "readOnly", "placeholder",
  "multiple", "accept", "inputMode", "selected", "alt", "src", "textContent", "style", "id"];

class StubElement extends StubNode {
  constructor(tag) {
    super();
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.className = "";
    this.attributes = {};
    this.listeners = {};
    this.classList = { add() {}, remove() {} };
    this.parent = null;
  }
  append(...nodes) {
    for (const node of nodes) {
      if (node instanceof StubElement) node.parent = this;
      this.children.push(node);
    }
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }
  replaceWith(node) {
    if (!this.parent) return;
    const index = this.parent.children.indexOf(this);
    if (index >= 0) this.parent.children[index] = node;
  }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter((child) => child !== this);
  }
  addEventListener(name, listener) {
    if (!this.listeners[name]) this.listeners[name] = [];
    this.listeners[name].push(listener);
  }
  setAttribute(name, value) {
    this.attributes[name] = value;
  }
  removeAttribute(name) {
    delete this.attributes[name];
  }
  querySelectorAll(tag) {
    return this.findAll((element) => element !== this && element.tagName === tag);
  }
  focus() {}
  fire(name) {
    for (const listener of this.listeners[name] || []) listener({ preventDefault() {} });
  }
  get text() {
    return (this.textContent || "") + this.children.map((child) => child.text).join(" ");
  }
  findAll(predicate, found = []) {
    if (predicate(this)) found.push(this);
    for (const child of this.children) if (child instanceof StubElement) child.findAll(predicate, found);
    return found;
  }
}
for (const property of PROPERTIES) {
  Object.defineProperty(StubElement.prototype, property, { value: undefined, writable: true, configurable: true });
}

function createElement(tag) {
  const element = new StubElement(tag);
  if (tag === "select") {
    // A real <select> reports the value of its selected option, the first by default.
    Object.defineProperty(element, "value", {
      get() {
        const options = element.children.filter((child) => child.tagName === "option");
        const chosen = options.find((option) => option.selected) || options[0];
        return chosen ? chosen.value : "";
      },
    });
  }
  return element;
}

function openConsole() {
  const byId = {};
  for (const id of ["view", "toast", "readiness", "review-count", "key-button"]) byId[id] = new StubElement("div");
  const windowListeners = {};
  const requests = [];
  const timers = new Map();
  let nextTimer = 1;
  let hash = "";
  const sandbox = {
    console, Headers, URLSearchParams, structuredClone, FormData, Intl, JSON, Promise, Number, String,
    Object, Array, Map, Set, Date, Error, Math, process,
    Node: StubNode,
    URL: { createObjectURL: () => "blob:page", revokeObjectURL: () => {} },
    document: {
      hidden: false,
      getElementById: (id) => byId[id],
      createElement,
      createTextNode: (text) => new StubText(text),
      querySelectorAll: () => [],
    },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    location: {
      get hash() {
        return hash;
      },
      set hash(value) {
        const next = value.startsWith("#") ? value : `#${value}`;
        if (next === hash) return;
        hash = next;
        queueMicrotask(() => (windowListeners.hashchange || []).forEach((listener) => listener()));
      },
    },
    window: {
      addEventListener: (name, listener) => {
        if (!windowListeners[name]) windowListeners[name] = [];
        windowListeners[name].push(listener);
      },
      prompt: () => null,
    },
    fetch: (url, init = {}) =>
      new Promise((resolve) => {
        requests.push({
          path: url,
          method: init.method || "GET",
          body: init.body,
          answered: false,
          answer(status, json) {
            this.answered = true;
            resolve({ ok: status < 400, status, statusText: String(status), json: async () => json, blob: async () => ({}) });
          },
        });
      }),
    setInterval: (task, milliseconds) => {
      timers.set(nextTimer, { task, milliseconds, repeats: true });
      return nextTimer++;
    },
    setTimeout: (task, milliseconds) => {
      timers.set(nextTimer, { task, milliseconds, repeats: false });
      return nextTimer++;
    },
    clearInterval: (id) => timers.delete(id),
    clearTimeout: (id) => timers.delete(id),
  };
  sandbox.addEventListener = sandbox.window.addEventListener;
  vm.createContext(sandbox);

  const settle = async () => {
    for (let turn = 0; turn < 20; turn += 1) await new Promise((resolve) => setImmediate(resolve));
  };
  const page = {
    view: byId.view,
    toast: byId.toast,
    sandbox,
    requests,
    settle,
    async load() {
      vm.runInContext(fs.readFileSync(SCRIPT, "utf8"), sandbox, { filename: "app.js" });
      await settle();
    },
    evaluate: (source) => vm.runInContext(source, sandbox),
    waiting: (part) => requests.filter((request) => !request.answered && request.path.includes(part)),
    sent: (part) => requests.filter((request) => request.path.includes(part)),
    async answer(part, status, json) {
      for (const request of page.waiting(part)) request.answer(status, json);
      await settle();
    },
    // Let every timer set with this delay fire once.
    async elapse(milliseconds) {
      for (const [id, timer] of [...timers]) {
        if (timer.milliseconds !== milliseconds) continue;
        if (!timer.repeats) timers.delete(id);
        timer.task();
      }
      await settle();
    },
    intervals: () => [...timers.values()].filter((timer) => timer.repeats).map((timer) => timer.milliseconds).sort((a, b) => a - b),
    heading() {
      const [title] = byId.view.findAll((element) => element.tagName === "h1");
      return title ? title.text.trim().replace(/\s+/g, " ") : "";
    },
    async go(target) {
      sandbox.location.hash = target;
      await settle();
    },
    inputs: () => byId.view.findAll((element) => element.tagName === "input"),
    input: (value) => page.inputs().find((element) => element.value === value),
    button: (label) => byId.view.findAll((element) => element.tagName === "button").find((element) => element.text.trim() === label),
    hint: () => byId.view.findAll((element) => element.tagName === "span").map((element) => element.textContent).find((text) => text && /check(s)? (still fail|passes)/.test(text)),
  };
  return page;
}

// --------------------------------------------------------------------------- data

const stats = (approved) => ({
  by_status: { queued: 0, processing: 0, approved, review: 1, rejected: 0, duplicate: 0, failed: 0 },
  processed: approved + 1, approved_automatically: approved, approved_by_reviewer: 0, automation_rate: 0.5,
  mean_model_seconds: 3, prompt_tokens: 1, output_tokens: 1, kept_tier: {}, review_reasons: {},
  exports_pending: 0, jobs: {}, models: [], replay: false,
});
const SUMMARY = {
  id: 7, filename: "invoice.pdf", status: "review", reasons: ["arithmetic"], received_at: "2026-07-01T09:00:00Z",
  decided_at: null, decided_by: null, vendor_id: "V-1002", vendor_name: "Cartonnages du Forez SARL",
  invoice_number: "2603-0187", document_type: "invoice", issue_date: "2026-03-14", currency: "EUR",
  total_gross: "2603.22", mode: "text", kept_tier: "large", model_seconds: 5,
};
const IBAN_ON_FILE = "FR7625661212855461338126452";
const OTHER_IBAN = "FR7630006000011234567890189";
const INVOICE = {
  document_type: "invoice", invoice_number: "2603-0187", issue_date: "2026-03-14", due_date: "2026-04-28",
  currency: "EUR", supplier_name: "Cartonnages du Forez SARL", supplier_vat_id: "FR04960370096",
  supplier_siret: null, supplier_iban: IBAN_ON_FILE, po_number: null, referenced_invoice: null,
  lines: [{ description: "Carton", quantity: "2", unit_price: "1043.01", amount: "2086.02", vat_rate: "20" }],
  allowance_total: null, charge_total: null, total_net: "2086.02",
  vat_breakdown: [{ rate: "20", base: null, tax: "417.20" }], total_tax: "417.20", total_gross: "2603.22",
};
const check = (id, passed, fields = []) => ({ id, family: id.split(".")[0], passed, message: id, blocking: true, retriable: false, fields });
const detail = (overrides = {}) => ({
  ...SUMMARY, sha256: "0".repeat(64), size_bytes: 1, page_count: 1, note: null, error: null, invoice: INVOICE,
  checks: [check("arithmetic.totals", false, ["total_gross"])], attempts: [], events: [], prompt_tokens: 1,
  output_tokens: 1, ...overrides,
});
const list = (total) => ({ total, items: [SUMMARY] });
const rechecked = (...checks) => ({ checks, vendor_id: "V-1002", vendor_name: "Cartonnages du Forez SARL" });
const ALL_PASS = rechecked(check("arithmetic.totals", true), check("bank.on_file", true));
const BANK_FAILS = rechecked(check("arithmetic.totals", true), check("bank.on_file", false, ["supplier_iban"]));

async function openDocument(overrides) {
  const page = openConsole();
  await page.load();
  await page.answer("/api/stats", 200, stats(3));
  await page.answer("/api/documents?limit=8", 200, list(4));
  await page.go("#/documents/7");
  await page.answer("/api/documents/7", 200, detail(overrides));
  await page.answer("/pages/", 200, {});
  return page;
}

// ---------------------------------------------------------------------- scenarios

const scenarios = {
  // The reviewer opens a document while the Overview is still loading; the Overview
  // answers last.
  async late_overview() {
    const page = openConsole();
    await page.load();
    await page.go("#/documents/7");
    await page.answer("/api/documents/7", 200, detail());
    await page.answer("/api/stats", 200, stats(3));
    await page.answer("/api/documents?limit=8", 200, list(4));
    return { view: page.heading(), address: page.sandbox.location.hash, timers: page.intervals() };
  },

  // Overview still loading -> "Review" -> a document, corrected -> the statistics change.
  async orphan_timer() {
    const page = openConsole();
    await page.load();
    await page.go("#/review");
    await page.answer("/api/stats", 200, stats(3));
    await page.answer("/api/documents?limit=8", 200, list(4));
    await page.answer("/api/documents?limit=100&status=review", 200, list(1));
    await page.go("#/documents/7");
    await page.answer("/api/documents/7", 200, detail());
    page.input("2603.22").value = "2503.22";
    const timers = page.intervals();
    await page.elapse(3000);
    await page.answer("/api/stats", 200, stats(4));
    await page.answer("/api/documents?limit=8", 200, list(5));
    return {
      timers_on_the_document: timers,
      view_after_the_statistics_changed: page.heading(),
      correction_still_on_screen: page.inputs().some((element) => element.value === "2503.22"),
    };
  },

  // Two rechecks answer in the other order; the reviewer then approves what is shown.
  async late_recheck() {
    const page = await openDocument();
    const gross = page.input("2603.22");
    gross.value = "2503.22";
    gross.fire("input");
    await page.elapse(450);
    const iban = page.input(IBAN_ON_FILE);
    iban.value = OTHER_IBAN;
    iban.fire("input");
    await page.elapse(450);
    const [first, second] = page.waiting("/recheck");
    second.answer(200, BANK_FAILS);
    await page.settle();
    first.answer(200, ALL_PASS);
    await page.settle();
    const hint = page.hint();
    page.view.findAll((element) => element.tagName === "textarea")[0].value = "confirmed with the supplier";
    page.button("Approve").fire("click");
    await page.settle();
    const [decision] = page.sent("/decision");
    return { hint, decision: JSON.parse(decision.body) };
  },

  // The reviewer edits a field and approves before the recheck of that edit has run.
  async unseen_check() {
    const page = await openDocument({ checks: [check("arithmetic.totals", true), check("bank.on_file", true)] });
    const iban = page.input(IBAN_ON_FILE);
    iban.value = OTHER_IBAN;
    iban.fire("input");
    page.view.findAll((element) => element.tagName === "textarea")[0].value = "fine";
    page.button("Approve").fire("click");
    await page.settle();
    await page.answer("/recheck", 200, BANK_FAILS);
    return { decisions_sent: page.sent("/decision").length, toast: page.toast.textContent, hint: page.hint() };
  },

  async double_click() {
    const approving = await openDocument({ checks: [check("arithmetic.totals", true)] });
    approving.button("Approve").fire("click");
    approving.button("Approve").fire("click");
    await approving.settle();
    const reading = await openDocument();
    reading.button("Read it again").fire("click");
    reading.button("Read it again").fire("click");
    await reading.settle();
    return { decisions_sent: approving.sent("/decision").length, reprocess_sent: reading.sent("/reprocess").length };
  },

  // The day shown for "2026-03-04" is the fourth of March wherever the reviewer sits.
  async dates() {
    const page = openConsole();
    await page.load();
    const result = {};
    for (const zone of ["Europe/Paris", "America/New_York", "Pacific/Auckland"]) {
      process.env.TZ = zone;
      result[zone] = page.evaluate('day("2026-03-04")') === new Date(2026, 2, 4).toLocaleDateString();
    }
    return result;
  },

  // A document no worker has read yet: its page count is unknown.
  async unknown_page_count() {
    const page = openConsole();
    await page.load();
    await page.go("#/documents/7");
    await page.answer("/api/documents/7", 200, detail({ status: "failed", page_count: 0 }));
    await page.answer("/pages/1", 200, {});
    await page.answer("/pages/2", 200, {});
    await page.answer("/pages/3", 404, { detail: "no such page" });
    await page.settle();
    const asked = page.sent("/pages/").map((request) => Number(request.path.split("/").pop()));
    const shown = page.view.findAll((element) => element.tagName === "img").length;
    return { asked, shown };
  },
};

const scenario = scenarios[process.argv[2]];
if (!scenario) {
  console.error(`unknown scenario: ${process.argv[2]}; one of ${Object.keys(scenarios).join(", ")}`);
  process.exit(2);
}
scenario().then(
  (result) => process.stdout.write(`${JSON.stringify(result)}\n`),
  (error) => {
    console.error(error);
    process.exit(1);
  },
);
