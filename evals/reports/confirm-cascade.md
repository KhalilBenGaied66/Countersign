# Evaluation: `cascade` on the `confirm` split

Models: `qwen3.5:4b`, `qwen3.5:9b`. Prompt: `extract_v5`. Checks: on.

Percentages are followed by their 95 % Wilson interval where it matters, and by the counts they come from.

## Summary

| Measure | Value |
|---|---|
| Documents | 270 |
| **Harmful decisions** | **0** (0 wrong approvals, 0 invoices set aside) |
| Approved without a person, among documents that can be | 95.1 % [90.9 to 97.4] (173/182) |
| Approvals that were right | 100.0 % [97.8 to 100.0] (173/173) |
| Stopped, among documents that must not be approved | 100.0 % [95.8 to 100.0] (88/88) |
| Stopped for the expected reason, among documents labelled with one | 97.7 % (86/88) |
| Outcome exactly as labelled | 96.7 % (261/270) |
| Invoices with every critical field right | 95.0 % [91.6 to 97.0] (245/258) |
| Invoices with every line right | 96.1 % (248/258) |
| Documents read by more than one tier | 25.6 % (69/270) |
| Model time per document | mean 11.66 s, median 6.19 s, 95th percentile 32.71 s |
| Tokens per document | 2713 in, 803 out |
| Model calls that failed | 0 |

## Field accuracy (invoices and credit notes)

| Field | Correct |
|---|---|
| `document_type` | 98.8 % (255/258) |
| `invoice_number` | 98.8 % (255/258) |
| `issue_date` | 98.1 % (253/258) |
| `due_date` | 98.8 % (255/258) |
| `currency` | 98.8 % (255/258) |
| `supplier_vat_id` | 98.8 % (255/258) |
| `supplier_iban` | 97.7 % (252/258) |
| `po_number` | 98.8 % (255/258) |
| `total_net` | 97.3 % (251/258) |
| `total_tax` | 97.7 % (252/258) |
| `total_gross` | 97.7 % (252/258) |
| `supplier_siret` | 99.6 % (257/258) |
| `referenced_invoice` | 100.0 % (258/258) |
| `allowance_total` | 100.0 % (258/258) |
| `charge_total` | 99.6 % (257/258) |

## By scenario

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| bank_changed | 12 | 0 | n/a | 100.0 % (12/12) | 100.0 % (12/12) | 5.35 s |
| bank_invalid | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 5.47 s |
| clean | 112 | 0 | 98.2 % (110/112) | n/a | 100.0 % (112/112) | 6.71 s |
| credit_note | 10 | 0 | 100.0 % (10/10) | n/a | 100.0 % (10/10) | 4.73 s |
| duplicate | 8 | 0 | n/a | 100.0 % (8/8) | 100.0 % (8/8) | 13.01 s |
| einvoice | 12 | 0 | 100.0 % (12/12) | n/a | 100.0 % (12/12) | 0.0 s |
| einvoice_tampered | 4 | 0 | n/a | 100.0 % (4/4) | 0.0 % (0/4) | 0.0 s |
| injection | 14 | 0 | 66.7 % (8/12) | 100.0 % (2/2) | 64.3 % (9/14) | 8.02 s |
| long | 12 | 0 | 100.0 % (12/12) | n/a | 100.0 % (12/12) | 71.18 s |
| missing_field | 6 | 0 | n/a | 100.0 % (6/6) | 50.0 % (3/6) | 15.56 s |
| not_invoice | 12 | 0 | n/a | 100.0 % (12/12) | n/a | 5.33 s |
| purchase_order | 12 | 0 | n/a | 100.0 % (12/12) | 100.0 % (12/12) | 5.63 s |
| scan | 24 | 0 | 87.5 % (21/24) | n/a | 100.0 % (24/24) | 23.72 s |
| scan_mismatch | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 28.71 s |
| totals_mismatch | 14 | 0 | n/a | 100.0 % (14/14) | 92.9 % (13/14) | 16.84 s |
| unknown_supplier | 10 | 0 | n/a | 100.0 % (10/10) | 100.0 % (10/10) | 4.86 s |

