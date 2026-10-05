# Evaluation: `cascade` on the `dev` split

Models: `qwen3.5:4b`, `qwen3.5:9b`. Prompt: `extract_v5`. Checks: on.

Percentages are followed by their 95 % Wilson interval where it matters, and by the counts they come from.

## Summary

| Measure | Value |
|---|---|
| Documents | 100 |
| **Harmful decisions** | **0** (0 wrong approvals, 0 invoices set aside) |
| Approved without a person, among documents that can be | 96.8 % [89.0 to 99.1] (60/62) |
| Approvals that were right | 100.0 % [94.0 to 100.0] (60/60) |
| Stopped, among documents that must not be approved | 100.0 % [90.8 to 100.0] (38/38) |
| Stopped for the expected reason, among documents labelled with one | 100.0 % (38/38) |
| Outcome exactly as labelled | 98.0 % (98/100) |
| Invoices with every critical field right | 92.6 % [85.6 to 96.4] (88/95) |
| Invoices with every line right | 98.9 % (94/95) |
| Documents read by more than one tier | 25.0 % (25/100) |
| Model time per document | mean 9.15 s, median 6.6 s, 95th percentile 24.6 s |
| Tokens per document | 2519 in, 629 out |
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
| `referenced_invoice` | 100.0 % (95/95) |
| `allowance_total` | 100.0 % (95/95) |
| `charge_total` | 100.0 % (95/95) |

## By scenario

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| bank_changed | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 9.01 s |
| bank_invalid | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 7.09 s |
| clean | 40 | 0 | 100.0 % (40/40) | n/a | 100.0 % (40/40) | 6.93 s |
| credit_note | 4 | 0 | 100.0 % (4/4) | n/a | 100.0 % (4/4) | 4.15 s |
| duplicate | 3 | 0 | n/a | 100.0 % (3/3) | 100.0 % (3/3) | 6.42 s |
| einvoice | 4 | 0 | 100.0 % (4/4) | n/a | 100.0 % (4/4) | 0.0 s |
| einvoice_tampered | 2 | 0 | n/a | 100.0 % (2/2) | 0.0 % (0/2) | 0.0 s |
| injection | 6 | 0 | 66.7 % (2/3) | 100.0 % (3/3) | 33.3 % (2/6) | 9.38 s |
| long | 3 | 0 | 100.0 % (3/3) | n/a | 100.0 % (3/3) | 18.24 s |
| missing_field | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 14.85 s |
| not_invoice | 5 | 0 | n/a | 100.0 % (5/5) | n/a | 6.68 s |
| purchase_order | 5 | 0 | n/a | 100.0 % (5/5) | 100.0 % (5/5) | 5.34 s |
| scan | 8 | 0 | 87.5 % (7/8) | n/a | 100.0 % (8/8) | 24.26 s |
| scan_mismatch | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 29.86 s |
| totals_mismatch | 6 | 0 | n/a | 100.0 % (6/6) | 83.3 % (5/6) | 13.14 s |
| unknown_supplier | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 4.64 s |

## By group

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| seen suppliers | 100 | 0 | 96.8 % (60/62) | 100.0 % (38/38) | 92.6 % (88/95) | 9.15 s |
| text layer | 84 | 0 | 98.0 % (49/50) | 100.0 % (34/34) | 93.7 % (74/79) | 7.87 s |
| scans | 10 | 0 | 87.5 % (7/8) | 100.0 % (2/2) | 100.0 % (10/10) | 25.38 s |
| embedded e-invoice | 6 | 0 | 100.0 % (4/4) | 100.0 % (2/2) | 66.7 % (4/6) | 0.0 s |
| language: en | 23 | 0 | 92.3 % (12/13) | 100.0 % (10/10) | 95.5 % (21/22) | 8.0 s |
| language: fr | 77 | 0 | 98.0 % (48/49) | 100.0 % (28/28) | 91.8 % (67/73) | 9.5 s |
| layout: anglo | 23 | 0 | 92.3 % (12/13) | 100.0 % (10/10) | 95.5 % (21/22) | 8.0 s |
| layout: classic | 32 | 0 | 100.0 % (19/19) | 100.0 % (13/13) | 96.7 % (29/30) | 11.24 s |
| layout: columns | 28 | 0 | 100.0 % (19/19) | 100.0 % (9/9) | 88.9 % (24/27) | 7.99 s |
| layout: ledger | 17 | 0 | 90.9 % (10/11) | 100.0 % (6/6) | 87.5 % (14/16) | 8.68 s |

## Harmful decisions

None.

## Other documents not handled as labelled

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| D-007 | scan | anglo, en | approved | review | consensus |  |
| D-076 | injection/visible_supplier | ledger, fr | approved | review | supplier | supplier record, supplier_vat_id, supplier_iban, supplier_siret |
