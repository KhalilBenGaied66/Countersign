# Evaluation: `cascade` on the `test` split

Models: `qwen3.5:4b`, `qwen3.5:9b`. Prompt: `extract_v5`. Checks: on.

Percentages are followed by their 95 % Wilson interval where it matters, and by the counts they come from.

## Summary

| Measure | Value |
|---|---|
| Documents | 270 |
| **Harmful decisions** | **2** (2 wrong approvals, 0 invoices set aside) |
| Approved without a person, among documents that can be | 94.5 % [90.2 to 97.0] (173/183) |
| Approvals that were right | 98.9 % [95.9 to 99.7] (173/175) |
| Stopped, among documents that must not be approved | 97.7 % [92.0 to 99.4] (85/87) |
| Stopped for the expected reason | 96.5 % (82/85) |
| Outcome exactly as labelled | 95.2 % (257/270) |
| Invoices with every critical field right | 94.6 % [91.1 to 96.7] (244/258) |
| Invoices with every line right | 97.3 % (251/258) |
| Documents read by more than one tier | 28.5 % (77/270) |
| Model time per document | mean 12.35 s, median 6.72 s, 95th percentile 35.02 s |
| Tokens per document | 2775 in, 855 out |
| Model calls that failed | 0 |

## Field accuracy (invoices and credit notes)

| Field | Correct |
|---|---|
| `document_type` | 98.8 % (255/258) |
| `invoice_number` | 98.8 % (255/258) |
| `issue_date` | 98.1 % (253/258) |
| `due_date` | 98.4 % (254/258) |
| `currency` | 98.8 % (255/258) |
| `supplier_vat_id` | 98.8 % (255/258) |
| `supplier_iban` | 97.7 % (252/258) |
| `po_number` | 99.6 % (257/258) |
| `total_net` | 97.3 % (251/258) |
| `total_tax` | 96.9 % (250/258) |
| `total_gross` | 96.9 % (250/258) |
| `supplier_siret` | 100.0 % (258/258) |
| `referenced_invoice` | 99.6 % (257/258) |
| `allowance_total` | 100.0 % (258/258) |
| `charge_total` | 99.6 % (257/258) |

## By scenario

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| bank_changed | 12 | 0 | n/a | 100.0 % (12/12) | 100.0 % (12/12) | 7.47 s |
| bank_invalid | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 4.96 s |
| clean | 112 | 0 | 99.1 % (111/112) | n/a | 100.0 % (112/112) | 6.73 s |
| credit_note | 10 | 0 | 100.0 % (10/10) | n/a | 100.0 % (10/10) | 4.12 s |
| duplicate | 8 | 0 | n/a | 100.0 % (8/8) | 100.0 % (8/8) | 10.49 s |
| einvoice | 12 | 0 | 100.0 % (12/12) | n/a | 100.0 % (12/12) | 0.0 s |
| einvoice_tampered | 4 | 0 | n/a | 100.0 % (4/4) | 0.0 % (0/4) | 0.0 s |
| injection | 14 | 0 | 61.5 % (8/13) | 100.0 % (1/1) | 57.1 % (8/14) | 8.26 s |
| long | 12 | 0 | 100.0 % (12/12) | n/a | 100.0 % (12/12) | 76.63 s |
| missing_field | 6 | 0 | n/a | 100.0 % (6/6) | 66.7 % (4/6) | 15.58 s |
| not_invoice | 12 | 0 | n/a | 100.0 % (12/12) | n/a | 15.76 s |
| purchase_order | 12 | 0 | n/a | 100.0 % (12/12) | 100.0 % (12/12) | 6.72 s |
| scan | 24 | 0 | 83.3 % (20/24) | n/a | 95.8 % (23/24) | 23.96 s |
| scan_mismatch | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 27.91 s |
| totals_mismatch | 14 | 2 | n/a | 85.7 % (12/14) | 92.9 % (13/14) | 15.08 s |
| unknown_supplier | 10 | 0 | n/a | 100.0 % (10/10) | 100.0 % (10/10) | 4.9 s |

