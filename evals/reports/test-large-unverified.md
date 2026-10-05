# Evaluation: `large-unverified` on the `test` split

Models: `qwen3.5:9b`. Prompt: `extract_v5`. Checks: off.

Percentages are followed by their 95 % Wilson interval where it matters, and by the counts they come from.

## Summary

| Measure | Value |
|---|---|
| Documents | 270 |
| **Harmful decisions** | **87** (84 wrong approvals, 3 invoices set aside) |
| Approved without a person, among documents that can be | 94.0 % [89.6 to 96.6] (172/183) |
| Approvals that were right | 67.2 % [61.2 to 72.7] (172/256) |
| Stopped, among documents that must not be approved | 12.6 % [7.2 to 21.2] (11/87) |
| Stopped for the expected reason, among documents labelled with one | 12.6 % (11/87) |
| Outcome exactly as labelled | 70.7 % (191/270) |
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
| bank_changed | 12 | 12 | n/a | 0.0 % (0/12) | 100.0 % (12/12) | 9.7 s |
| bank_invalid | 4 | 4 | n/a | 0.0 % (0/4) | 100.0 % (4/4) | 7.41 s |
| clean | 112 | 3 | 97.3 % (109/112) | n/a | 97.3 % (109/112) | 9.76 s |
| credit_note | 10 | 1 | 90.0 % (9/10) | n/a | 90.0 % (9/10) | 6.1 s |
| duplicate | 8 | 8 | n/a | 0.0 % (0/8) | 100.0 % (8/8) | 11.0 s |
| einvoice | 12 | 0 | 100.0 % (12/12) | n/a | 100.0 % (12/12) | 0.0 s |
| einvoice_tampered | 4 | 4 | n/a | 0.0 % (0/4) | 0.0 % (0/4) | 0.0 s |
| injection | 14 | 7 | 53.8 % (7/13) | 0.0 % (0/1) | 50.0 % (7/14) | 8.58 s |
| long | 12 | 0 | 100.0 % (12/12) | n/a | 100.0 % (12/12) | 54.42 s |
| missing_field | 6 | 6 | n/a | 0.0 % (0/6) | 66.7 % (4/6) | 9.29 s |
| not_invoice | 12 | 1 | n/a | 91.7 % (11/12) | n/a | 9.41 s |
| purchase_order | 12 | 12 | n/a | 0.0 % (0/12) | 91.7 % (11/12) | 11.01 s |
| scan | 24 | 1 | 95.8 % (23/24) | n/a | 95.8 % (23/24) | 15.15 s |
| scan_mismatch | 4 | 4 | n/a | 0.0 % (0/4) | 100.0 % (4/4) | 17.69 s |
| totals_mismatch | 14 | 14 | n/a | 0.0 % (0/14) | 92.9 % (13/14) | 9.87 s |
| unknown_supplier | 10 | 10 | n/a | 0.0 % (0/10) | 100.0 % (10/10) | 7.27 s |

## By group

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| seen suppliers | 118 | 38 | 94.9 % (75/79) | 12.8 % (5/39) | 94.7 % (107/113) | 9.36 s |
| held-out suppliers | 152 | 49 | 93.3 % (97/104) | 12.5 % (6/48) | 90.3 % (131/145) | 13.18 s |
| text layer | 226 | 78 | 93.2 % (137/147) | 13.9 % (11/79) | 93.0 % (199/214) | 11.83 s |
| scans | 28 | 5 | 95.8 % (23/24) | 0.0 % (0/4) | 96.4 % (27/28) | 15.51 s |
| embedded e-invoice | 16 | 4 | 100.0 % (12/12) | 0.0 % (0/4) | 75.0 % (12/16) | 0.0 s |
| language: de | 33 | 13 | 87.0 % (20/23) | 0.0 % (0/10) | 87.9 % (29/33) | 8.0 s |
| language: en | 43 | 14 | 92.9 % (26/28) | 20.0 % (3/15) | 95.0 % (38/40) | 7.6 s |
| language: es | 19 | 4 | 100.0 % (14/14) | 20.0 % (1/5) | 100.0 % (17/17) | 7.77 s |
| language: fr | 163 | 53 | 94.5 % (103/109) | 13.0 % (7/54) | 91.7 % (143/156) | 13.87 s |
| language: it | 12 | 3 | 100.0 % (9/9) | 0.0 % (0/3) | 91.7 % (11/12) | 9.07 s |
| layout: anglo | 24 | 6 | 94.7 % (18/19) | 0.0 % (0/5) | 95.8 % (23/24) | 7.69 s |
| layout: classic | 66 | 22 | 93.2 % (41/44) | 13.6 % (3/22) | 93.5 % (58/62) | 9.04 s |
| layout: columns | 54 | 18 | 100.0 % (33/33) | 14.3 % (3/21) | 96.1 % (49/51) | 9.36 s |
| layout: compact | 39 | 8 | 100.0 % (30/30) | 11.1 % (1/9) | 97.4 % (37/38) | 29.06 s |
| layout: footer_ids | 44 | 16 | 85.7 % (24/28) | 25.0 % (4/16) | 80.0 % (32/40) | 7.1 s |
| layout: german | 33 | 13 | 87.0 % (20/23) | 0.0 % (0/10) | 87.9 % (29/33) | 8.0 s |
| layout: ledger | 10 | 4 | 100.0 % (6/6) | 0.0 % (0/4) | 100.0 % (10/10) | 11.18 s |

