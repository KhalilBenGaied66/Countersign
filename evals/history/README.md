# The two live runs, as they were written

These twenty files are the reports of the two splits that were run once on documents
the code had never met, on 2 October 2026:

- `test-*`: the test split, with the pipeline as it was frozen before the run;
- `confirm-*`: the confirmation split, with the code as it stood after the fixes that
  followed the first run.

They are the measurements. They are a record, not a regression target: the code has
changed since each run (two code reviews, then the fix for what each run found), so
`python -m countersign.eval.gate` does not recompute them. It recomputes the reports
under `evals/reports`, which are those of the current code on the same recorded model
answers.

What changed between the two sets, and why, is in
[docs/evaluation.md](../../docs/evaluation.md).