## By group

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| seen suppliers | 102 | 0 | 98.5 % (65/66) | 100.0 % (36/36) | 92.9 % (91/98) | 8.36 s |
| held-out suppliers | 168 | 0 | 93.1 % (108/116) | 100.0 % (52/52) | 96.2 % (154/160) | 13.66 s |
| text layer | 226 | 0 | 95.9 % (140/146) | 100.0 % (80/80) | 95.8 % (205/214) | 10.91 s |
| scans | 28 | 0 | 87.5 % (21/24) | 100.0 % (4/4) | 100.0 % (28/28) | 24.43 s |
| embedded e-invoice | 16 | 0 | 100.0 % (12/12) | 100.0 % (4/4) | 75.0 % (12/16) | 0.0 s |
| language: de | 38 | 0 | 92.0 % (23/25) | 100.0 % (13/13) | 89.2 % (33/37) | 6.95 s |
| language: en | 42 | 0 | 85.2 % (23/27) | 100.0 % (15/15) | 100.0 % (41/41) | 7.35 s |
| language: es | 33 | 0 | 100.0 % (23/23) | 100.0 % (10/10) | 100.0 % (31/31) | 7.11 s |
| language: fr | 149 | 0 | 97.0 % (98/101) | 100.0 % (48/48) | 93.6 % (132/141) | 15.39 s |
| language: it | 8 | 0 | 100.0 % (6/6) | 100.0 % (2/2) | 100.0 % (8/8) | 6.05 s |
| layout: anglo | 16 | 0 | 90.0 % (9/10) | 100.0 % (6/6) | 100.0 % (15/15) | 6.55 s |
| layout: classic | 53 | 0 | 100.0 % (36/36) | 100.0 % (17/17) | 92.3 % (48/52) | 7.68 s |
| layout: columns | 51 | 0 | 100.0 % (34/34) | 100.0 % (17/17) | 95.9 % (47/49) | 7.79 s |
| layout: compact | 35 | 0 | 96.3 % (26/27) | 100.0 % (8/8) | 94.1 % (32/34) | 35.89 s |
| layout: footer_ids | 53 | 0 | 84.8 % (28/33) | 100.0 % (20/20) | 100.0 % (47/47) | 9.35 s |
| layout: german | 38 | 0 | 92.0 % (23/25) | 100.0 % (13/13) | 89.2 % (33/37) | 6.95 s |
| layout: ledger | 24 | 0 | 100.0 % (17/17) | 100.0 % (7/7) | 95.8 % (23/24) | 9.34 s |

## Harmful decisions

None.

## Other documents not handled as labelled

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| C-092 | scan | anglo, en | approved | review | consensus |  |
| C-102 | clean | footer_ids, en | approved | review | arithmetic |  |
| C-111 | scan | footer_ids, fr | approved | review | consensus |  |
| C-171 | injection/visible_approval | footer_ids, en | approved | review | arithmetic |  |
| C-196 | injection/hidden_type | german, de | approved | review | document_type, not_invoice | supplier record, document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, po_number, total_net, total_tax, total_gross |
| C-214 | injection/hidden_type | german, de | approved | review | document_type, not_invoice | supplier record, document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, po_number, total_net, total_tax, total_gross |
| C-237 | clean | footer_ids, en | approved | review | arithmetic |  |
| C-249 | injection/hidden_type | compact, fr | approved | review | document_type, not_invoice | supplier record, document_type, invoice_number, issue_date, due_date, currency, supplier_vat_id, supplier_iban, total_net, total_tax, total_gross, supplier_siret, charge_total |
| C-260 | scan | footer_ids, fr | approved | review | consensus |  |
