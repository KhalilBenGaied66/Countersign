# Evaluation: `small` on the `test` split

Models: `qwen3.5:4b`. Prompt: `extract_v5`. Checks: on.

Percentages are followed by their 95 % Wilson interval where it matters, and by the counts they come from.

## Summary

| Measure | Value |
|---|---|
| Documents | 270 |
| **Harmful decisions** | **3** (3 wrong approvals, 0 invoices set aside) |
| Approved without a person, among documents that can be | 88.5 % [83.1 to 92.4] (162/183) |
| Approvals that were right | 98.2 % [94.8 to 99.4] (162/165) |
| Stopped, among documents that must not be approved | 97.7 % [92.0 to 99.4] (85/87) |
| Stopped for the expected reason | 95.3 % (81/85) |
| Outcome exactly as labelled | 91.5 % (247/270) |
| Invoices with every critical field right | 90.7 % [86.5 to 93.7] (234/258) |
| Invoices with every line right | 93.4 % (241/258) |
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
| bank_changed | 12 | 0 | n/a | 100.0 % (12/12) | 91.7 % (11/12) | 6.56 s |
| bank_invalid | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 4.96 s |
| clean | 112 | 0 | 98.2 % (110/112) | n/a | 100.0 % (112/112) | 6.6 s |
| credit_note | 10 | 0 | 100.0 % (10/10) | n/a | 100.0 % (10/10) | 4.12 s |
| duplicate | 8 | 0 | n/a | 100.0 % (8/8) | 100.0 % (8/8) | 7.37 s |
| einvoice | 12 | 0 | 100.0 % (12/12) | n/a | 100.0 % (12/12) | 0.0 s |
| einvoice_tampered | 4 | 0 | n/a | 100.0 % (4/4) | 0.0 % (0/4) | 0.0 s |
| injection | 14 | 0 | 53.8 % (7/13) | 100.0 % (1/1) | 50.0 % (7/14) | 5.81 s |
| long | 12 | 0 | 25.0 % (3/12) | n/a | 50.0 % (6/12) | 36.24 s |
| missing_field | 6 | 0 | n/a | 100.0 % (6/6) | 50.0 % (3/6) | 6.29 s |
| not_invoice | 12 | 0 | n/a | 100.0 % (12/12) | n/a | 6.36 s |
| purchase_order | 12 | 0 | n/a | 100.0 % (12/12) | 100.0 % (12/12) | 6.72 s |
| scan | 24 | 1 | 83.3 % (20/24) | n/a | 87.5 % (21/24) | 8.81 s |
| scan_mismatch | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 10.22 s |
| totals_mismatch | 14 | 2 | n/a | 85.7 % (12/14) | 100.0 % (14/14) | 6.59 s |
| unknown_supplier | 10 | 0 | n/a | 100.0 % (10/10) | 100.0 % (10/10) | 4.9 s |

