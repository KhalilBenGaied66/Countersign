# Evaluation: `prompt-v3` on the `dev` split

Models: `qwen3.5:4b`. Prompt: `extract_v3`. Checks: on.

Percentages are followed by their 95 % Wilson interval where it matters, and by the counts they come from.

## Summary

| Measure | Value |
|---|---|
| Documents | 100 |
| **Harmful decisions** | **0** (0 wrong approvals, 0 invoices set aside) |
| Approved without a person, among documents that can be | 82.3 % [71.0 to 89.8] (51/62) |
| Approvals that were right | 100.0 % [93.0 to 100.0] (51/51) |
| Stopped, among documents that must not be approved | 100.0 % [90.8 to 100.0] (38/38) |
| Stopped for the expected reason, among documents labelled with one | 94.7 % (36/38) |
| Outcome exactly as labelled | 89.0 % (89/100) |
| Invoices with every critical field right | 89.5 % [81.7 to 94.2] (85/95) |
| Invoices with every line right | 97.9 % (93/95) |
| Documents read by more than one tier | 0.0 % (0/100) |
| Model time per document | mean 6.13 s, median 5.82 s, 95th percentile 9.57 s |
| Tokens per document | 1585 in, 490 out |
| Model calls that failed | 0 |

## Field accuracy (invoices and credit notes)

| Field | Correct |
|---|---|
| `document_type` | 100.0 % (95/95) |
| `invoice_number` | 96.8 % (92/95) |
| `issue_date` | 100.0 % (95/95) |
| `due_date` | 100.0 % (95/95) |
| `currency` | 100.0 % (95/95) |
| `supplier_vat_id` | 97.9 % (93/95) |
| `supplier_iban` | 95.8 % (91/95) |
| `po_number` | 100.0 % (95/95) |
| `total_net` | 98.9 % (94/95) |
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
| clean | 40 | 0 | 95.0 % (38/40) | n/a | 97.5 % (39/40) | 6.08 s |
| credit_note | 4 | 0 | 75.0 % (3/4) | n/a | 75.0 % (3/4) | 4.15 s |
| duplicate | 3 | 0 | n/a | 100.0 % (3/3) | 100.0 % (3/3) | 6.29 s |
| einvoice | 4 | 0 | 100.0 % (4/4) | n/a | 100.0 % (4/4) | 0.0 s |
| einvoice_tampered | 2 | 0 | n/a | 100.0 % (2/2) | 0.0 % (0/2) | 0.0 s |
| injection | 6 | 0 | 100.0 % (3/3) | 100.0 % (3/3) | 50.0 % (3/6) | 6.14 s |
| long | 3 | 0 | 100.0 % (3/3) | n/a | 100.0 % (3/3) | 18.18 s |
| missing_field | 2 | 0 | n/a | 100.0 % (2/2) | 0.0 % (0/2) | 6.06 s |
| not_invoice | 5 | 0 | n/a | 100.0 % (5/5) | n/a | 4.89 s |
| purchase_order | 5 | 0 | n/a | 100.0 % (5/5) | 100.0 % (5/5) | 5.34 s |
| scan | 8 | 0 | 0.0 % (0/8) | n/a | 87.5 % (7/8) | 8.9 s |
| scan_mismatch | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 9.59 s |
| totals_mismatch | 6 | 0 | n/a | 100.0 % (6/6) | 100.0 % (6/6) | 5.27 s |
| unknown_supplier | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 4.57 s |

## By group

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| seen suppliers | 100 | 0 | 82.3 % (51/62) | 100.0 % (38/38) | 89.5 % (85/95) | 6.13 s |
| text layer | 84 | 0 | 94.0 % (47/50) | 100.0 % (34/34) | 91.1 % (72/79) | 6.22 s |
| scans | 10 | 0 | 0.0 % (0/8) | 100.0 % (2/2) | 90.0 % (9/10) | 9.04 s |
| embedded e-invoice | 6 | 0 | 100.0 % (4/4) | 100.0 % (2/2) | 66.7 % (4/6) | 0.0 s |
| language: en | 23 | 0 | 84.6 % (11/13) | 100.0 % (10/10) | 90.9 % (20/22) | 5.38 s |
| language: fr | 77 | 0 | 81.6 % (40/49) | 100.0 % (28/28) | 89.0 % (65/73) | 6.35 s |
| layout: anglo | 23 | 0 | 84.6 % (11/13) | 100.0 % (10/10) | 90.9 % (20/22) | 5.38 s |
| layout: classic | 32 | 0 | 78.9 % (15/19) | 100.0 % (13/13) | 90.0 % (27/30) | 6.99 s |
| layout: columns | 28 | 0 | 84.2 % (16/19) | 100.0 % (9/9) | 88.9 % (24/27) | 6.26 s |
| layout: ledger | 17 | 0 | 81.8 % (9/11) | 100.0 % (6/6) | 87.5 % (14/16) | 5.3 s |

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
| D-051 | scan | classic, fr | approved | review | consensus |  |
| D-056 | clean | ledger, fr | approved | review | supplier, grounding | supplier_vat_id |
| D-067 | scan | classic, fr | approved | review | consensus |  |
| D-071 | credit_note | columns, fr | approved | review | duplicate | invoice_number, referenced_invoice |
