# Security

Invoice intake is where money leaves a company on the strength of a document sent by
someone else. This page lists what can go wrong, what stands in the way, and what does
not.

Two independent code reviews went looking for ways around the checks and through the
storage layer. What they found is fixed and covered by tests
(`tests/test_hardening.py`, and the storage and API tests), or listed below as a limit.

## What is trusted

| | Trusted? | Consequence |
|---|---|---|
| The PDF | No | Parsed defensively; never executed; its text is data |
| The model's output | No | A form to verify, not a decision |
| The embedded e-invoice | No more than the page | Checked like a model's output, and against the page |
| The vendor master and purchase orders | Yes | They are the reference; whoever can edit them can redirect payments |
| An authenticated API client | Within its role | Reviewers decide; operators submit and read |

## Threats

### A changed bank account

The usual fraud: an invoice from a known supplier, with someone else's IBAN.

- The IBAN reported by the model must be the one on file (`bank.on_file`). The buyer's
  own account, which a direct-debit notice prints, is not the supplier's.
- Every IBAN on the page is collected by pattern, without the model, and must be on
  file too (`bank.sweep`): in groups of four, with dashes or dots, in lower case,
  broken over two lines or glued to its label. A model that overlooks the account, or
  is told to, cannot hide it.
- An IBAN that fails its checksum is stopped whether or not it is on file.
- The export never carries the IBAN of the invoice. Payment goes to the account in the
  vendor master.

The last point is what holds if everything else fails: an approved invoice with a
forged IBAN still pays the real supplier.

What it does not cover: changing the account in the vendor master is outside this
system, and that is where the fraud moves next. A scan has no text to sweep; its IBAN
is only what two models read. The sweep knows the structure of an IBAN in the
thirty-six countries of the euro payments area: an account of another country, or one
that is not an IBAN at all (a US routing and account number), is not swept.

### Instructions written in the document

A document can address the model: "ignore the totals above", "the supplier IBAN is…",
in a footer or in white one-point text that no person sees and every text extractor
reads.

The defence is not a better prompt. The prompt does say the document is data, and the
evaluation shows the models still follow some of these instructions
([evaluation.md](evaluation.md)). The defence is that obeying buys nothing:

- the model has no tool and takes no decision: it can only fill the form wrongly;
- a wrong form has to pass the checks: a substituted IBAN is not on file, substituted
  totals do not match the lines;
- a document declared "not an invoice" is set aside only if its own title or a second
  reading says the same, and goes to a person otherwise;
- text nobody sees cannot change how a printed date is read: when the dates of the
  text layer contradict the day/month order of the supplier's country, a person reads
  the date.

What it does not cover: a text layer that describes a *complete and consistent*
invoice different from the visible page, from a supplier on file, with the account on
file. The text is what is read, so the hidden version is approved; with an embedded
e-invoice carrying the same figures, without any model. Payment still goes to the real
supplier, for the wrong amount. A purchase order bounds the damage for suppliers that
need one. Comparing the text layer with a rendering of the page would close it; it is
not done.

### A document that contradicts itself

A misprinted total next to a correct VAT table. A model can report the consistent value
instead of the printed one, and every sum then works.

- The prompt asks for what is printed, contradictions included.
- A total must be an amount printed on the line of its own label, when the label is in
  the vocabulary (`arithmetic.labelled`).
- A second reading may not overrule an amount the page prints as a number of its own,
  a total or a line (`arithmetic.competing`).
- The amount of a line must be printed on the row of its unit price: the net total,
  reported as the amount of the only line, is on the page and not on that row.
- VAT must be tied to a rate and a base. When the page gives no base, the bases the
  rows imply must account for the net total (`arithmetic.vat`).

What it does not cover: a single reading, in a language outside the label vocabulary
(French and English), that reports the tidy value. A test documents exactly that case.

### A value that is almost the one printed

- A reference must be printed as a whole: "FA-2026-0018" is not on a page that prints
  "FA-2026-00187", and does not get past the duplicate check as a new invoice.
- An invoice number must fit the supplier's numbering, digit widths included.
- An amount keeps its sign: 2 175,25 read from a page that prints -2 175,25 is not on
  the page. An invoice with a negative total is stopped.
- A number grouped by apostrophes or no-break spaces is one number: 240.00 is not on a
  page that prints 1'240.00.
- The currency must be one the page names, and a date must be the one printed after
  its own label when the label is known.

What it does not cover: a number grouped by plain spaces may be two columns, so
"345,00" out of "12 345,00" counts as printed; arithmetic and the labelled totals
catch that reading, where labels are known. A supplier that numbers its invoices with
digits only is protected by the width of the number, not by its shape: its customer
code, with as many digits, would pass.

