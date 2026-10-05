# Evaluation: `large` on the `test` split

Models: `qwen3.5:9b`. Prompt: `extract_v5`. Checks: on.

Percentages are followed by their 95 % Wilson interval where it matters, and by the counts they come from.

## Summary

| Measure | Value |
|---|---|
| Documents | 270 |
| **Harmful decisions** | **1** (1 wrong approvals, 0 invoices set aside) |
| Approved without a person, among documents that can be | 93.4 % [88.9 to 96.2] (171/183) |
| Approvals that were right | 99.4 % [96.8 to 99.9] (171/172) |
| Stopped, among documents that must not be approved | 98.9 % [93.8 to 99.8] (86/87) |
| Stopped for the expected reason | 96.5 % (83/86) |
| Outcome exactly as labelled | 94.8 % (256/270) |
| Invoices with every critical field right | 92.2 % [88.3 to 94.9] (238/258) |
| Invoices with every line right | 97.3 % (251/258) |
| Documents read by more than one tier | 0.0 % (0/270) |
| Model time per document | mean 11.51 s, median 9.05 s, 95th percentile 24.69 s |
| Tokens per document | 1918 in, 625 out |
| Model calls that failed | 0 |

## Field accuracy (invoices and credit notes)

| Field | Correct |
|---|---|
| `document_type` | 98.8 % (255/258) |
| `invoice_number` | 98.8 % (255/258) |
| `issue_date` | 97.7 % (252/258) |
| `due_date` | 98.4 % (254/258) |
| `currency` | 98.8 % (255/258) |
| `supplier_vat_id` | 98.1 % (253/258) |
| `supplier_iban` | 96.1 % (248/258) |
| `po_number` | 99.6 % (257/258) |
| `total_net` | 96.9 % (250/258) |
| `total_tax` | 96.9 % (250/258) |
| `total_gross` | 96.9 % (250/258) |
| `supplier_siret` | 100.0 % (258/258) |
| `referenced_invoice` | 99.6 % (257/258) |
| `allowance_total` | 100.0 % (258/258) |
| `charge_total` | 99.6 % (257/258) |

## By scenario

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| bank_changed | 12 | 0 | n/a | 100.0 % (12/12) | 100.0 % (12/12) | 9.7 s |
| bank_invalid | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 7.41 s |
| clean | 112 | 0 | 96.4 % (108/112) | n/a | 97.3 % (109/112) | 9.76 s |
| credit_note | 10 | 0 | 90.0 % (9/10) | n/a | 90.0 % (9/10) | 6.1 s |
| duplicate | 8 | 0 | n/a | 100.0 % (8/8) | 100.0 % (8/8) | 11.0 s |
| einvoice | 12 | 0 | 100.0 % (12/12) | n/a | 100.0 % (12/12) | 0.0 s |
| einvoice_tampered | 4 | 0 | n/a | 100.0 % (4/4) | 0.0 % (0/4) | 0.0 s |
| injection | 14 | 0 | 53.8 % (7/13) | 100.0 % (1/1) | 50.0 % (7/14) | 8.58 s |
| long | 12 | 0 | 100.0 % (12/12) | n/a | 100.0 % (12/12) | 54.42 s |
| missing_field | 6 | 0 | n/a | 100.0 % (6/6) | 66.7 % (4/6) | 9.29 s |
| not_invoice | 12 | 0 | n/a | 100.0 % (12/12) | n/a | 9.41 s |
| purchase_order | 12 | 0 | n/a | 100.0 % (12/12) | 91.7 % (11/12) | 11.01 s |
| scan | 24 | 0 | 95.8 % (23/24) | n/a | 95.8 % (23/24) | 15.15 s |
| scan_mismatch | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 17.69 s |
| totals_mismatch | 14 | 1 | n/a | 92.9 % (13/14) | 92.9 % (13/14) | 9.87 s |
| unknown_supplier | 10 | 0 | n/a | 100.0 % (10/10) | 100.0 % (10/10) | 7.27 s |

