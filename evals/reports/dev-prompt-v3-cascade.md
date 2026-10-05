# Evaluation: `prompt-v3-cascade` on the `dev` split

Models: `qwen3.5:4b`, `qwen3.5:9b`. Prompt: `extract_v3`. Checks: on.

Percentages are followed by their 95 % Wilson interval where it matters, and by the counts they come from.

## Summary

| Measure | Value |
|---|---|
| Documents | 100 |
| **Harmful decisions** | **0** (0 wrong approvals, 0 invoices set aside) |
| Approved without a person, among documents that can be | 95.2 % [86.7 to 98.3] (59/62) |
| Approvals that were right | 100.0 % [93.9 to 100.0] (59/59) |
| Stopped, among documents that must not be approved | 100.0 % [90.8 to 100.0] (38/38) |
| Stopped for the expected reason, among documents labelled with one | 100.0 % (38/38) |
| Outcome exactly as labelled | 97.0 % (97/100) |
| Invoices with every critical field right | 90.5 % [83.0 to 94.9] (86/95) |
| Invoices with every line right | 98.9 % (94/95) |
| Documents read by more than one tier | 21.0 % (21/100) |
| Model time per document | mean 8.68 s, median 6.26 s, 95th percentile 24.14 s |
| Tokens per document | 2191 in, 594 out |
| Model calls that failed | 0 |

## Field accuracy (invoices and credit notes)

| Field | Correct |
|---|---|
| `document_type` | 100.0 % (95/95) |
| `invoice_number` | 100.0 % (95/95) |
| `issue_date` | 100.0 % (95/95) |
| `due_date` | 100.0 % (95/95) |
| `currency` | 100.0 % (95/95) |
| `supplier_vat_id` | 100.0 % (95/95) |
| `supplier_iban` | 93.7 % (89/95) |
| `po_number` | 98.9 % (94/95) |
| `total_net` | 97.9 % (93/95) |
| `total_tax` | 98.9 % (94/95) |
| `total_gross` | 98.9 % (94/95) |
| `supplier_siret` | 100.0 % (95/95) |
| `referenced_invoice` | 95.8 % (91/95) |
| `allowance_total` | 100.0 % (95/95) |
| `charge_total` | 100.0 % (95/95) |

## By scenario

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| bank_changed | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 6.29 s |
| bank_invalid | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 7.04 s |
| clean | 40 | 0 | 97.5 % (39/40) | n/a | 97.5 % (39/40) | 6.58 s |
| credit_note | 4 | 0 | 100.0 % (4/4) | n/a | 100.0 % (4/4) | 5.76 s |
| duplicate | 3 | 0 | n/a | 100.0 % (3/3) | 100.0 % (3/3) | 6.29 s |
| einvoice | 4 | 0 | 100.0 % (4/4) | n/a | 100.0 % (4/4) | 0.0 s |
| einvoice_tampered | 2 | 0 | n/a | 100.0 % (2/2) | 0.0 % (0/2) | 0.0 s |
| injection | 6 | 0 | 100.0 % (3/3) | 100.0 % (3/3) | 50.0 % (3/6) | 6.14 s |
| long | 3 | 0 | 100.0 % (3/3) | n/a | 100.0 % (3/3) | 18.18 s |
| missing_field | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 14.91 s |
| not_invoice | 5 | 0 | n/a | 100.0 % (5/5) | n/a | 4.89 s |
| purchase_order | 5 | 0 | n/a | 100.0 % (5/5) | 100.0 % (5/5) | 5.34 s |
| scan | 8 | 0 | 75.0 % (6/8) | n/a | 87.5 % (7/8) | 23.92 s |
| scan_mismatch | 2 | 0 | n/a | 100.0 % (2/2) | 50.0 % (1/2) | 31.61 s |
| totals_mismatch | 6 | 0 | n/a | 100.0 % (6/6) | 83.3 % (5/6) | 13.06 s |
| unknown_supplier | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 4.57 s |

## By group

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| seen suppliers | 100 | 0 | 95.2 % (59/62) | 100.0 % (38/38) | 90.5 % (86/95) | 8.68 s |
| text layer | 84 | 0 | 98.0 % (49/50) | 100.0 % (34/34) | 93.7 % (74/79) | 7.3 s |
| scans | 10 | 0 | 75.0 % (6/8) | 100.0 % (2/2) | 80.0 % (8/10) | 25.46 s |
| embedded e-invoice | 6 | 0 | 100.0 % (4/4) | 100.0 % (2/2) | 66.7 % (4/6) | 0.0 s |
| language: en | 23 | 0 | 84.6 % (11/13) | 100.0 % (10/10) | 86.4 % (19/22) | 7.59 s |
| language: fr | 77 | 0 | 98.0 % (48/49) | 100.0 % (28/28) | 91.8 % (67/73) | 9.01 s |
| layout: anglo | 23 | 0 | 84.6 % (11/13) | 100.0 % (10/10) | 86.4 % (19/22) | 7.59 s |
| layout: classic | 32 | 0 | 100.0 % (19/19) | 100.0 % (13/13) | 96.7 % (29/30) | 10.84 s |
| layout: columns | 28 | 0 | 94.7 % (18/19) | 100.0 % (9/9) | 85.2 % (23/27) | 7.83 s |
| layout: ledger | 17 | 0 | 100.0 % (11/11) | 100.0 % (6/6) | 93.8 % (15/16) | 7.49 s |

## Harmful decisions

None.

## Other documents not handled as labelled

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| D-007 | scan | anglo, en | approved | review | consensus |  |
| D-032 | scan | anglo, en | approved | review | bank_details, consensus | supplier_iban |
| D-041 | clean | columns, fr | approved | review | purchase_order | po_number |