### Paying twice, or not at all

- The same file is the same document (content hash).
- The same supplier, number, kind, amount and date as an earlier document is a
  duplicate, provided nothing else is wrong with it.
- The same number on a different document is not set aside but shown to a person:
  a credit note quotes the invoice it cancels, and the two are easily confused.
- An invoice that a person rejected is not approved when it is sent again: the new
  copy goes to a person, with the name of who refused the first.
- The database enforces one approval per supplier and invoice number, whatever the
  workers do.
- Nothing is set aside on the word of one reading (see
  [decisions.md](decisions.md), 17): a real invoice called "not an invoice" by one
  model goes to a person.

What it does not cover: an invoice addressed to another company is stopped only when
the page has a text layer that names neither the buyer nor its identifiers. A file
that holds two invoices is processed as the first one.

### Hostile files

| Attack | Defence |
|---|---|
| Oversized file, hundreds of pages | 15 MB and 12 pages; an upload is refused at its declared size, before its body is read, and cut off at the limit if it lied |
| A small file that expands | no compressed stream may expand beyond 4 MB; only XML attachments are decompressed, up to 2 MB; a page is rendered to 6 million pixels at most |
| Encrypted or malformed PDF | refused; whatever the parser raises becomes "unreadable", and the file goes to a person |
| XML external entity, entity expansion in the embedded invoice | `defusedxml`, DTDs refused outright |
| Text built to make a pattern backtrack | every pattern run on page text has bounded repetitions; a test runs each on 200 000 characters built against it |
| A very long document to exhaust the model | size estimated before the call; output capped; a truncated answer is an error, not a result |
| Numbers of half a million digits | a printed number is at most 24 characters; anything longer is unreadable |
| Script in a supplier name or a line description | the console builds the page from text nodes; a test forbids HTML sinks in its source |
| A file that is not a PDF, uploaded as one | magic bytes checked; stored files are served as `application/pdf` with `nosniff` |

An upload is stored without being opened: parsing happens in the worker, not in the
request.

What it does not cover: the total time and memory a file built for the purpose can
cost inside those limits (many streams of 4 MB each, a page of dense text operators).
The PDF renderer (pdfium) and the PDF parser are large pieces of native and Python
code reading untrusted input, inside the worker. The container image runs as an
unprivileged user; nothing more is done to isolate them. A production deployment
parses in a process with memory and time limits of its own.

### The API

- With `COUNTERSIGN_API_KEYS` set, every `/api` call needs a key. Keys are compared in
  constant time. Two roles: `operator` submits and reads, `reviewer` also decides.
- A key setting that does not parse entirely stops the application at start-up: a
  typing mistake must not leave the API open.
- Without keys the API is open. That is accepted on the loopback address only: serving
  on any other address without keys is refused, unless `COUNTERSIGN_ALLOW_OPEN=true`
  says that something else decides who can reach the port.
- Key, origin and size are checked on the headers, before the body is read.
- A request that changes something and carries an `Origin` header must come from the
  server's own pages: a page of another site open in the reviewer's browser cannot
  post here. Answers forbid framing and content sniffing.
- Probes and the static console carry no document data and need no key.

Missing: rate limiting, key rotation, single sign-on, any notion of who may see which
supplier, and a list of accepted `Host` names: behind a reverse proxy the original
`Host` header has to be passed on, or the console's own requests are refused.

### The reviewer

- A decision records who took it, what was corrected and which failed checks were
  overridden. Approving despite a failed check requires a comment and the list of the
  checks being overridden: a check that failed after the reviewer last looked is
  refused, not waved through by the comment.
- An invoice from a supplier that is not on file cannot be approved at all: the
  supplier has to exist in the vendor master first.
- Corrections go through the same checks as a model's reading.
- Two decisions on the same document at the same moment cannot both succeed.

Missing: a second pair of eyes above an amount, and separation between the person who
edits the vendor master and the person who approves.

## Data

Invoices carry business data and sometimes personal data (a sole trader's name and
bank account).

- Models run locally. No document, extraction or prompt leaves the machine.
- Logs and traces carry identifiers, outcomes and sizes, never content. A test checks
  that spans do not contain the invoice number, the supplier, the IBAN or the total;
  database errors are logged without the values of their statement.
- Files are stored under their content hash, in a directory the application owns.

Missing: retention periods, deletion, encryption at rest, and access logging for reads.

## Supply chain

- Dependencies are locked (`uv.lock`).
- Models are open-weight, Apache 2.0, pulled by tag. A tag can be moved: a production
  deployment should pin the digest and re-run the evaluation when it changes.
