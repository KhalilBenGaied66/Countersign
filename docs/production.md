# Before real use

This repository is a prototype measured on synthetic documents. This page lists what
separates it from a system an accounts-payable team could rely on. Nothing below is
done unless stated.

## First: real documents

| Step | With whom |
|---|---|
| Run the pipeline in shadow mode on a few hundred real invoices already processed by hand, and compare with what was posted | accounts payable |
| Build the evaluation set from those documents, including the ones that went wrong in the past | accounts payable |
| Review every check with the people who own the rule: tolerances, which suppliers need an order, what a duplicate is | accounts payable, purchasing, internal control |
| Decide which outcomes may ever be automatic, and up to what amount | finance management |

Until then the numbers in [evaluation.md](evaluation.md) say how the system behaves on
documents built for the purpose, not on a company's mail.

## Reading

| Topic | State | To do |
|---|---|---|
| Scans | one page, read from its image by two models; no text to check values against, nor to find a second account or the addressee in | measure on real scans; an OCR layer to give the checks a text to work on; page-by-page reading for longer scans |
| Languages | prompt and label vocabulary developed on French and English; German, Spanish and Italian measured as held out | label vocabulary per language in use; evaluation per language |
| Long documents | twelve pages, about sixty lines | split by page and merge, or accept header-only extraction for suppliers whose lines are not needed |
| Several invoices in one file | read as the first one | split on titles and page numbering before extraction |
| Line discounts | the form has no field for them: quantity × unit price then differs from the amount and the invoice goes to a person | a discount per line in the schema, which means a new prompt version and new recordings |
| Credit notes numbered apart | the supplier's numbering is told from one invoice number; a second example can be given per supplier | fill it from the ERP's history |
| Amounts grouped by plain spaces | "345,00" out of "12 345,00" counts as printed, because that space may separate two columns | positions of the text on the page, instead of its lines |
| Handwriting, stamps, photos of paper | not handled, not measured | out of scope until measured |
| Hidden text layer that differs from the page | not detected, except for bank accounts, order numbers, the title and the order of day and month | compare the text layer with a rendering of the page |
| Models | two open-weight models chosen because they were on the machine | compare candidates on the real set; pin model digests |

## Integration

The prototype reads three JSON files and writes one JSON file per approved document.

- Vendor master and purchase orders come from the ERP, with their own access rights
  and change history. The loader in `master.py` is the place to replace.
- Purchase order matching is a single comparison of the net total with the order.
  Partial deliveries, several invoices against one order, and matching against goods
  receipts are not modelled; the remaining amount of an order is not tracked.
- One approval per supplier and invoice number, for good: a supplier whose numbering
  restarts each year needs the year in that key.
- The export is a file drop. A real integration posts to the ERP and reads back the
  posting reference; the outbox row is where that reference belongs.
- Documents arrive by upload. A mailbox or an e-invoicing platform connector is not
  written.
- Embedded e-invoices are read from the Cross Industry Invoice syntax only, without
  schema validation. UBL is not read.

## Operation

| Topic | State | To do |
|---|---|---|
| Database | SQLite, one transaction at a time; the storage and API tests also pass on PostgreSQL 17 | backups, connection pooling limits, a load test of the queue |
| Queue | a lease that is not renewed, as long as the slowest document (25 minutes by default) | a heartbeat from the worker, so that a dead worker is noticed in seconds |
| Parsing | in the worker, with a limit on each compressed stream, not on the whole file | a process with memory and time limits of its own for the PDF parser and the renderer |
| Throughput | one GPU, one request at a time | a serving stack with batching (vLLM) and a measurement of latency under concurrency |
| Observability | metrics, traces and logs emitted | dashboards, alerts, and a collector to send traces to: the OTLP export is tested against a local receiver, never against a real one |
| Deployment | one container image | an environment, secrets management, upgrades |
| Files | local directory | object storage, retention, deletion |

## Control

| Topic | State | To do |
|---|---|---|
| Identity | static API keys with two roles; no list of accepted host names | single sign-on; roles per entity or supplier; rate limiting |
| Approval | one reviewer | a second approver above a threshold; separation between master-data editing and approval |
| Audit | every decision recorded with corrections and overridden checks | export to the company's audit store; immutability |
| Personal data | no content in logs or traces; models local | retention, deletion, data protection impact assessment |

## Suggested order

1. Shadow run on real documents and a real evaluation set.
2. Read-only connection to the vendor master and purchase orders.
3. Review screen used by the team on everything, with no automatic approval.
4. Automatic approval for the suppliers and amounts the measurements support.
5. Posting to the ERP.
