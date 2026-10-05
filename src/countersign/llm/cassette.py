"""Record model answers once, replay them anywhere.

An evaluation over hundreds of documents takes an hour of GPU time; the code around the
model (parsing, checks, decisions) changes far more often than the model's answers. A
cassette stores each answer under the hash of its request, so the full evaluation can
be re-run in seconds, on a machine without a GPU, and give the same numbers.

Changing the prompt, the schema, the model or the text sent changes the hash: stale
answers are never replayed, they are simply missing, and a replay fails loudly. The
size of the context window is not in the hash; the guard that refuses a request too
long for it runs before the tape is read, in a replay as in a live call.

A cassette is a directory with one JSON Lines file per model. Entries are appended as
calls complete, so an interrupted run resumes where it stopped.
"""

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from countersign.llm.client import (
    ErrorKind,
    ModelClient,
    ModelError,
    ModelRequest,
    ModelResponse,
    ensure_fits,
)

Mode = Literal["replay", "auto", "record"]

# Failures that depend on the request alone and would happen again: worth replaying.
_DETERMINISTIC_ERRORS: frozenset[ErrorKind] = frozenset({"too_long", "truncated_output"})


class CassetteMiss(Exception):
    """Replay was asked for a request that was never recorded."""


def _file_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model) + ".jsonl"


class Cassette:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._tapes: dict[str, dict[str, dict[str, Any]]] = {}
        self.used: set[str] = set()

    def _tape(self, model: str) -> dict[str, dict[str, Any]]:
        if model not in self._tapes:
            entries: dict[str, dict[str, Any]] = {}
            path = self.directory / _file_name(model)
            if path.exists():
                with path.open(encoding="utf-8") as handle:
                    for line in handle:
                        if line.strip():
                            entry = json.loads(line)
                            entries[entry["key"]] = entry
            self._tapes[model] = entries
        return self._tapes[model]

    def get(self, model: str, key: str) -> dict[str, Any] | None:
        entry = self._tape(model).get(key)
        if entry is not None:
            self.used.add(key)
        return entry

    def put(self, model: str, entry: dict[str, Any]) -> None:
        self._tape(model)[entry["key"]] = entry
        self.used.add(entry["key"])
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / _file_name(model)).open(
            "a", encoding="utf-8", newline="\n"
        ) as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

    def prune(self) -> int:
        """Keep only the entries used since loading; return how many were dropped.

        Files are rewritten sorted, so that recording the same answers twice gives the
        same bytes.
        """
        dropped = 0
        for path in sorted(self.directory.glob("*.jsonl")):
            entries = {}
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        entry = json.loads(line)
                        entries[entry["key"]] = entry
            kept = [entry for key, entry in entries.items() if key in self.used]
            dropped += len(entries) - len(kept)
            kept.sort(key=lambda entry: (entry.get("label", ""), entry["key"]))
            lines = [json.dumps(entry, ensure_ascii=False, sort_keys=True) for entry in kept]
            if lines:
                path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
            else:
                path.unlink()
        self._tapes.clear()
        return dropped


class RecordingClient:
    """A `ModelClient` that answers from a cassette and records what it has to ask.

    - "replay": cassette only; an unknown request raises `CassetteMiss`.
    - "auto":   cassette first, the wrapped client for what is missing.
    - "record": always the wrapped client; earlier answers are superseded.
    """

    def __init__(self, cassette: Cassette, inner: ModelClient | None, mode: Mode = "auto") -> None:
        if mode != "replay" and inner is None:
            raise ValueError(f"mode {mode!r} needs a model client to record from")
        self.cassette = cassette
        self._inner = inner
        self._mode = mode
        self.hits = 0
        self.calls = 0

    def generate(self, request: ModelRequest) -> ModelResponse:
        # The context size is not part of the key: without this, a replay would answer
        # for a request that no longer fits and that the model server would never see.
        ensure_fits(request)
        key = request.key()
        if self._mode != "record":
            entry = self.cassette.get(request.model, key)
            if entry is not None:
                self.hits += 1
                return _replay(entry)
        if self._inner is None or self._mode == "replay":
            raise CassetteMiss(
                f"no recorded answer for {request.label or key[:12]} ({request.model})"
            )
        self.calls += 1
        base = {"key": key, "label": request.label}
        try:
            response = self._inner.generate(request)
        except ModelError as error:
            if error.kind in _DETERMINISTIC_ERRORS:
                failure = {"kind": error.kind, "message": error.message}
                self.cassette.put(request.model, {**base, "error": failure})
            raise
        self.cassette.put(request.model, {**base, "response": asdict(response)})
        return response


def _replay(entry: dict[str, Any]) -> ModelResponse:
    if "error" in entry:
        raise ModelError(entry["error"]["kind"], entry["error"].get("message", ""))
    return ModelResponse(**entry["response"])


class ReplayClient:
    """Replay for the application: an unknown request is a model that cannot answer.

    The evaluation wants a miss to stop the run. The application, started without a GPU
    on recorded answers, wants the document to fail like any other outage.
    """

    def __init__(self, directory: Path) -> None:
        self._inner = RecordingClient(Cassette(directory), None, "replay")

    def generate(self, request: ModelRequest) -> ModelResponse:
        try:
            return self._inner.generate(request)
        except CassetteMiss as miss:
            raise ModelError("unavailable", str(miss)) from None