## By group

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| seen suppliers | 118 | 0 | 94.9 % (75/79) | 100.0 % (39/39) | 94.7 % (107/113) | 9.36 s |
| held-out suppliers | 152 | 1 | 92.3 % (96/104) | 97.9 % (47/48) | 90.3 % (131/145) | 13.18 s |
| text layer | 226 | 1 | 92.5 % (136/147) | 98.7 % (78/79) | 93.0 % (199/214) | 11.83 s |
| scans | 28 | 0 | 95.8 % (23/24) | 100.0 % (4/4) | 96.4 % (27/28) | 15.51 s |
| embedded e-invoice | 16 | 0 | 100.0 % (12/12) | 100.0 % (4/4) | 75.0 % (12/16) | 0.0 s |
| language: de | 33 | 0 | 87.0 % (20/23) | 100.0 % (10/10) | 87.9 % (29/33) | 8.0 s |
| language: en | 43 | 0 | 89.3 % (25/28) | 100.0 % (15/15) | 95.0 % (38/40) | 7.6 s |
| language: es | 19 | 0 | 100.0 % (14/14) | 100.0 % (5/5) | 100.0 % (17/17) | 7.77 s |
| language: fr | 163 | 1 | 94.5 % (103/109) | 98.1 % (53/54) | 91.7 % (143/156) | 13.87 s |
| language: it | 12 | 0 | 100.0 % (9/9) | 100.0 % (3/3) | 91.7 % (11/12) | 9.07 s |
| layout: anglo | 24 | 0 | 94.7 % (18/19) | 100.0 % (5/5) | 95.8 % (23/24) | 7.69 s |
| layout: classic | 66 | 0 | 93.2 % (41/44) | 100.0 % (22/22) | 93.5 % (58/62) | 9.04 s |
| layout: columns | 54 | 0 | 100.0 % (33/33) | 100.0 % (21/21) | 96.1 % (49/51) | 9.36 s |
| layout: compact | 39 | 0 | 100.0 % (30/30) | 100.0 % (9/9) | 97.4 % (37/38) | 29.06 s |
| layout: footer_ids | 44 | 1 | 82.1 % (23/28) | 93.8 % (15/16) | 80.0 % (32/40) | 7.1 s |
| layout: german | 33 | 0 | 87.0 % (20/23) | 100.0 % (10/10) | 87.9 % (29/33) | 8.0 s |
| layout: ledger | 10 | 0 | 100.0 % (6/6) | 100.0 % (4/4) | 100.0 % (10/10) | 11.18 s |

## Harmful decisions

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| T-040 | totals_mismatch/rate | footer_ids, fr | review | approved |  |  |

## Other documents not handled as labelled

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| T-037 | clean | footer_ids, fr | approved | review | supplier, bank_details, grounding | supplier_vat_id, supplier_iban |
| T-039 | not_invoice/delivery_note | classic, es | rejected | review | document_type, missing_field, invoice_number |  |
| T-048 | injection/hidden_totals | classic, fr | approved | review | arithmetic | total_net, total_tax, total_gross |
| T-053 | injection/hidden_type | german, de | approved | review | document_type, not_invoice | document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, total_net, total_tax, total_gross |
| T-063 | injection/hidden_type | german, de | approved | review | document_type, not_invoice | document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, po_number, total_net, total_tax, total_gross, charge_total |
| T-065 | clean | footer_ids, fr | approved | review | bank_details | supplier_iban |
| T-079 | injection/hidden_totals | anglo, en | approved | review | arithmetic | total_net, total_tax, total_gross |
| T-082 | clean | footer_ids, fr | approved | review | bank_details | supplier_iban |
| T-107 | scan | classic, fr | approved | review | arithmetic | total_tax, total_gross |
| T-124 | clean | footer_ids, en | approved | review | arithmetic |  |
| T-147 | injection/visible_supplier | german, de | approved | review | arithmetic | total_net |
| T-237 | injection/hidden_type | footer_ids, en | approved | review | document_type, not_invoice | document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, total_net, total_tax, total_gross |
| T-239 | credit_note | classic, fr | approved | review | grounding | issue_date |
