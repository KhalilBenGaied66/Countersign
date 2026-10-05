"""One call to a model server: a document in, a JSON string out, with usage numbers.

The pipeline depends on the `ModelClient` protocol only. `OllamaClient` implements it
for a local Ollama server; `countersign.llm.cassette` wraps any client to record its
answers and replay them later without a GPU.

Three failures are specific to local inference and are turned into `ModelError` here
instead of being left to corrupt a result silently:

- the server truncates a prompt longer than the context window without saying so, so
  the size is estimated before the call and the prompt size the server reports, when
  it reports one, is checked after it;
- generation stops at the output limit in the middle of a JSON document;
- the server is still loading the model, or is not running at all.
"""

import base64
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

ErrorKind = Literal[
    "unavailable",  # server unreachable or model missing: retry later
    "timeout",
    "too_long",  # the document does not fit the context window
    "truncated_output",  # generation hit the output limit
    "bad_response",  # the server answered something that is not a chat response
]

# Upper bounds used only to refuse a document before sending it. Measured on the dev
# split: laid-out invoice text costs about 0.25 token per character, and an A4 page
# rendered at 200 DPI about 4,000 tokens.
_TOKENS_PER_CHARACTER = 0.4
_TOKENS_PER_IMAGE = 4400
_PROMPT_OVERHEAD_TOKENS = 64

DEFAULT_RETRIES = 2
_LONGEST_PAUSE_S = 10.0


class ModelError(Exception):
    def __init__(self, kind: ErrorKind, message: str = "") -> None:
        super().__init__(f"{kind}: {message}" if message else kind)
        self.kind: ErrorKind = kind
        self.message = message


def _pause_before(attempt: int) -> float:
    return min(2.0**attempt, _LONGEST_PAUSE_S)


def worst_case_seconds(timeout_s: float, max_retries: int = DEFAULT_RETRIES) -> float:
    """The longest one call can last: every try answers an error just before the timeout.

    The lease of a job is derived from it, so that a worker still waiting for a model
    is never taken for a dead one.
    """
    pauses = sum(_pause_before(attempt) for attempt in range(1, max_retries + 1))
    return (max_retries + 1) * timeout_s + pauses


