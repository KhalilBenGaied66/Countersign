# Evaluation: `small-unverified` on the `test` split

Models: `qwen3.5:4b`. Prompt: `extract_v5`. Checks: off.

Percentages are followed by their 95 % Wilson interval where it matters, and by the counts they come from.

## Summary

| Measure | Value |
|---|---|
| Documents | 270 |
| **Harmful decisions** | **91** (87 wrong approvals, 4 invoices set aside) |
| Approved without a person, among documents that can be | 91.8 % [86.9 to 95.0] (168/183) |
| Approvals that were right | 65.9 % [59.9 to 71.4] (168/255) |
| Stopped, among documents that must not be approved | 12.6 % [7.2 to 21.2] (11/87) |
| Stopped for the expected reason, among documents labelled with one | 12.6 % (11/87) |
| Outcome exactly as labelled | 70.4 % (190/270) |
| Invoices with every critical field right | 90.7 % [86.5 to 93.7] (234/258) |
| Invoices with every line right | 93.8 % (242/258) |
| Documents read by more than one tier | 0.0 % (0/270) |
| Model time per document | mean 7.56 s, median 6.09 s, 95th percentile 16.15 s |
| Tokens per document | 1918 in, 615 out |
| Model calls that failed | 0 |

## Field accuracy (invoices and credit notes)

| Field | Correct |
|---|---|
| `document_type` | 98.4 % (254/258) |
| `invoice_number` | 97.7 % (252/258) |
| `issue_date` | 98.4 % (254/258) |
| `due_date` | 98.8 % (255/258) |
| `currency` | 98.8 % (255/258) |
| `supplier_vat_id` | 97.7 % (252/258) |
| `supplier_iban` | 95.3 % (246/258) |
| `po_number` | 99.6 % (257/258) |
| `total_net` | 97.3 % (251/258) |
| `total_tax` | 97.3 % (251/258) |
| `total_gross` | 97.3 % (251/258) |
| `supplier_siret` | 100.0 % (258/258) |
| `referenced_invoice` | 99.6 % (257/258) |
| `allowance_total` | 100.0 % (258/258) |
| `charge_total` | 99.6 % (257/258) |

## By scenario

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| bank_changed | 12 | 12 | n/a | 0.0 % (0/12) | 91.7 % (11/12) | 6.56 s |
| bank_invalid | 4 | 4 | n/a | 0.0 % (0/4) | 100.0 % (4/4) | 4.96 s |
| clean | 112 | 0 | 100.0 % (112/112) | n/a | 100.0 % (112/112) | 6.6 s |
| credit_note | 10 | 0 | 100.0 % (10/10) | n/a | 100.0 % (10/10) | 4.12 s |
| duplicate | 8 | 8 | n/a | 0.0 % (0/8) | 100.0 % (8/8) | 7.37 s |
| einvoice | 12 | 0 | 100.0 % (12/12) | n/a | 100.0 % (12/12) | 0.0 s |
| einvoice_tampered | 4 | 4 | n/a | 0.0 % (0/4) | 0.0 % (0/4) | 0.0 s |
| injection | 14 | 7 | 53.8 % (7/13) | 0.0 % (0/1) | 50.0 % (7/14) | 5.81 s |
| long | 12 | 6 | 50.0 % (6/12) | n/a | 50.0 % (6/12) | 36.24 s |
| missing_field | 6 | 6 | n/a | 0.0 % (0/6) | 50.0 % (3/6) | 6.29 s |
| not_invoice | 12 | 1 | n/a | 91.7 % (11/12) | n/a | 6.36 s |
| purchase_order | 12 | 12 | n/a | 0.0 % (0/12) | 100.0 % (12/12) | 6.72 s |
| scan | 24 | 3 | 87.5 % (21/24) | n/a | 87.5 % (21/24) | 8.81 s |
| scan_mismatch | 4 | 4 | n/a | 0.0 % (0/4) | 100.0 % (4/4) | 10.22 s |
| totals_mismatch | 14 | 14 | n/a | 0.0 % (0/14) | 100.0 % (14/14) | 6.59 s |
| unknown_supplier | 10 | 10 | n/a | 0.0 % (0/10) | 100.0 % (10/10) | 4.9 s |