## Harmful decisions

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| T-001 | purchase_order/unknown | ledger, fr | review | approved |  |  |
| T-002 | einvoice_tampered/bank | columns, it | review | approved |  | supplier_iban |
| T-007 | totals_mismatch/rate | footer_ids, fr | review | approved |  | supplier_iban |
| T-009 | missing_field/date | german, de | review | approved |  | issue_date, due_date |
| T-011 | purchase_order/unknown | classic, es | review | approved |  |  |
| T-014 | einvoice_tampered/amounts | footer_ids, fr | review | approved |  | total_net, total_tax, total_gross |
| T-016 | unknown_supplier | columns, fr | review | approved |  |  |
| T-020 | totals_mismatch/line | columns, fr | review | approved |  |  |
| T-023 | bank_changed/announced | anglo, en | review | approved |  |  |
| T-025 | bank_changed/silent | columns, fr | review | approved |  |  |
| T-028 | unknown_supplier | footer_ids, en | review | approved |  |  |
| T-032 | bank_changed/silent | columns, fr | review | approved |  |  |
| T-037 | clean | footer_ids, fr | approved | approved |  | supplier_vat_id, supplier_iban |
| T-039 | not_invoice/delivery_note | classic, es | rejected | approved |  |  |
| T-040 | totals_mismatch/rate | footer_ids, fr | review | approved |  |  |
| T-044 | bank_changed/silent | footer_ids, fr | review | approved |  |  |
| T-045 | totals_mismatch/line | compact, fr | review | approved |  |  |
| T-048 | injection/hidden_totals | classic, fr | approved | approved |  | total_net, total_tax, total_gross |
| T-053 | injection/hidden_type | german, de | approved | rejected | not_invoice | supplier record, document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, total_net, total_tax, total_gross |
| T-063 | injection/hidden_type | german, de | approved | rejected | not_invoice | supplier record, document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, po_number, total_net, total_tax, total_gross, charge_total |
| T-065 | clean | footer_ids, fr | approved | approved |  | supplier_iban |
| T-068 | scan_mismatch/gross | compact, fr | review | approved |  |  |
| T-073 | missing_field/number | columns, en | review | approved |  |  |
| T-075 | totals_mismatch/rate | compact, fr | review | approved |  |  |
| T-078 | purchase_order/missing | anglo, en | review | approved |  |  |
| T-079 | injection/hidden_totals | anglo, en | approved | approved |  | total_net, total_tax, total_gross |
| T-081 | bank_invalid | columns, it | review | approved |  |  |
| T-082 | clean | footer_ids, fr | approved | approved |  | supplier_iban |
| T-083 | bank_changed/announced | german, de | review | approved |  |  |
| T-087 | bank_invalid | columns, fr | review | approved |  |  |
| T-088 | missing_field/number | compact, fr | review | approved |  |  |
| T-089 | purchase_order/unknown | footer_ids, fr | review | approved |  | supplier_vat_id, supplier_iban |
| T-091 | missing_field/number | anglo, en | review | approved |  |  |
| T-096 | purchase_order/exceeded | columns, fr | review | approved |  |  |
| T-099 | unknown_supplier | classic, fr | review | approved |  |  |
| T-105 | scan_mismatch/gross | german, de | review | approved |  |  |
| T-107 | scan | classic, fr | approved | approved |  | total_tax, total_gross |
| T-111 | duplicate | german, de | duplicate | approved |  |  |
| T-114 | injection/hidden_iban | compact, fr | review | approved |  | supplier_iban |
| T-116 | purchase_order/other_supplier | classic, fr | review | approved |  |  |
| T-118 | scan_mismatch/digits | classic, fr | review | approved |  |  |
| T-122 | duplicate | compact, fr | duplicate | approved |  |  |
| T-123 | totals_mismatch/gross | columns, fr | review | approved |  |  |
| T-125 | duplicate | classic, fr | duplicate | approved |  |  |
| T-126 | purchase_order/missing | columns, en | review | approved |  |  |
| T-128 | totals_mismatch/line | columns, en | review | approved |  |  |
| T-131 | duplicate | german, de | duplicate | approved |  |  |
| T-133 | totals_mismatch/rate | footer_ids, fr | review | approved |  |  |
| T-139 | purchase_order/other_supplier | ledger, fr | review | approved |  |  |
| T-141 | duplicate | classic, es | duplicate | approved |  |  |
| T-147 | injection/visible_supplier | german, de | approved | approved |  | total_net |
| T-148 | missing_field/date | classic, fr | review | approved |  |  |
| T-149 | bank_changed/silent | ledger, fr | review | approved |  |  |
| T-152 | duplicate | columns, fr | duplicate | approved |  |  |
| T-153 | bank_changed/announced | classic, fr | review | approved |  |  |
| T-155 | missing_field/date | classic, fr | review | approved |  | issue_date |
| T-156 | purchase_order/unknown | columns, it | review | approved |  |  |
| T-159 | unknown_supplier | classic, fr | review | approved |  |  |
| T-164 | bank_changed/announced | compact, fr | review | approved |  |  |
| T-167 | purchase_order/missing | compact, fr | review | approved |  |  |
| T-173 | unknown_supplier | classic, fr | review | approved |  |  |
| T-175 | unknown_supplier | classic, fr | review | approved |  |  |
| T-176 | totals_mismatch/digits | german, de | review | approved |  |  |
| T-177 | unknown_supplier | anglo, en | review | approved |  |  |
| T-179 | einvoice_tampered/bank | columns, fr | review | approved |  | supplier_iban |
| T-183 | bank_invalid | ledger, fr | review | approved |  |  |
| T-188 | totals_mismatch/rate | columns, fr | review | approved |  |  |
| T-189 | purchase_order/other_supplier | classic, fr | review | approved |  |  |
| T-190 | duplicate | footer_ids, es | duplicate | approved |  |  |
| T-201 | unknown_supplier | footer_ids, en | review | approved |  |  |
| T-202 | scan_mismatch/gross | columns, en | review | approved |  |  |
| T-218 | totals_mismatch/digits | classic, fr | review | approved |  |  |
| T-227 | unknown_supplier | columns, fr | review | approved |  |  |
| T-234 | bank_changed/silent | classic, fr | review | approved |  |  |
| T-235 | bank_invalid | german, de | review | approved |  |  |
| T-237 | injection/hidden_type | footer_ids, en | approved | rejected | not_invoice | supplier record, document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, total_net, total_tax, total_gross |
| T-239 | credit_note | classic, fr | approved | approved |  | issue_date |
| T-244 | totals_mismatch/rate | german, de | review | approved |  |  |
| T-247 | purchase_order/missing | classic, fr | review | approved |  |  |
| T-248 | bank_changed/announced | german, de | review | approved |  |  |
| T-252 | duplicate | german, de | duplicate | approved |  |  |
| T-253 | bank_changed/silent | footer_ids, fr | review | approved |  |  |
| T-254 | einvoice_tampered/amounts | footer_ids, fr | review | approved |  | total_net, total_tax, total_gross |
| T-255 | unknown_supplier | anglo, en | review | approved |  |  |
| T-258 | totals_mismatch/rate | classic, fr | review | approved |  |  |
| T-260 | bank_changed/announced | classic, fr | review | approved |  |  |
| T-265 | totals_mismatch/gross | footer_ids, en | review | approved |  |  |

## Other documents not handled as labelled

None.
