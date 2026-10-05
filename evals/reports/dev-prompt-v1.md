# Evaluation: `prompt-v1` on the `dev` split

Models: `qwen3.5:4b`. Prompt: `extract_v1`. Checks: on.

Percentages are followed by their 95 % Wilson interval where it matters, and by the counts they come from.

## Summary

| Measure | Value |
|---|---|
| Documents | 100 |
| **Harmful decisions** | **0** (0 wrong approvals, 0 invoices set aside) |
| Approved without a person, among documents that can be | 59.7 % [47.2 to 71.0] (37/62) |
| Approvals that were right | 100.0 % [90.6 to 100.0] (37/37) |
| Stopped, among documents that must not be approved | 100.0 % [90.8 to 100.0] (38/38) |
| Stopped for the expected reason, among documents labelled with one | 97.4 % (37/38) |
| Outcome exactly as labelled | 74.0 % (74/100) |
| Invoices with every critical field right | 89.5 % [81.7 to 94.2] (85/95) |
| Invoices with every line right | 88.4 % (84/95) |
| Documents read by more than one tier | 0.0 % (0/100) |
| Model time per document | mean 6.83 s, median 6.49 s, 95th percentile 10.34 s |
| Tokens per document | 1428 in, 548 out |
| Model calls that failed | 0 |

## Field accuracy (invoices and credit notes)

| Field | Correct |
|---|---|
| `document_type` | 100.0 % (95/95) |
| `invoice_number` | 97.9 % (93/95) |
| `issue_date` | 100.0 % (95/95) |
| `due_date` | 100.0 % (95/95) |
| `currency` | 100.0 % (95/95) |
| `supplier_vat_id` | 97.9 % (93/95) |
| `supplier_iban` | 95.8 % (91/95) |
| `po_number` | 100.0 % (95/95) |
| `total_net` | 97.9 % (93/95) |
| `total_tax` | 97.9 % (93/95) |
| `total_gross` | 97.9 % (93/95) |
| `supplier_siret` | 100.0 % (95/95) |
| `referenced_invoice` | 95.8 % (91/95) |
| `allowance_total` | 100.0 % (95/95) |
| `charge_total` | 98.9 % (94/95) |

## By scenario

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| bank_changed | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 7.49 s |
| bank_invalid | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 7.35 s |
| clean | 40 | 0 | 67.5 % (27/40) | n/a | 97.5 % (39/40) | 6.78 s |
| credit_note | 4 | 0 | 50.0 % (2/4) | n/a | 75.0 % (3/4) | 4.43 s |
| duplicate | 3 | 0 | n/a | 100.0 % (3/3) | 100.0 % (3/3) | 6.9 s |
| einvoice | 4 | 0 | 100.0 % (4/4) | n/a | 100.0 % (4/4) | 0.0 s |
| einvoice_tampered | 2 | 0 | n/a | 100.0 % (2/2) | 0.0 % (0/2) | 0.0 s |
| injection | 6 | 0 | 100.0 % (3/3) | 100.0 % (3/3) | 50.0 % (3/6) | 6.78 s |
| long | 3 | 0 | 33.3 % (1/3) | n/a | 100.0 % (3/3) | 24.11 s |
| missing_field | 2 | 0 | n/a | 100.0 % (2/2) | 50.0 % (1/2) | 6.43 s |
| not_invoice | 5 | 0 | n/a | 100.0 % (5/5) | n/a | 5.09 s |
| purchase_order | 5 | 0 | n/a | 100.0 % (5/5) | 100.0 % (5/5) | 5.8 s |
| scan | 8 | 0 | 0.0 % (0/8) | n/a | 87.5 % (7/8) | 9.27 s |
| scan_mismatch | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 9.89 s |
| totals_mismatch | 6 | 0 | n/a | 100.0 % (6/6) | 83.3 % (5/6) | 5.53 s |
| unknown_supplier | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 5.37 s |

## By group

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| seen suppliers | 100 | 0 | 59.7 % (37/62) | 100.0 % (38/38) | 89.5 % (85/95) | 6.83 s |
| text layer | 84 | 0 | 66.0 % (33/50) | 100.0 % (34/34) | 91.1 % (72/79) | 7.01 s |
| scans | 10 | 0 | 0.0 % (0/8) | 100.0 % (2/2) | 90.0 % (9/10) | 9.39 s |
| embedded e-invoice | 6 | 0 | 100.0 % (4/4) | 100.0 % (2/2) | 66.7 % (4/6) | 0.0 s |
| language: en | 23 | 0 | 46.2 % (6/13) | 100.0 % (10/10) | 90.9 % (20/22) | 6.23 s |
| language: fr | 77 | 0 | 63.3 % (31/49) | 100.0 % (28/28) | 89.0 % (65/73) | 7.01 s |
| layout: anglo | 23 | 0 | 46.2 % (6/13) | 100.0 % (10/10) | 90.9 % (20/22) | 6.23 s |
| layout: classic | 32 | 0 | 42.1 % (8/19) | 100.0 % (13/13) | 90.0 % (27/30) | 7.86 s |
| layout: columns | 28 | 0 | 68.4 % (13/19) | 100.0 % (9/9) | 88.9 % (24/27) | 6.83 s |
| layout: ledger | 17 | 0 | 90.9 % (10/11) | 100.0 % (6/6) | 87.5 % (14/16) | 5.71 s |

## Harmful decisions

None.

## Other documents not handled as labelled

| Document | Scenario | Layout | Expected | Got | Reasons | Wrong fields |
|---|---|---|---|---|---|---|
| D-002 | long | classic, fr | approved | review | extraction, arithmetic |  |
| D-004 | clean | columns, fr | approved | review | arithmetic |  |
| D-006 | scan | classic, fr | approved | review | consensus |  |
| D-007 | scan | anglo, en | approved | review | supplier, consensus | supplier record, supplier_vat_id |
| D-008 | clean | anglo, en | approved | review | arithmetic |  |
| D-013 | clean | anglo, en | approved | review | arithmetic |  |
| D-017 | clean | anglo, en | approved | review | arithmetic |  |
| D-019 | clean | classic, fr | approved | review | arithmetic |  |
| D-023 | scan | columns, fr | approved | review | consensus |  |
| D-027 | scan | classic, fr | approved | review | consensus |  |
| D-032 | scan | anglo, en | approved | review | consensus |  |
| D-033 | clean | classic, fr | approved | review | arithmetic |  |
| D-037 | credit_note | columns, fr | approved | review | arithmetic | referenced_invoice |
| D-039 | scan | ledger, fr | approved | review | consensus |  |
| D-041 | clean | columns, fr | approved | review | arithmetic |  |
| D-043 | clean | columns, fr | approved | review | arithmetic |  |
| D-047 | clean | classic, fr | approved | review | arithmetic |  |
| D-051 | scan | classic, fr | approved | review | consensus |  |
| D-052 | clean | classic, fr | approved | review | missing_field | total_net, total_tax, total_gross, charge_total |
| D-061 | clean | anglo, en | approved | review | arithmetic |  |
| D-063 | duplicate | columns, fr | duplicate | review | duplicate, arithmetic |  |
| D-067 | scan | classic, fr | approved | review | arithmetic, consensus |  |
| D-071 | credit_note | columns, fr | approved | review | duplicate | invoice_number, referenced_invoice |
| D-080 | clean | anglo, en | approved | review | arithmetic |  |
| D-086 | long | classic, fr | approved | review | arithmetic |  |
| D-091 | clean | classic, fr | approved | review | arithmetic |  |