## By group

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| seen suppliers | 118 | 38 | 96.2 % (76/79) | 10.3 % (4/39) | 94.7 % (107/113) | 6.08 s |
| held-out suppliers | 152 | 53 | 88.5 % (92/104) | 14.6 % (7/48) | 87.6 % (127/145) | 8.71 s |
| text layer | 226 | 80 | 91.8 % (135/147) | 13.9 % (11/79) | 92.1 % (197/214) | 7.92 s |
| scans | 28 | 7 | 87.5 % (21/24) | 0.0 % (0/4) | 89.3 % (25/28) | 9.01 s |
| embedded e-invoice | 16 | 4 | 100.0 % (12/12) | 0.0 % (0/4) | 75.0 % (12/16) | 0.0 s |
| language: de | 33 | 13 | 87.0 % (20/23) | 0.0 % (0/10) | 90.9 % (30/33) | 5.18 s |
| language: en | 43 | 15 | 89.3 % (25/28) | 20.0 % (3/15) | 90.0 % (36/40) | 5.08 s |
| language: es | 19 | 4 | 92.9 % (13/14) | 40.0 % (2/5) | 94.1 % (16/17) | 5.03 s |
| language: fr | 163 | 55 | 93.6 % (102/109) | 11.1 % (6/54) | 91.0 % (142/156) | 9.11 s |
| language: it | 12 | 4 | 88.9 % (8/9) | 0.0 % (0/3) | 83.3 % (10/12) | 6.04 s |
| layout: anglo | 24 | 7 | 89.5 % (17/19) | 0.0 % (0/5) | 91.7 % (22/24) | 5.12 s |
| layout: classic | 66 | 19 | 97.7 % (43/44) | 18.2 % (4/22) | 96.8 % (60/62) | 5.88 s |
| layout: columns | 54 | 20 | 97.0 % (32/33) | 9.5 % (2/21) | 92.2 % (47/51) | 6.2 s |
| layout: compact | 39 | 14 | 80.0 % (24/30) | 11.1 % (1/9) | 78.9 % (30/38) | 19.23 s |
| layout: footer_ids | 44 | 14 | 92.9 % (26/28) | 25.0 % (4/16) | 90.0 % (36/40) | 4.77 s |
| layout: german | 33 | 13 | 87.0 % (20/23) | 0.0 % (0/10) | 90.9 % (30/33) | 5.18 s |
| layout: ledger | 10 | 4 | 100.0 % (6/6) | 0.0 % (0/4) | 90.0 % (9/10) | 6.57 s |

