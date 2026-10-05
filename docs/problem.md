# The problem

## Status of this page

Orvane Industries does not exist. This page describes a case built for the prototype:
a plausible accounts-payable team, not the result of interviews. Volumes and pain
points are working assumptions, not measurements.

## Starting point (assumed)

Orvane Industries, a manufacturer in Lyon, receives a few hundred supplier invoices a
month, as PDF attached to e-mail. An accounts-payable clerk:

1. opens the PDF and keys the header into the ERP: supplier, number, dates, totals;
2. checks that the supplier exists and that the totals add up;
3. finds the purchase order, when there is one, and compares the amount;
4. posts the invoice, which will be paid at its due date to the account on file.

Suppliers are French, British, Irish, Dutch, German, Swiss, Spanish, Italian and
American. Their invoices differ in language, layout, number format and date format.
Some are scans. Since 1 September 2026 a growing share arrive as hybrid e-invoices
that carry their own data
([economie.gouv.fr](https://www.economie.gouv.fr/tout-savoir-sur-la-facturation-electronique-pour-les-entreprises)).

## What goes wrong

| Problem | What the prototype sets against it |
|---|---|
| Keying takes time and is done by people who could be handling exceptions | A model reads; a person sees only what could not be verified |
| A mistyped amount or date is posted | Arithmetic and consistency checks before anything is posted |
| The same invoice is paid twice | Content hash, supplier-and-number check, a unique index in the database |
| An invoice meant for another company lands in the mailbox | The page must name the buyer |
| An invoice arrives with someone else's bank account | Bank details compared with the vendor master, and never taken from the invoice |
| A quote or a pro forma invoice is posted as an invoice | The kind of document is checked against its title |
| Nobody can say afterwards why an invoice was approved | Every approval lists the checks that passed, the model and prompt version used |

## What the system must never do

- Approve an invoice with a wrong supplier, amount, number or date.
- Approve an invoice whose bank account is not the one on file, or pay to it.
- Approve an invoice the supplier got wrong (totals that do not add up, VAT at the
  wrong rate) by quietly correcting it.
- Set aside a real invoice without anyone being asked to look.
- Do anything a sentence written in a document tells it to do.

The evaluation counts the first four as *harmful decisions*. Everything else, including
sending a perfectly good invoice to a person, is a cost and not a failure.

## What to measure in real use

The API exposes these; none has a target validated with users.

- share of documents approved without a person;
- share of approvals later found wrong (the number that matters, and the one that can
  only be measured by auditing a sample);
- review backlog and time to decision;
- reasons documents are stopped, by supplier;
- model time per document.

## Open questions

A real project would settle these with the people concerned:

- Up to what amount may an invoice be approved without a person, if at all?
- Which suppliers must quote a purchase order, and what tolerance applies?
- Who updates a supplier's bank account, and how is the change confirmed?
- What is a duplicate: same number, or same number and amount?
- How long are files and extractions kept?
- Where do documents come from: a mailbox, a portal, an e-invoicing platform?