@dataclass(frozen=True)
class ModelRequest:
    model: str
    system: str
    user: str
    images: tuple[bytes, ...] = ()
    # Where the images come from, for example "<sha256 of the file>@200dpi:1". When set
    # it stands for the images in the key: a page rasterises to slightly different bytes
    # on another platform, and an answer recorded here must replay there.
    image_source: str = ""
    schema: dict[str, Any] | None = None
    think: bool = False
    max_output_tokens: int = 6000
    context_tokens: int = 16384
    seed: int = 7
    # Free-form label for logs and cassettes ("T-014", a document id); not sent.
    label: str = field(default="", compare=False)

    def key(self) -> str:
        """Identity of the request: two requests with the same key get the same answer.

        The context size is left out: it changes whether a request fits, not its answer.
        """
        identity = {
            "model": self.model,
            "system": self.system,
            "user": self.user,
            "images": self.image_source
            or [hashlib.sha256(image).hexdigest() for image in self.images],
            "schema": self.schema,
            "think": self.think,
            "max_output_tokens": self.max_output_tokens,
            "seed": self.seed,
        }
        canonical = json.dumps(identity, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def estimated_prompt_tokens(self) -> int:
        characters = len(self.system) + len(self.user)
        return (
            int(characters * _TOKENS_PER_CHARACTER)
            + len(self.images) * _TOKENS_PER_IMAGE
            + _PROMPT_OVERHEAD_TOKENS
        )


@dataclass(frozen=True)
class ModelResponse:
    content: str
    model: str
    prompt_tokens: int
    output_tokens: int
    # Wall-clock seconds of the call, and the part the server spent loading the model.
    duration_s: float
    load_s: float = 0.0
    done_reason: str = "stop"


class ModelClient(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse: ...


def ensure_fits(request: ModelRequest) -> None:
    """Refuse a request that cannot fit the context window, before anything is sent.

    Every client calls it, the one that replays recordings included: an answer on tape
    must not stand in for a request the live system would refuse.
    """
    needed = request.estimated_prompt_tokens() + request.max_output_tokens
    if needed > request.context_tokens:
        raise ModelError(
            "too_long", f"about {needed} tokens for a window of {request.context_tokens}"
        )


def _count(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ModelError("bad_response", f"{key} is not a number")
    return int(value)


class OllamaClient:
    """Chat completion against Ollama's native API, with constrained JSON output."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        *,
        timeout_s: float = 240.0,
        max_retries: int = DEFAULT_RETRIES,
        keep_alive: str = "10m",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_s, connect=5.0),
            transport=transport,
        )
        self._max_retries = max_retries
        self._keep_alive = keep_alive

    def close(self) -> None:
        self._http.close()

    def is_ready(self, model: str) -> bool:
        """Whether the server answers and has `model` installed."""
        try:
            response = self._http.get("/api/tags", timeout=3.0)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return False
        entries = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return False
        installed = {entry.get("name") for entry in entries if isinstance(entry, dict)}
        # The server lists "name:tag"; a model named without a tag is its "latest".
        return (model if ":" in model else f"{model}:latest") in installed

    def generate(self, request: ModelRequest) -> ModelResponse:
        ensure_fits(request)

        message: dict[str, Any] = {"role": "user", "content": request.user}
        if request.images:
            message["images"] = [
                base64.b64encode(image).decode("ascii") for image in request.images
            ]
        body: dict[str, Any] = {
            "model": request.model,
            "stream": False,
            "think": request.think,
            "keep_alive": self._keep_alive,
            "messages": [{"role": "system", "content": request.system}, message],
            "options": {
                "temperature": 0,
                "seed": request.seed,
                "num_ctx": request.context_tokens,
                "num_predict": request.max_output_tokens,
            },
        }
        if request.schema is not None:
            body["format"] = request.schema

        started = time.perf_counter()
        payload = self._post(body)
        duration_s = time.perf_counter() - started

        answer = payload.get("message")
        content = answer.get("content") if isinstance(answer, dict) else None
        if not isinstance(content, str):
            raise ModelError("bad_response", "no message content")
        done_reason = str(payload.get("done_reason") or "")
        prompt_tokens = _count(payload, "prompt_eval_count")
        output_tokens = _count(payload, "eval_count")
        # A server that gives no reason for stopping, and stopped at the limit, was cut.
        cut = not done_reason and output_tokens >= request.max_output_tokens
        if done_reason == "length" or cut:
            raise ModelError("truncated_output", f"stopped after {output_tokens} tokens")
        # A server that leaves the prompt size out gives nothing to check here: only the
        # estimate made before the call then stands between a long prompt and the window.
        if prompt_tokens + output_tokens >= request.context_tokens:
            raise ModelError("too_long", "the context window was filled")
        return ModelResponse(
            content=content,
            model=request.model,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            duration_s=round(duration_s, 3),
            load_s=round(_count(payload, "load_duration") / 1e9, 3),
            done_reason=done_reason,
        )

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        last: ModelError = ModelError("unavailable")
        for attempt in range(self._max_retries + 1):
            if attempt:
                time.sleep(_pause_before(attempt))
            try:
                response = self._http.post("/api/chat", json=body)
            except httpx.TimeoutException:
                # A generation that ran out of time will run out of time again.
                raise ModelError("timeout") from None
            except httpx.TransportError as error:
                last = ModelError("unavailable", type(error).__name__)
                continue
            if response.status_code >= 500:
                last = ModelError("unavailable", f"HTTP {response.status_code}")
                continue
            if response.status_code == 404:
                raise ModelError("unavailable", f"model {body['model']} is not installed")
            if response.status_code >= 400:
                raise ModelError("bad_response", f"HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError:
                raise ModelError("bad_response", "not JSON") from None
            if not isinstance(payload, dict):
                raise ModelError("bad_response", "not a JSON object")
            return payload
        raise last
