# Evaluation: `small` on the `dev` split

Models: `qwen3.5:4b`. Prompt: `extract_v5`. Checks: on.

Percentages are followed by their 95 % Wilson interval where it matters, and by the counts they come from.

## Summary

| Measure | Value |
|---|---|
| Documents | 100 |
| **Harmful decisions** | **0** (0 wrong approvals, 0 invoices set aside) |
| Approved without a person, among documents that can be | 80.6 % [69.2 to 88.6] (50/62) |
| Approvals that were right | 100.0 % [92.9 to 100.0] (50/50) |
| Stopped, among documents that must not be approved | 100.0 % [90.8 to 100.0] (38/38) |
| Stopped for the expected reason, among documents labelled with one | 97.4 % (37/38) |
| Outcome exactly as labelled | 87.0 % (87/100) |
| Invoices with every critical field right | 89.5 % [81.7 to 94.2] (85/95) |
| Invoices with every line right | 97.9 % (93/95) |
| Documents read by more than one tier | 0.0 % (0/100) |
| Model time per document | mean 6.28 s, median 5.96 s, 95th percentile 9.73 s |
| Tokens per document | 1800 in, 499 out |
| Model calls that failed | 0 |

## Field accuracy (invoices and credit notes)

| Field | Correct |
|---|---|
| `document_type` | 100.0 % (95/95) |
| `invoice_number` | 100.0 % (95/95) |
| `issue_date` | 100.0 % (95/95) |
| `due_date` | 100.0 % (95/95) |
| `currency` | 100.0 % (95/95) |
| `supplier_vat_id` | 95.8 % (91/95) |
| `supplier_iban` | 93.7 % (89/95) |
| `po_number` | 100.0 % (95/95) |
| `total_net` | 98.9 % (94/95) |
| `total_tax` | 98.9 % (94/95) |
| `total_gross` | 98.9 % (94/95) |
| `supplier_siret` | 100.0 % (95/95) |
| `referenced_invoice` | 100.0 % (95/95) |
| `allowance_total` | 100.0 % (95/95) |
| `charge_total` | 100.0 % (95/95) |

## By scenario

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| bank_changed | 4 | 0 | n/a | 100.0 % (4/4) | 75.0 % (3/4) | 6.34 s |
| bank_invalid | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 7.09 s |
| clean | 40 | 0 | 92.5 % (37/40) | n/a | 95.0 % (38/40) | 6.15 s |
| credit_note | 4 | 0 | 100.0 % (4/4) | n/a | 100.0 % (4/4) | 4.15 s |
| duplicate | 3 | 0 | n/a | 100.0 % (3/3) | 100.0 % (3/3) | 6.42 s |
| einvoice | 4 | 0 | 100.0 % (4/4) | n/a | 100.0 % (4/4) | 0.0 s |
| einvoice_tampered | 2 | 0 | n/a | 100.0 % (2/2) | 0.0 % (0/2) | 0.0 s |
| injection | 6 | 0 | 66.7 % (2/3) | 100.0 % (3/3) | 33.3 % (2/6) | 6.32 s |
| long | 3 | 0 | 100.0 % (3/3) | n/a | 100.0 % (3/3) | 18.24 s |
| missing_field | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 5.95 s |
| not_invoice | 5 | 0 | n/a | 100.0 % (5/5) | n/a | 5.1 s |
| purchase_order | 5 | 0 | n/a | 100.0 % (5/5) | 100.0 % (5/5) | 5.34 s |
| scan | 8 | 0 | 0.0 % (0/8) | n/a | 87.5 % (7/8) | 9.01 s |
| scan_mismatch | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 14.0 s |
| totals_mismatch | 6 | 0 | n/a | 100.0 % (6/6) | 100.0 % (6/6) | 5.29 s |
| unknown_supplier | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 4.64 s |

## By group

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| seen suppliers | 100 | 0 | 80.6 % (50/62) | 100.0 % (38/38) | 89.5 % (85/95) | 6.28 s |
| text layer | 84 | 0 | 92.0 % (46/50) | 100.0 % (34/34) | 91.1 % (72/79) | 6.29 s |
| scans | 10 | 0 | 0.0 % (0/8) | 100.0 % (2/2) | 90.0 % (9/10) | 10.01 s |
| embedded e-invoice | 6 | 0 | 100.0 % (4/4) | 100.0 % (2/2) | 66.7 % (4/6) | 0.0 s |
| language: en | 23 | 0 | 84.6 % (11/13) | 100.0 % (10/10) | 90.9 % (20/22) | 5.44 s |
| language: fr | 77 | 0 | 79.6 % (39/49) | 100.0 % (28/28) | 89.0 % (65/73) | 6.54 s |
| layout: anglo | 23 | 0 | 84.6 % (11/13) | 100.0 % (10/10) | 90.9 % (20/22) | 5.44 s |
| layout: classic | 32 | 0 | 73.7 % (14/19) | 100.0 % (13/13) | 93.3 % (28/30) | 7.38 s |
| layout: columns | 28 | 0 | 89.5 % (17/19) | 100.0 % (9/9) | 88.9 % (24/27) | 6.27 s |
| layout: ledger | 17 | 0 | 72.7 % (8/11) | 100.0 % (6/6) | 81.2 % (13/16) | 5.39 s |

## Harmful decisions

None.

## Other documents not handled as labelled

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| D-006 | scan | classic, fr | approved | review | consensus |  |
| D-007 | scan | anglo, en | approved | review | supplier, consensus | supplier record, supplier_vat_id |
| D-023 | scan | columns, fr | approved | review | consensus |  |
| D-027 | scan | classic, fr | approved | review | consensus |  |
| D-032 | scan | anglo, en | approved | review | consensus |  |
| D-039 | scan | ledger, fr | approved | review | consensus |  |
| D-041 | clean | columns, fr | approved | review | arithmetic |  |
| D-047 | clean | classic, fr | approved | review | bank_details, grounding | supplier_iban |
| D-051 | scan | classic, fr | approved | review | consensus |  |
| D-056 | clean | ledger, fr | approved | review | supplier, grounding | supplier_vat_id |
| D-062 | not_invoice/proforma | anglo, en | rejected | review | document_type, invoice_number |  |
| D-067 | scan | classic, fr | approved | review | consensus |  |
| D-076 | injection/visible_supplier | ledger, fr | approved | review | supplier, grounding | supplier_vat_id |
