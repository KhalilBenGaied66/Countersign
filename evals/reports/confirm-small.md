# Evaluation: `small` on the `confirm` split

Models: `qwen3.5:4b`. Prompt: `extract_v5`. Checks: on.

Percentages are followed by their 95 % Wilson interval where it matters, and by the counts they come from.

## Summary

| Measure | Value |
|---|---|
| Documents | 270 |
| **Harmful decisions** | **0** (0 wrong approvals, 0 invoices set aside) |
| Approved without a person, among documents that can be | 76.4 % [69.7 to 82.0] (139/182) |
| Approvals that were right | 100.0 % [97.3 to 100.0] (139/139) |
| Stopped, among documents that must not be approved | 100.0 % [95.8 to 100.0] (88/88) |
| Stopped for the expected reason, among documents labelled with one | 97.7 % (86/88) |
| Outcome exactly as labelled | 83.3 % (225/270) |
| Invoices with every critical field right | 92.2 % [88.3 to 94.9] (238/258) |
| Invoices with every line right | 92.2 % (238/258) |
| Documents read by more than one tier | 0.0 % (0/270) |
| Model time per document | mean 7.24 s, median 5.88 s, 95th percentile 15.0 s |
| Tokens per document | 1902 in, 586 out |
| Model calls that failed | 0 |

## Field accuracy (invoices and credit notes)

| Field | Correct |
|---|---|
| `document_type` | 98.8 % (255/258) |
| `invoice_number` | 97.7 % (252/258) |
| `issue_date` | 98.4 % (254/258) |
| `due_date` | 98.8 % (255/258) |
| `currency` | 98.8 % (255/258) |
| `supplier_vat_id` | 98.4 % (254/258) |
| `supplier_iban` | 95.7 % (247/258) |
| `po_number` | 98.8 % (255/258) |
| `total_net` | 97.3 % (251/258) |
| `total_tax` | 97.7 % (252/258) |
| `total_gross` | 97.3 % (251/258) |
| `supplier_siret` | 99.6 % (257/258) |
| `referenced_invoice` | 100.0 % (258/258) |
| `allowance_total` | 100.0 % (258/258) |
| `charge_total` | 99.6 % (257/258) |

## By scenario

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| bank_changed | 12 | 0 | n/a | 100.0 % (12/12) | 100.0 % (12/12) | 5.35 s |
| bank_invalid | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 5.47 s |
| clean | 112 | 0 | 96.4 % (108/112) | n/a | 99.1 % (111/112) | 6.42 s |
| credit_note | 10 | 0 | 90.0 % (9/10) | n/a | 100.0 % (10/10) | 4.1 s |
| duplicate | 8 | 0 | n/a | 100.0 % (8/8) | 87.5 % (7/8) | 8.18 s |
| einvoice | 12 | 0 | 100.0 % (12/12) | n/a | 100.0 % (12/12) | 0.0 s |
| einvoice_tampered | 4 | 0 | n/a | 100.0 % (4/4) | 0.0 % (0/4) | 0.0 s |
| injection | 14 | 0 | 58.3 % (7/12) | 100.0 % (2/2) | 64.3 % (9/14) | 6.08 s |
| long | 12 | 0 | 25.0 % (3/12) | n/a | 66.7 % (8/12) | 33.11 s |
| missing_field | 6 | 0 | n/a | 100.0 % (6/6) | 66.7 % (4/6) | 6.2 s |
| not_invoice | 12 | 0 | n/a | 100.0 % (12/12) | n/a | 5.33 s |
| purchase_order | 12 | 0 | n/a | 100.0 % (12/12) | 100.0 % (12/12) | 5.63 s |
| scan | 24 | 0 | 0.0 % (0/24) | n/a | 87.5 % (21/24) | 8.66 s |
| scan_mismatch | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 10.73 s |
| totals_mismatch | 14 | 0 | n/a | 100.0 % (14/14) | 100.0 % (14/14) | 6.74 s |
| unknown_supplier | 10 | 0 | n/a | 100.0 % (10/10) | 100.0 % (10/10) | 4.86 s |

