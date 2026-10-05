# Evaluation: `prompt-v4` on the `dev` split

Models: `qwen3.5:4b`. Prompt: `extract_v4`. Checks: on.

Percentages are followed by their 95 % Wilson interval where it matters, and by the counts they come from.

## Summary

| Measure | Value |
|---|---|
| Documents | 100 |
| **Harmful decisions** | **0** (0 wrong approvals, 0 invoices set aside) |
| Approved without a person, among documents that can be | 75.8 % [63.8 to 84.8] (47/62) |
| Approvals that were right | 100.0 % [92.4 to 100.0] (47/47) |
| Stopped, among documents that must not be approved | 100.0 % [90.8 to 100.0] (38/38) |
| Stopped for the expected reason, among documents labelled with one | 97.4 % (37/38) |
| Outcome exactly as labelled | 84.0 % (84/100) |
| Invoices with every critical field right | 86.3 % [78.0 to 91.8] (82/95) |
| Invoices with every line right | 97.9 % (93/95) |
| Documents read by more than one tier | 0.0 % (0/100) |
| Model time per document | mean 6.15 s, median 5.83 s, 95th percentile 9.74 s |
| Tokens per document | 1765 in, 489 out |
| Model calls that failed | 0 |

## Field accuracy (invoices and credit notes)

| Field | Correct |
|---|---|
| `document_type` | 100.0 % (95/95) |
| `invoice_number` | 95.8 % (91/95) |
| `issue_date` | 100.0 % (95/95) |
| `due_date` | 100.0 % (95/95) |
| `currency` | 100.0 % (95/95) |
| `supplier_vat_id` | 96.8 % (92/95) |
| `supplier_iban` | 94.7 % (90/95) |
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
| bank_changed | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 6.19 s |
| bank_invalid | 2 | 0 | n/a | 100.0 % (2/2) | 50.0 % (1/2) | 6.96 s |
| clean | 40 | 0 | 92.5 % (37/40) | n/a | 95.0 % (38/40) | 6.01 s |
| credit_note | 4 | 0 | 0.0 % (0/4) | n/a | 0.0 % (0/4) | 3.98 s |
| duplicate | 3 | 0 | n/a | 100.0 % (3/3) | 100.0 % (3/3) | 6.18 s |
| einvoice | 4 | 0 | 100.0 % (4/4) | n/a | 100.0 % (4/4) | 0.0 s |
| einvoice_tampered | 2 | 0 | n/a | 100.0 % (2/2) | 0.0 % (0/2) | 0.0 s |
| injection | 6 | 0 | 100.0 % (3/3) | 100.0 % (3/3) | 50.0 % (3/6) | 7.53 s |
| long | 3 | 0 | 100.0 % (3/3) | n/a | 100.0 % (3/3) | 18.14 s |
| missing_field | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 6.03 s |
| not_invoice | 5 | 0 | n/a | 100.0 % (5/5) | n/a | 4.88 s |
| purchase_order | 5 | 0 | n/a | 100.0 % (5/5) | 100.0 % (5/5) | 5.27 s |
| scan | 8 | 0 | 0.0 % (0/8) | n/a | 87.5 % (7/8) | 8.78 s |
| scan_mismatch | 2 | 0 | n/a | 100.0 % (2/2) | 100.0 % (2/2) | 9.62 s |
| totals_mismatch | 6 | 0 | n/a | 100.0 % (6/6) | 100.0 % (6/6) | 5.19 s |
| unknown_supplier | 4 | 0 | n/a | 100.0 % (4/4) | 100.0 % (4/4) | 4.52 s |

## By group

| Group | Docs | Harmful | Approved when possible | Stopped when needed | Critical fields right | Model time |
|---|---|---|---|---|---|---|
| seen suppliers | 100 | 0 | 75.8 % (47/62) | 100.0 % (38/38) | 86.3 % (82/95) | 6.15 s |
| text layer | 84 | 0 | 86.0 % (43/50) | 100.0 % (34/34) | 87.3 % (69/79) | 6.25 s |
| scans | 10 | 0 | 0.0 % (0/8) | 100.0 % (2/2) | 90.0 % (9/10) | 8.95 s |
| embedded e-invoice | 6 | 0 | 100.0 % (4/4) | 100.0 % (2/2) | 66.7 % (4/6) | 0.0 s |
| language: en | 23 | 0 | 76.9 % (10/13) | 100.0 % (10/10) | 86.4 % (19/22) | 5.34 s |
| language: fr | 77 | 0 | 75.5 % (37/49) | 100.0 % (28/28) | 86.3 % (63/73) | 6.39 s |
| layout: anglo | 23 | 0 | 76.9 % (10/13) | 100.0 % (10/10) | 86.4 % (19/22) | 5.34 s |
| layout: classic | 32 | 0 | 73.7 % (14/19) | 100.0 % (13/13) | 93.3 % (28/30) | 7.2 s |
| layout: columns | 28 | 0 | 73.7 % (14/19) | 100.0 % (9/9) | 81.5 % (22/27) | 6.12 s |
| layout: ledger | 17 | 0 | 81.8 % (9/11) | 100.0 % (6/6) | 81.2 % (13/16) | 5.3 s |

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
| D-036 | credit_note | columns, fr | approved | review | missing_field | invoice_number, referenced_invoice |
| D-037 | credit_note | columns, fr | approved | review | missing_field | invoice_number, referenced_invoice |
| D-039 | scan | ledger, fr | approved | review | consensus |  |
| D-041 | clean | columns, fr | approved | review | arithmetic |  |
| D-047 | clean | classic, fr | approved | review | bank_details, grounding | supplier_iban |
| D-051 | scan | classic, fr | approved | review | consensus |  |
| D-056 | clean | ledger, fr | approved | review | supplier, grounding | supplier_vat_id |
| D-062 | not_invoice/proforma | anglo, en | rejected | review | document_type, invoice_number |  |
| D-067 | scan | classic, fr | approved | review | consensus |  |
| D-071 | credit_note | columns, fr | approved | review | missing_field | invoice_number, referenced_invoice |
| D-073 | credit_note | anglo, en | approved | review | missing_field | invoice_number, referenced_invoice |
