# Decisions

Each entry gives the choice, why, what was discarded, and what the choice costs.
Numbers come from [evaluation.md](evaluation.md). Entries 17 to 20 were added after two
code reviews and the first run on the test split; several earlier ones were amended
then, and say so.

## 1. The model reads, code decides

**Choice.** A model returns the fields of a form. Normalisation, checks and the
decision are code. The model has no tool and is never asked whether to approve.

**Why.** An approval moves money. It has to be explainable by naming the checks that
passed, reproducible on the same input, and testable without a model.

**Discarded.** An agent that looks up the supplier, compares with the order and
decides. It would put a model in the path of an instruction written in the document,
and its decision could only be audited by reading a transcript.

**Cost.** Anything the checks do not encode is not caught. The checks are the
product; the list in [architecture.md](architecture.md) is finite.

## 2. No self-reported confidence

**Choice.** Whether an extraction can be trusted is decided by comparing it with
things the model does not control: arithmetic, checksums, the text of the page, the
vendor master, the order book, the ledger of documents already received.

**Why.** A model that misreads a total is not less confident about it. Evidence that
is independent of the reader fails for different reasons than the reader does.

**Discarded.** A confidence field in the output; log-probabilities; a second model
grading the first. All three ask a model about a model.

**Cost.** Fields without independent evidence are weakly protected. A date is checked
against the one printed after its label only when the label is in the vocabulary;
otherwise it only has to be on the page and in a plausible order. An invoice number
must be printed as a whole and fit the supplier's numbering, digit widths included,
which is evidence, not proof: the customer code of a supplier that numbers its invoices
with as many digits would pass.

## 3. Sweeps: read the page without the model

**Choice.** IBANs, the buyer's own order numbers, the title of the document, the
totals and dates printed after their label, and the name of the buyer are found by
pattern in the text layer, independently of the model.

**Why.** A check on what the model reports says nothing about what it leaves out. An
account number the model ignores, or is told to ignore, is still on the page.

**Cost.** Patterns are vocabulary. Titles and date labels are recognised by a list of
words in five languages; labelled totals in French and English only. Outside the
vocabulary a sweep provides no evidence, and says so by passing nothing rather than
failing. An IBAN is recognised by the structure its country gives it, for the
thirty-six countries of the euro payments area; an account written any other way is
not swept.

## 4. A cascade, small model first

**Choice.** The 4.7 B model reads every document. The 9.7 B model reads a document
only when a failed check says another reading could help, or when the document is a
scan.

**Why.** The larger model reads a little better and takes half as long again: on the
test split it gets every critical field right on 92 % of invoices against 91 %, in
11.5 s per document against 7.6 s. Reading everything with both would more than double
the cost for that point. Reading with the second where a check contradicts the first
uses it as a second opinion, which is what it is good for: on the test split 40 text
documents were read twice, and 11 of them were approved on the second reading.

**Discarded.** The larger model alone: half as long again on every document, and still
one reader, so no scan could be approved. A hosted frontier model as the last tier: it
would send supplier invoices and bank details to a third party, for a gain that was
not measured.

**Cost.** Two models in video memory (about 10 GB with a 16k context). A reading error
that passes every check on the first tier is never seen by the second.

## 5. Escalation is decided by the kind of failure

**Choice.** Each failed check says whether another reading could change it. A value
that is not on the page is worth a second reading. A value that is on the page and
contradicts the vendor master is a fact about the document, and goes to a person
directly.

**Why.** Without this rule every document that must be stopped (a changed bank
account, an unknown supplier) would first cost a second model call that cannot help.

**Cost.** The rule rests on the text layer. For a scan nothing can be told apart, so
everything is read twice.

## 6. The second reading is blind

**Choice.** The second tier gets the same prompt and the same document. It is not told
what the first tier answered nor which check failed.

**Why.** "Your lines add up to 464.60 but you reported 446.60" is an invitation to
write 464.60. The check would then pass because the model was told the answer, not
because the page says so, and an invoice whose printed total is wrong would be
approved with a corrected one.

**Discarded.** A repair loop that feeds the failed checks back. It is the usual
pattern for structured output, and it removes the independence the checks rely on.

**Cost.** The second model may repeat the first one's mistake.

## 7. A second reading may not overrule a printed amount

**Choice.** If the first reading found a total on the page and the second reading
reports another value for it, the document goes to review, even when the second
reading passes every check.

