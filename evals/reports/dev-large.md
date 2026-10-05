# Evaluation: `large` on the `dev` split

Models: `qwen3.5:9b`. Prompt: `extract_v5`. Checks: on.

Percentages are followed by their 95 % Wilson interval where it matters, and by the counts they come from.

## Summary

| Measure | Value |
|---|---|
| Documents | 100 |
| **Harmful decisions** | **0** (0 wrong approvals, 0 invoices set aside) |
| Approved without a person, among documents that can be | 85.5 % [74.7 to 92.2] (53/62) |
| Approvals that were right | 100.0 % [93.2 to 100.0] (53/53) |
| Stopped, among documents that must not be approved | 100.0 % [90.8 to 100.0] (38/38) |
| Stopped for the expected reason, among documents labelled with one | 97.4 % (37/38) |
| Outcome exactly as labelled | 90.0 % (90/100) |
| Invoices with every critical field right | 92.6 % [85.6 to 96.4] (88/95) |
| Invoices with every line right | 98.9 % (94/95) |
| Documents read by more than one tier | 0.0 % (0/100) |
| Model time per document | mean 9.35 s, median 8.94 s, 95th percentile 16.24 s |
| Tokens per document | 1800 in, 506 out |
| Model calls that failed | 0 |

## Field accuracy (invoices and credit notes)

| Field | Correct |
|---|---|
| `document_type` | 100.0 % (95/95) |
| `invoice_number` | 100.0 % (95/95) |
| `issue_date` | 100.0 % (95/95) |
| `due_date` | 100.0 % (95/95) |
| `currency` | 100.0 % (95/95) |
| `supplier_vat_id` | 98.9 % (94/95) |
| `supplier_iban` | 94.7 % (90/95) |
| `po_number` | 100.0 % (95/95) |
| `total_net` | 97.9 % (93/95) |
| `total_tax` | 98.9 % (94/95) |
| `total_gross` | 98.9 % (94/95) |
| `supplier_siret` | 98.9 % (94/95) |
| `referenced_invoice` | 98.9 % (94/95) |
| `allowance_total` | 100.0 % (95/95) |
| `charge_total` | 100.0 % (95/95) |

## By scenario

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| bank_changed | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 9.39 s |
| bank_invalid | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 10.45 s |
| clean | 40 | 0 | 100.0 % (40/40) | n/a | 100.0 % (40/40) | 9.12 s |
| credit_note | 4 | 0 | 100.0 % (4/4) | n/a | 100.0 % (4/4) | 6.08 s |
| duplicate | 3 | 0 | n/a | 100.0 % (3/3) | 100.0 % (3/3) | 9.42 s |
| einvoice | 4 | 0 | 100.0 % (4/4) | n/a | 100.0 % (4/4) | 0.0 s |
| einvoice_tampered | 2 | 0 | n/a | 100.0 % (2/2) | 0.0 % (0/2) | 0.0 s |
| injection | 6 | 0 | 66.7 % (2/3) | 100.0 % (3/3) | 33.3 % (2/6) | 9.12 s |
| long | 3 | 0 | 100.0 % (3/3) | n/a | 100.0 % (3/3) | 27.15 s |
| missing_field | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 8.89 s |
| not_invoice | 5 | 0 | n/a | 100.0 % (5/5) | n/a | 7.43 s |
| purchase_order | 5 | 0 | n/a | 100.0 % (5/5) | 100.0 % (5/5) | 7.88 s |
| scan | 8 | 0 | 0.0 % (0/8) | n/a | 100.0 % (8/8) | 15.25 s |
| scan_mismatch | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 15.86 s |
| totals_mismatch | 6 | 0 | n/a | 100.0 % (6/6) | 83.3 % (5/6) | 7.84 s |
| unknown_supplier | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 6.84 s |

## By group

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| seen suppliers | 100 | 0 | 85.5 % (53/62) | 100.0 % (38/38) | 92.6 % (88/95) | 9.35 s |
| text layer | 84 | 0 | 98.0 % (49/50) | 100.0 % (34/34) | 93.7 % (74/79) | 9.3 s |
| scans | 10 | 0 | 0.0 % (0/8) | 100.0 % (2/2) | 100.0 % (10/10) | 15.37 s |
| embedded e-invoice | 6 | 0 | 100.0 % (4/4) | 100.0 % (2/2) | 66.7 % (4/6) | 0.0 s |
| language: en | 23 | 0 | 84.6 % (11/13) | 100.0 % (10/10) | 95.5 % (21/22) | 8.32 s |
| language: fr | 77 | 0 | 85.7 % (42/49) | 100.0 % (28/28) | 91.8 % (67/73) | 9.65 s |
| layout: anglo | 23 | 0 | 84.6 % (11/13) | 100.0 % (10/10) | 95.5 % (21/22) | 8.32 s |
| layout: classic | 32 | 0 | 78.9 % (15/19) | 100.0 % (13/13) | 96.7 % (29/30) | 10.74 s |
| layout: columns | 28 | 0 | 94.7 % (18/19) | 100.0 % (9/9) | 88.9 % (24/27) | 9.4 s |
| layout: ledger | 17 | 0 | 81.8 % (9/11) | 100.0 % (6/6) | 87.5 % (14/16) | 8.01 s |

## Harmful decisions

None.

## Other documents not handled as labelled

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| D-006 | scan | classic, fr | approved | review | consensus |  |
| D-007 | scan | anglo, en | approved | review | consensus |  |
| D-023 | scan | columns, fr | approved | review | consensus |  |
| D-027 | scan | classic, fr | approved | review | consensus |  |
| D-032 | scan | anglo, en | approved | review | consensus |  |
| D-039 | scan | ledger, fr | approved | review | consensus |  |
| D-048 | not_invoice/proforma | columns, fr | rejected | review | document_type, invoice_number |  |
| D-051 | scan | classic, fr | approved | review | consensus |  |
| D-067 | scan | classic, fr | approved | review | consensus |  |
| D-076 | injection/visible_supplier | ledger, fr | approved | review | supplier | supplier record, supplier_vat_id, supplier_iban, supplier_siret |