## By group

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| seen suppliers | 102 | 0 | 78.8 % (52/66) | 100.0 % (36/36) | 92.9 % (91/98) | 5.64 s |
| held-out suppliers | 168 | 0 | 75.0 % (87/116) | 100.0 % (52/52) | 91.9 % (147/160) | 8.22 s |
| text layer | 226 | 0 | 87.0 % (127/146) | 100.0 % (80/80) | 93.9 % (201/214) | 7.55 s |
| scans | 28 | 0 | 0.0 % (0/24) | 100.0 % (4/4) | 89.3 % (25/28) | 8.95 s |
| embedded e-invoice | 16 | 0 | 100.0 % (12/12) | 100.0 % (4/4) | 75.0 % (12/16) | 0.0 s |
| language: de | 38 | 0 | 84.0 % (21/25) | 100.0 % (13/13) | 91.9 % (34/37) | 4.86 s |
| language: en | 42 | 0 | 74.1 % (20/27) | 100.0 % (15/15) | 97.6 % (40/41) | 5.23 s |
| language: es | 33 | 0 | 82.6 % (19/23) | 100.0 % (10/10) | 96.8 % (30/31) | 5.29 s |
| language: fr | 149 | 0 | 72.3 % (73/101) | 100.0 % (48/48) | 89.4 % (126/141) | 8.96 s |
| language: it | 8 | 0 | 100.0 % (6/6) | 100.0 % (2/2) | 100.0 % (8/8) | 5.17 s |
| layout: anglo | 16 | 0 | 80.0 % (8/10) | 100.0 % (6/6) | 93.3 % (14/15) | 4.99 s |
| layout: classic | 53 | 0 | 86.1 % (31/36) | 100.0 % (17/17) | 92.3 % (48/52) | 5.85 s |
| layout: columns | 51 | 0 | 79.4 % (27/34) | 100.0 % (17/17) | 98.0 % (48/49) | 5.35 s |
| layout: compact | 35 | 0 | 59.3 % (16/27) | 100.0 % (8/8) | 79.4 % (27/34) | 19.07 s |
| layout: footer_ids | 53 | 0 | 66.7 % (22/33) | 100.0 % (20/20) | 93.6 % (44/47) | 5.61 s |
| layout: german | 38 | 0 | 84.0 % (21/25) | 100.0 % (13/13) | 91.9 % (34/37) | 4.86 s |
| layout: ledger | 24 | 0 | 82.4 % (14/17) | 100.0 % (7/7) | 95.8 % (23/24) | 5.99 s |

## Harmful decisions

None.

## Other documents not handled as labelled

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| C-003 | scan | german, de | approved | review | consensus |  |
| C-007 | scan | columns, en | approved | review | consensus |  |
| C-030 | scan | compact, fr | approved | review | consensus |  |
| C-032 | long | compact, fr | approved | review | bank_details, grounding | supplier_iban |
| C-043 | scan | columns, fr | approved | review | consensus |  |
| C-045 | injection/line_instruction | footer_ids, fr | approved | review | arithmetic |  |
| C-051 | scan | columns, fr | approved | review | consensus |  |
| C-055 | long | compact, fr | approved | review | bank_details, grounding | supplier_iban |
| C-057 | long | compact, fr | approved | review | arithmetic |  |
| C-060 | scan | footer_ids, fr | approved | review | consensus |  |
| C-064 | long | compact, fr | approved | review | bank_details, arithmetic, grounding | supplier_iban |
| C-076 | scan | footer_ids, es | approved | review | consensus |  |
| C-082 | scan | classic, es | approved | review | consensus |  |
| C-083 | scan | german, de | approved | review | consensus |  |
| C-092 | scan | anglo, en | approved | review | supplier, consensus | supplier record, supplier_vat_id |
| C-098 | duplicate | compact, fr | duplicate | review | bank_details, duplicate, grounding | supplier_iban |
| C-102 | clean | footer_ids, en | approved | review | arithmetic |  |
| C-105 | scan | columns, fr | approved | review | consensus |  |
| C-111 | scan | footer_ids, fr | approved | review | invoice_number, consensus | invoice_number |
| C-112 | scan | classic, fr | approved | review | consensus |  |
| C-115 | credit_note | columns, fr | approved | review | arithmetic |  |
| C-116 | scan | ledger, fr | approved | review | consensus |  |
| C-131 | clean | footer_ids, es | approved | review | arithmetic |  |
| C-136 | scan | columns, en | approved | review | consensus |  |
| C-139 | scan | classic, fr | approved | review | consensus |  |
| C-146 | clean | footer_ids, es | approved | review | extraction, arithmetic, grounding | total_net, total_gross |
| C-149 | scan | classic, fr | approved | review | consensus |  |
| C-154 | duplicate | compact, fr | duplicate | review | duplicate, arithmetic |  |
| C-162 | long | compact, fr | approved | review | arithmetic |  |
| C-171 | injection/visible_approval | footer_ids, en | approved | review | arithmetic |  |
| C-186 | scan | classic, fr | approved | review | consensus |  |
| C-196 | injection/hidden_type | german, de | approved | review | document_type, not_invoice | supplier record, document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, po_number, total_net, total_tax, total_gross |
| C-203 | scan | ledger, fr | approved | review | consensus |  |
| C-209 | scan | columns, fr | approved | review | consensus |  |
| C-214 | injection/hidden_type | german, de | approved | review | document_type, not_invoice | supplier record, document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, po_number, total_net, total_tax, total_gross |
| C-219 | long | compact, fr | approved | review | arithmetic |  |
| C-222 | scan | footer_ids, fr | approved | review | consensus |  |
| C-223 | long | compact, fr | approved | review | arithmetic |  |
| C-229 | scan | anglo, en | approved | review | consensus |  |
| C-237 | clean | footer_ids, en | approved | review | arithmetic |  |
| C-244 | scan | ledger, fr | approved | review | consensus |  |
| C-249 | injection/hidden_type | compact, fr | approved | review | document_type, not_invoice | supplier record, document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, total_net, total_tax, total_gross, supplier_siret, charge_total |
| C-250 | long | compact, fr | approved | review | arithmetic |  |
| C-252 | long | compact, fr | approved | review | bank_details, arithmetic, grounding | supplier_iban |
| C-260 | scan | footer_ids, fr | approved | review | invoice_number, consensus | invoice_number |