**Why.** Found on the dev split: a supplier's net total was misprinted, the VAT table
next to it was right. The small model reported the misprinted total, which failed the
arithmetic. The large model reported the base from the VAT table, which made
everything add up, and the document was approved with a figure it does not print.
Two values on one page for the same total is not a reading problem.

**Cost.** On the dev split it stopped that document and no other. A wrong pick by the
first tier that happens to be printed elsewhere costs a review. The rule was extended
to line amounts after the confirmation split, where the large model replaced a
misprinted line amount by the one the totals imply; a line amount must also stand on
the row of its unit price, which stops the same tidying by a first reader. A first value that is only
some digits of a longer number ("435,57" out of "1 435,57") is not a candidate: the
page does not print it as a number of its own.

## 8. Scans are keyed twice

**Choice.** A document without a text layer is read from page images by both models
and approved only if they agree on every critical field.

**Why.** There is no text to check a value against. Two different readers making the
same mistake on the same digit is less likely than either making it.

**Discarded.** An OCR engine in front, to give the checks a text layer. It is the
natural next step and was left out to keep the measurement about the models; see
[production.md](production.md).

**Cost.** Two model calls per scan, and a low automatic rate: one misread digit by
either model sends the scan to a person. With a single model no scan is approved at
all, and a scan of several pages is not read: two page images do not fit the context
window next to the answer.

## 9. An embedded e-invoice is read as data

**Choice.** When the PDF carries its own XML (Factur-X, ZUGFeRD), the XML is read and
no model is called. The result goes through the same checks, including the comparison
with the visible page.