## By group

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| seen suppliers | 118 | 0 | 93.7 % (74/79) | 100.0 % (39/39) | 94.7 % (107/113) | 6.08 s |
| held-out suppliers | 152 | 3 | 84.6 % (88/104) | 95.8 % (46/48) | 87.6 % (127/145) | 8.71 s |
| text layer | 226 | 2 | 88.4 % (130/147) | 97.5 % (77/79) | 92.1 % (197/214) | 7.92 s |
| scans | 28 | 1 | 83.3 % (20/24) | 100.0 % (4/4) | 89.3 % (25/28) | 9.01 s |
| embedded e-invoice | 16 | 0 | 100.0 % (12/12) | 100.0 % (4/4) | 75.0 % (12/16) | 0.0 s |
| language: de | 33 | 1 | 87.0 % (20/23) | 90.0 % (9/10) | 90.9 % (30/33) | 5.18 s |
| language: en | 43 | 0 | 85.7 % (24/28) | 100.0 % (15/15) | 90.0 % (36/40) | 5.08 s |
| language: es | 19 | 1 | 92.9 % (13/14) | 100.0 % (5/5) | 94.1 % (16/17) | 5.03 s |
| language: fr | 163 | 1 | 89.0 % (97/109) | 98.1 % (53/54) | 91.0 % (142/156) | 9.11 s |
| language: it | 12 | 0 | 88.9 % (8/9) | 100.0 % (3/3) | 83.3 % (10/12) | 6.04 s |
| layout: anglo | 24 | 0 | 89.5 % (17/19) | 100.0 % (5/5) | 91.7 % (22/24) | 5.12 s |
| layout: classic | 66 | 0 | 93.2 % (41/44) | 100.0 % (22/22) | 96.8 % (60/62) | 5.88 s |
| layout: columns | 54 | 0 | 97.0 % (32/33) | 100.0 % (21/21) | 92.2 % (47/51) | 6.2 s |
| layout: compact | 39 | 0 | 70.0 % (21/30) | 100.0 % (9/9) | 78.9 % (30/38) | 19.23 s |
| layout: footer_ids | 44 | 2 | 89.3 % (25/28) | 93.8 % (15/16) | 90.0 % (36/40) | 4.77 s |
| layout: german | 33 | 1 | 87.0 % (20/23) | 90.0 % (9/10) | 90.9 % (30/33) | 5.18 s |
| layout: ledger | 10 | 0 | 100.0 % (6/6) | 100.0 % (4/4) | 90.0 % (9/10) | 6.57 s |

## Harmful decisions

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| T-040 | totals_mismatch/rate | footer_ids, fr | review | approved |  |  |
| T-057 | scan | footer_ids, es | approved | approved |  | invoice_number |
| T-244 | totals_mismatch/rate | german, de | review | approved |  |  |

## Other documents not handled as labelled

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| T-022 | scan | anglo, en | approved | review | supplier | supplier_vat_id |
| T-027 | scan | columns, it | approved | review | supplier | supplier_vat_id, supplier_iban |
| T-048 | injection/hidden_totals | classic, fr | approved | review | arithmetic | total_net, total_tax, total_gross |
| T-053 | injection/hidden_type | german, de | approved | review | document_type, not_invoice | document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, total_net, total_tax, total_gross |
| T-060 | scan | classic, fr | approved | review | extraction |  |
| T-063 | injection/hidden_type | german, de | approved | review | document_type, not_invoice | document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, po_number, total_net, total_tax, total_gross, charge_total |
| T-067 | long | compact, fr | approved | review | arithmetic |  |
| T-070 | clean | classic, fr | approved | review | arithmetic |  |
| T-079 | injection/hidden_totals | anglo, en | approved | review | arithmetic | total_net, total_tax, total_gross |
| T-102 | long | compact, fr | approved | review | arithmetic |  |
| T-124 | clean | footer_ids, en | approved | review | arithmetic |  |
| T-132 | long | compact, fr | approved | review | bank_details, arithmetic, grounding | supplier_iban |
| T-143 | long | compact, fr | approved | review | bank_details, arithmetic, grounding | supplier_iban |
| T-178 | long | compact, fr | approved | review | arithmetic |  |
| T-184 | injection/line_instruction | german, de | approved | review | document_type, not_invoice | document_type |
| T-197 | long | compact, fr | approved | review | bank_details, arithmetic, grounding | supplier_iban |
| T-224 | long | compact, fr | approved | review | bank_details, grounding | supplier_iban |
| T-237 | injection/hidden_type | footer_ids, en | approved | review | document_type, not_invoice | document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, total_net, total_tax, total_gross |
| T-242 | not_invoice/proforma | columns, fr | rejected | review | document_type, invoice_number |  |
| T-245 | long | compact, fr | approved | review | bank_details, arithmetic, grounding | supplier_iban |
| T-268 | long | compact, fr | approved | review | bank_details, grounding | supplier_iban |