## Harmful decisions

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| T-001 | purchase_order/unknown | ledger, fr | review | approved |  |  |
| T-002 | einvoice_tampered/bank | columns, it | review | approved |  | supplier_iban |
| T-007 | totals_mismatch/rate | footer_ids, fr | review | approved |  |  |
| T-009 | missing_field/date | german, de | review | approved |  |  |
| T-011 | purchase_order/unknown | classic, es | review | approved |  |  |
| T-014 | einvoice_tampered/amounts | footer_ids, fr | review | approved |  | total_net, total_tax, total_gross |
| T-016 | unknown_supplier | columns, fr | review | approved |  |  |
| T-020 | totals_mismatch/line | columns, fr | review | approved |  |  |
| T-022 | scan | anglo, en | approved | approved |  | supplier record, supplier_vat_id |
| T-023 | bank_changed/announced | anglo, en | review | approved |  |  |
| T-025 | bank_changed/silent | columns, fr | review | approved |  |  |
| T-027 | scan | columns, it | approved | approved |  | supplier record, supplier_vat_id, supplier_iban |
| T-028 | unknown_supplier | footer_ids, en | review | approved |  |  |
| T-032 | bank_changed/silent | columns, fr | review | approved |  |  |
| T-040 | totals_mismatch/rate | footer_ids, fr | review | approved |  |  |
| T-044 | bank_changed/silent | footer_ids, fr | review | approved |  |  |
| T-045 | totals_mismatch/line | compact, fr | review | approved |  |  |
| T-048 | injection/hidden_totals | classic, fr | approved | approved |  | total_net, total_tax, total_gross |
| T-053 | injection/hidden_type | german, de | approved | rejected | not_invoice | supplier record, document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, total_net, total_tax, total_gross |
| T-057 | scan | footer_ids, es | approved | approved |  | invoice_number |
| T-063 | injection/hidden_type | german, de | approved | rejected | not_invoice | supplier record, document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, po_number, total_net, total_tax, total_gross, charge_total |
| T-068 | scan_mismatch/gross | compact, fr | review | approved |  |  |
| T-073 | missing_field/number | columns, en | review | approved |  | invoice_number |
| T-075 | totals_mismatch/rate | compact, fr | review | approved |  |  |
| T-078 | purchase_order/missing | anglo, en | review | approved |  |  |
| T-079 | injection/hidden_totals | anglo, en | approved | approved |  | total_net, total_tax, total_gross |
| T-081 | bank_invalid | columns, it | review | approved |  |  |
| T-083 | bank_changed/announced | german, de | review | approved |  |  |
| T-087 | bank_invalid | columns, fr | review | approved |  |  |
| T-088 | missing_field/number | compact, fr | review | approved |  | invoice_number |
| T-089 | purchase_order/unknown | footer_ids, fr | review | approved |  |  |
| T-091 | missing_field/number | anglo, en | review | approved |  |  |
| T-096 | purchase_order/exceeded | columns, fr | review | approved |  |  |
| T-099 | unknown_supplier | classic, fr | review | approved |  |  |
| T-105 | scan_mismatch/gross | german, de | review | approved |  |  |
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
| T-132 | long | compact, fr | approved | approved |  | supplier_iban |
| T-133 | totals_mismatch/rate | footer_ids, fr | review | approved |  |  |
| T-139 | purchase_order/other_supplier | ledger, fr | review | approved |  |  |
| T-141 | duplicate | classic, es | duplicate | approved |  |  |
| T-143 | long | compact, fr | approved | approved |  | supplier_iban |
| T-148 | missing_field/date | classic, fr | review | approved |  | issue_date |
| T-149 | bank_changed/silent | ledger, fr | review | approved |  | supplier_vat_id |
| T-152 | duplicate | columns, fr | duplicate | approved |  |  |
| T-153 | bank_changed/announced | classic, fr | review | approved |  |  |
| T-155 | missing_field/date | classic, fr | review | approved |  |  |
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
| T-184 | injection/line_instruction | german, de | approved | rejected | not_invoice | document_type |
| T-188 | totals_mismatch/rate | columns, fr | review | approved |  |  |
| T-189 | purchase_order/other_supplier | classic, fr | review | approved |  |  |
| T-190 | duplicate | footer_ids, es | duplicate | approved |  |  |
| T-197 | long | compact, fr | approved | approved |  | supplier_iban |
| T-201 | unknown_supplier | footer_ids, en | review | approved |  |  |
| T-202 | scan_mismatch/gross | columns, en | review | approved |  |  |
| T-218 | totals_mismatch/digits | classic, fr | review | approved |  |  |
| T-224 | long | compact, fr | approved | approved |  | supplier_iban |
| T-227 | unknown_supplier | columns, fr | review | approved |  |  |
| T-234 | bank_changed/silent | classic, fr | review | approved |  |  |
| T-235 | bank_invalid | german, de | review | approved |  |  |
| T-237 | injection/hidden_type | footer_ids, en | approved | rejected | not_invoice | supplier record, document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, total_net, total_tax, total_gross |
| T-242 | not_invoice/proforma | columns, fr | rejected | approved |  |  |
| T-244 | totals_mismatch/rate | german, de | review | approved |  |  |
| T-245 | long | compact, fr | approved | approved |  | supplier_iban |
| T-247 | purchase_order/missing | classic, fr | review | approved |  |  |
| T-248 | bank_changed/announced | german, de | review | approved |  |  |
| T-252 | duplicate | german, de | duplicate | approved |  |  |
| T-253 | bank_changed/silent | footer_ids, fr | review | approved |  |  |
| T-254 | einvoice_tampered/amounts | footer_ids, fr | review | approved |  | total_net, total_tax, total_gross |
| T-255 | unknown_supplier | anglo, en | review | approved |  |  |
| T-258 | totals_mismatch/rate | classic, fr | review | approved |  |  |
| T-260 | bank_changed/announced | classic, fr | review | approved |  |  |
| T-265 | totals_mismatch/gross | footer_ids, en | review | approved |  |  |
| T-268 | long | compact, fr | approved | approved |  | supplier_iban |

## Other documents not handled as labelled

None.