**Why.** Structured data from the issuer beats reading a rendering of it. Since
1 September 2026 every company in France must be able to receive e-invoices, large
companies must issue them, and smaller ones follow in September 2027
([economie.gouv.fr](https://www.economie.gouv.fr/tout-savoir-sur-la-facturation-electronique-pour-les-entreprises)).
The share of documents that need no extraction can only grow.

**Cost.** The XML is trusted no more than the page: a hybrid invoice whose XML and
page disagree goes to review, as does one whose XML passes but whose page has no text
to compare with. No model is asked to arbitrate. An XML the reader does not handle (a
profile without line items, a type code other than invoice and credit note) is set
aside and the page is read by the models: its data is then not used at all.

## 10. Amounts as numbers, dates as printed

**Choice.** The model returns amounts as JSON numbers and dates as the text printed.

**Why.** Measured. The first prompt asked for every value as text, to keep number
formats out of the model's hands. Under constrained decoding both models then produced
values such as `"{\"value\": 35}"`, or empty strings. Asking for numbers removed the
problem. Dates stay as printed because "03/04/2026" cannot be resolved from one field:
the day/month order is inferred from the whole document.

**Cost.** The model converts "1.234,56" itself. A conversion error is caught by the
arithmetic and by the comparison with the numbers on the page, not prevented.

## 11. Prompts are versioned, with their output shape

**Choice.** A prompt is a numbered file tied to the JSON schema it asks for. A change
is a new version; earlier versions stay.

**Why.** The id is stored with every extraction. A recorded answer belongs to the
exact wording that produced it, and the effect of each change can be measured against
the previous version on the same documents.

**Cost.** Five files for what is one prompt in use.

## 12. Model answers are recorded and replayed

**Choice.** Every evaluation call is stored under the hash of its request. CI
recomputes all committed reports from the recordings and fails if one byte differs.

**Why.** The code around the model changes far more often than the model's answers. A
change to a check should be testable in seconds against hundreds of real answers, on a
machine without a GPU, and a report in the repository should be provably current.

**Discarded.** Running small models in CI. Slow, and it would measure a different
model on different hardware than the numbers published.

**Cost.** A few megabytes of recordings in the repository. A prompt change needs the
GPU again before CI passes, which is intended. The key of a scan names the file, the
resolution and the rasterising recipe rather than the pixels, so that a recording
replays on another platform: a change in how pages are drawn has to be declared by
hand, by changing that name.

## 13. Local open-weight models

**Choice.** Two Apache-licensed models served by Ollama on one consumer GPU.

**Why.** Invoices carry prices, volumes and bank accounts. Nothing leaves the machine,
there is no per-document fee, and the evaluation can be reproduced by anyone with the
same card.

**Cost.** Throughput is one request at a time. The models are whatever fits in 16 GB,
not the best available. Ollama is a convenience, not a serving stack: see
[production.md](production.md).

## 14. The queue is a table

**Choice.** Jobs live in the database next to the documents; claiming is one atomic
statement, with a lease.

**Why.** One GPU reads a few hundred documents an hour. A broker would be the largest
component of the deployment and add a second place where a document's state lives.

**Cost.** Polling, once a second per idle worker. Delivery is at-least-once, made safe
by idempotent processing and a unique index rather than by the queue. A lease is not
renewed, so it has to outlast the slowest possible document: a job whose worker died
waits about 25 minutes with the default timeouts before another worker takes it.

## 15. Only an exact repeat is a duplicate

**Choice.** A document is set aside as a duplicate only if supplier, number, kind,
gross total and issue date all match an earlier one, and nothing else is wrong with
it. The same number on a different document goes to another reading, then to a person.
So does the number of a document that a person rejected.

**Why.** Found on the dev split: a credit note was read with the number of the invoice
it cancels, matched that invoice, and was dropped as its duplicate. Nobody would have
seen it. A credit note now also has a field for the invoice it refers to, which gives
the model somewhere else to put that number, and the two may not be equal. The date
was added after a review: a monthly invoice of a constant amount, read with the number
of last month's, was otherwise the "same" document.

**Cost.** A genuine duplicate re-issued with a corrected amount is shown to a person
instead of being set aside, and so is the copy of an invoice that was itself sent to
review.

## 16. Payment details come from the vendor master

**Choice.** The export carries the IBAN on file. The IBAN printed on an invoice is
only ever compared with it.

**Why.** It makes the worst case of every other failure harmless for the bank account:
an approved invoice with a forged IBAN still pays the real supplier.

**Cost.** A supplier that really changed bank is paid to the old account until the
master is updated, through a process outside this system.

## 17. Nothing is set aside on one reading

**Choice.** "Not an invoice" needs two sources that agree: the reading and the title of
the page, or two readings. One reading alone, or two that disagree, send the document
to a person. A scan read by a single model is never approved.

**Why.** Setting a document aside is the one decision nobody looks at afterwards. A
review found five ways in which a real invoice ended there on the word of one model:
the last of two readings was taken as the verdict, whatever the first one said.

**Cost.** A quote with a title outside the vocabulary costs a second model call, and a
person when the two models disagree.

## 18. A title is what is printed large

**Choice.** The kind of document a page claims to be is read from the text the first
page prints clearly larger than the rest. A page printed in one size falls back on a
column in capitals among the first lines.

**Why.** The first version looked for capitals, because the synthetic documents print
their titles that way. A review showed what that does to "Avoir" or "Facture pro
forma" in lower case: the credit note was taken for an invoice, and the correct
reading was the one that got stopped.

**Cost.** A second pass over the first page to get font sizes. A title in the same
size and case as the body is not seen.

## 19. Arithmetic that cannot be checked does not pass

**Choice.** When a check on the document's own figures has nothing to compare, it
either has another way to reach the same conclusion or it fails. VAT rows without bases are reconciled with the net
total through the base each row implies; VAT without any rate fails; a line without an
amount does not switch the addition off.

**Why.** Found by the test split: two invoices with VAT at half its rate were
approved. Their pages printed no base per rate and no rate per line, so the check had
nothing to compare each row with and reported success. A review had found the same
pattern in the addition of the lines a few hours earlier.

**Cost.** An invoice partly outside VAT that says so nowhere (no 0 % row, no rate per
line) goes to a person.

## 20. A test split is used once

**Choice.** The test split was run once on the frozen pipeline. When it found
something, the fix was followed by a new split of documents never used before, run
once in turn. That one found something else. Both results are published as they were
measured, next to what the current code gives on the same recordings, and the two are
never mixed.

**Why.** A number measured on documents that were then used to fix the system is no
longer a measurement of the system on unseen documents. Three wrong approvals in 540
is the estimate; zero in 540 recomputed is a regression test.

**Cost.** An hour and a half of GPU time, and two sets of numbers to explain.

## Not done, on purpose

- **Fine-tuning.** Nothing measured suggests the reading is the bottleneck; the checks
  and the review rate are.
- **A judge model.** Every score in the evaluation is a comparison with ground truth.
- **A front-end framework.** The console is one page of plain JavaScript; its only
  hard requirement is never to insert document content as HTML.
- **A message broker, a vector store, an agent framework.** None has a job here.
