# Operations

## Run

Python 3.11 or later and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

### Without a GPU

```bash
uv run countersign demo
```

The application then answers from the model answers recorded during the evaluation:
sixty documents of the test split are queued at start and behave exactly as measured.
The checks take 1 July 2026 for today, the date the samples were recorded for. Any
other document fails as "model unavailable".

The console is at http://127.0.0.1:8000.

### With local models

[Ollama](https://ollama.com) running on the same machine, with the two models pulled:

```bash
ollama pull qwen3.5:4b
ollama pull qwen3.5:9b
uv run countersign serve
```

Both models loaded with a 16k context take about 10 GB of video memory. `/readyz`
answers 503 until the server is reachable and both models are installed.

### In a container

```bash
docker compose --profile demo up --build     # recorded answers, samples queued
docker compose --profile live up --build     # Ollama on the host
```

The port is published on the host's loopback address only. On Linux the Ollama server
of the host has to listen on the Docker bridge (`OLLAMA_HOST=0.0.0.0`) for the `live`
profile to reach it.

## Commands

| Command | Does |
|---|---|
| `countersign serve [--host H] [--port P] [--no-workers]` | API, console and workers |
| `countersign demo [--host H] [--port P] [--limit 60]` | the same on recorded answers, with samples of the test split queued |
| `countersign worker` | a worker alone; stops after the current document on SIGTERM |
| `countersign submit FILE...` | queue PDF files |
| `countersign samples [--split test] [--limit 40]` | queue documents of the dataset |
| `countersign migrate` | bring the database to the current schema (the application does it at start-up) |
| `python -m countersign.eval.run --split test --config cascade [--replay]` | evaluate |
| `python -m countersign.eval.gate` | recompute every committed report |
| `python -m countersign.eval.compare --split confirm` | the tables of the documentation |
| `python -m countersign.datagen.build` | rebuild the dataset |

## Configuration

Environment variables, prefix `COUNTERSIGN_`, or a `.env` file. A value that does not
validate stops the application at start-up, with the name of the setting and without
its value.

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///var/countersign.db` | SQLAlchemy URL |
| `STORAGE_DIR` | `var/documents` | received files, named by content hash |
| `EXPORT_DIR` | `var/export` | one JSON file per approved document |
| `REFERENCE_DIR` | `data/reference` | company, vendors, purchase orders |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | model server |
| `SMALL_MODEL`, `LARGE_MODEL` | `qwen3.5:4b`, `qwen3.5:9b` | first and second tier |
| `MODEL_TIMEOUT_S` | `240` | per try of a model call |
| `MODEL_RETRIES` | `2` | tries after the first one, when the model server answers an error |
| `REPLAY_DIR` | unset | answer from recorded cassettes instead of a server |
| `TODAY` | unset | the date the checks take for today; unset, the real date |
| `WORKERS` | `1` | worker threads in `serve` |
| `POLL_INTERVAL_S` | `1` | pause of an idle worker between two looks at the queue |
| `JOB_LEASE_S` | `300` | the least time a claimed job is protected (see below) |
| `JOB_MAX_ATTEMPTS` | `3` | before a job is parked as failed |
| `JOB_BACKOFF_S` | `5` | first retry delay, doubled each time |
| `API_KEYS` | unset | `name:role:key,...`; roles `operator` and `reviewer` |
| `ALLOW_OPEN` | `false` | accept to serve without keys on an address other than the loopback |
| `MAX_UPLOAD_BYTES` | 15 MB | per file |
| `OTLP_ENDPOINT` | unset | export traces over OTLP/HTTP (needs the `otlp` extra) |
| `LOG_LEVEL` | `INFO` | |

Without `API_KEYS` the API is open, and `serve` refuses any address but the loopback
unless `ALLOW_OPEN` is set. A key entry that is not exactly `name:role:key` is an
error, not an entry that is skipped.

The lease of a job is not renewed, so it is never shorter than the slowest document:
`tiers × (MODEL_RETRIES + 1) × MODEL_TIMEOUT_S`, plus the pauses between tries and a
margin of a minute. That is 1 512 s with the defaults; `JOB_LEASE_S` only matters when
it is longer.

## Signals

### Probes

- `GET /healthz`: the process answers.
- `GET /readyz`: the database answers and both models are installed. 503 otherwise,
  with the detail in the body.

### Metrics (`GET /metrics`, Prometheus)

| Metric | Labels | Read it for |
|---|---|---|
| `countersign_documents_total` | `outcome`, `mode` | share approved without a person; scans versus text |
| `countersign_extraction_attempts_total` | `tier`, `result` | how often the second tier is needed; model failures |
| `countersign_check_failures_total` | `family` | why documents are stopped |
| `countersign_model_seconds` | `tier` | latency of each tier |
| `countersign_document_model_seconds` | | model time per document, all tiers |
| `countersign_tokens_total` | `tier`, `direction` | load on the model server |
| `countersign_job_failures_total` | `final` | retries, and jobs that were given up |
| `countersign_jobs` | `status` | queue depth |
| `countersign_documents` | `status` | review backlog, failed documents |

Counters live in the process that does the work: with separate worker processes,
scrape each. The two gauges are read from the database at scrape time and are right
wherever they are scraped.

### Traces

One trace per document: `countersign.process` with a child span for parsing, each
extraction and each verification. Model spans follow the OpenTelemetry GenAI
conventions (`gen_ai.request.model`, `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`). Attributes carry sizes, outcomes and check names, never
invoice content; a test enforces it.

### Logs

One JSON object per line on standard error. `document_processed` carries the document
id, the outcome, the reasons, the tiers used and the model seconds; `request` carries
the method, the path, the status and the time of each API call. Logs carry no supplier
name, amount or account number, and a database error is logged without the values of
its statement.

## What to watch

| Signal | Likely cause | Action |
|---|---|---|
| `countersign_jobs{status="queued"}` grows | model server slow or down; more documents than one GPU reads | check `/readyz`; add a worker only if the model server has spare capacity |
| `countersign_documents{status="failed"}` above zero | a model was unreachable for three attempts in a row; a result the database refused | restore the model server, then "Read it again" in the console or `POST /api/documents/{id}/reprocess` |
| share of `outcome="review"` rises | a new supplier layout; a model or prompt change; master data out of date | look at `countersign_check_failures_total` by family |
| `family="bank_details"` rises for one supplier | the supplier changed bank, or someone is impersonating it | confirm with the supplier through a known contact, then update the vendor master |
| `family="grounding"` or `"arithmetic"` rises across suppliers | the model reads worse: different model build, context too small | run the evaluation against the live server |
| `result="error"` on a tier | truncated output on long documents; model missing | raise `max_output_tokens`; `ollama list` |

## Failure modes

| Failure | What happens | What is lost |
|---|---|---|
| Worker dies during a model call | the lease expires (about 25 minutes with the defaults), another worker takes the job | one model call, and the wait |
| Worker dies after the model call, before writing | same; the document is read again | one model call, and the wait |
| Two workers finish the same job | the one that lost its lease writes nothing | nothing |
| Model server down, for both models or for one | the job fails, backs off, and is parked after three attempts; nothing is sent to review for that reason | nothing; documents wait as failed |
| A result the database refuses | the job fails at once with its own error, and is not tried again | nothing; the document shows as failed |
| Database unavailable | uploads fail with an error; workers log and retry their loop | nothing |
| Disk full in the export directory | the approval is committed, its outbox row stays pending and is delivered later | nothing |
| Crash between an approval and its export file | same: the file is written from the outbox, after the commit | nothing |
| The same invoice arrives twice at once | the unique index lets one approval through | nothing |
| Two reviewers decide the same document at once | the second gets 409 | nothing |

## Behaviour worth knowing

- `page_count` is 0 until a worker has read the file: an upload is stored without
  being opened.
- An approval despite failed checks must carry a comment and the ids of the checks it
  overrides (`acknowledged`). The console sends them; a client that sends a comment
  alone gets 409 with the list.
- A JSON body over 1 MB, an upload over `MAX_UPLOAD_BYTES`, a document id beyond
  2³¹ − 1 are refused (413, 413, 422) before anything is read or looked up.
- Behind a reverse proxy the original `Host` header must be passed on: a request that
  changes something is refused when its `Origin` is not the host it is sent to.

## After changing the prompt, a model or a check

```bash
uv run python -m countersign.eval.run --split dev --config cascade      # needs the GPU
uv run python -m countersign.eval.gate                                  # needs nothing
```

A prompt or model change invalidates the recorded answers of the affected
configuration: the gate fails until the evaluation has been run again and its reports
committed. A change to a check or to the parser needs no GPU: the reports are
recomputed from the recordings, and the diff of the report shows which documents moved.

A change to how scanned pages are drawn (`render_pages`) is not seen by the gate on its
own: the recordings of scans are keyed by file, resolution and the name `RASTER` in
`parsing/pdf.py`. Change that name with the drawing, and record the scans again.