## By group

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| seen suppliers | 118 | 0 | 94.9 % (75/79) | 100.0 % (39/39) | 95.6 % (108/113) | 9.19 s |
| held-out suppliers | 152 | 2 | 94.2 % (98/104) | 95.8 % (46/48) | 93.8 % (136/145) | 14.79 s |
| text layer | 226 | 2 | 95.9 % (141/147) | 97.5 % (77/79) | 95.8 % (205/214) | 11.71 s |
| scans | 28 | 0 | 83.3 % (20/24) | 100.0 % (4/4) | 96.4 % (27/28) | 24.52 s |
| embedded e-invoice | 16 | 0 | 100.0 % (12/12) | 100.0 % (4/4) | 75.0 % (12/16) | 0.0 s |
| language: de | 33 | 1 | 91.3 % (21/23) | 90.0 % (9/10) | 90.9 % (30/33) | 7.27 s |
| language: en | 43 | 0 | 85.7 % (24/28) | 100.0 % (15/15) | 95.0 % (38/40) | 7.5 s |
| language: es | 19 | 0 | 92.9 % (13/14) | 100.0 % (5/5) | 100.0 % (17/17) | 7.27 s |
| language: fr | 163 | 1 | 98.2 % (107/109) | 98.1 % (53/54) | 94.9 % (148/156) | 15.63 s |
| language: it | 12 | 0 | 88.9 % (8/9) | 100.0 % (3/3) | 91.7 % (11/12) | 7.07 s |
| layout: anglo | 24 | 0 | 89.5 % (17/19) | 100.0 % (5/5) | 95.8 % (23/24) | 6.46 s |
| layout: classic | 66 | 0 | 95.5 % (42/44) | 100.0 % (22/22) | 95.2 % (59/62) | 9.4 s |
| layout: columns | 54 | 0 | 97.0 % (32/33) | 100.0 % (21/21) | 96.1 % (49/51) | 8.95 s |
| layout: compact | 39 | 0 | 100.0 % (30/30) | 100.0 % (9/9) | 97.4 % (37/38) | 36.94 s |
| layout: footer_ids | 44 | 1 | 89.3 % (25/28) | 93.8 % (15/16) | 90.0 % (36/40) | 6.87 s |
| layout: german | 33 | 1 | 91.3 % (21/23) | 90.0 % (9/10) | 90.9 % (30/33) | 7.27 s |
| layout: ledger | 10 | 0 | 100.0 % (6/6) | 100.0 % (4/4) | 100.0 % (10/10) | 9.17 s |

## Harmful decisions

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| T-040 | totals_mismatch/rate | footer_ids, fr | review | approved |  |  |
| T-244 | totals_mismatch/rate | german, de | review | approved |  |  |

## Other documents not handled as labelled

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| T-022 | scan | anglo, en | approved | review | consensus |  |
| T-027 | scan | columns, it | approved | review | consensus |  |
| T-039 | not_invoice/delivery_note | classic, es | rejected | review | document_type, missing_field, invoice_number |  |
| T-048 | injection/hidden_totals | classic, fr | approved | review | arithmetic | total_net, total_tax, total_gross |
| T-053 | injection/hidden_type | german, de | approved | review | document_type, not_invoice | document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, total_net, total_tax, total_gross |
| T-057 | scan | footer_ids, es | approved | review | consensus |  |
| T-063 | injection/hidden_type | german, de | approved | review | document_type, not_invoice | document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, po_number, total_net, total_tax, total_gross, charge_total |
| T-079 | injection/hidden_totals | anglo, en | approved | review | arithmetic | total_net, total_tax, total_gross |
| T-107 | scan | classic, fr | approved | review | arithmetic, consensus | total_tax, total_gross |
| T-124 | clean | footer_ids, en | approved | review | arithmetic |  |
| T-237 | injection/hidden_type | footer_ids, en | approved | review | document_type, not_invoice | document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, total_net, total_tax, total_gross |
