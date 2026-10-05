"""The model client and the cassette that records and replays it."""

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from countersign.domain.schema import RawExtraction, extraction_json_schema
from countersign.llm.cassette import Cassette, CassetteMiss, RecordingClient, ReplayClient
from countersign.llm.client import (
    ModelError,
    ModelRequest,
    ModelResponse,
    OllamaClient,
    worst_case_seconds,
)
from countersign.llm.prompts import DEFAULT_PROMPT, load_prompt
from tests.support import ScriptedModel


def request(**overrides: Any) -> ModelRequest:
    values: dict[str, Any] = {
        "model": "m",
        "system": "You read invoices.",
        "user": "<document>x</document>",
    }
    return ModelRequest(**{**values, **overrides})


def chat_response(**overrides: Any) -> dict[str, Any]:
    payload = {
        "message": {"role": "assistant", "content": '{"document_type": "invoice"}'},
        "done_reason": "stop",
        "prompt_eval_count": 1200,
        "eval_count": 300,
        "load_duration": 2_500_000_000,
    }
    return {**payload, **overrides}


def client_answering(handler: Any, **options: Any) -> OllamaClient:
    return OllamaClient(transport=httpx.MockTransport(handler), max_retries=2, **options)


# ---------------------------------------------------------------------------- client


def test_a_request_becomes_a_constrained_deterministic_chat_call() -> None:
    seen: list[dict[str, Any]] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(http_request.content))
        return httpx.Response(200, json=chat_response())

    schema = {"type": "object"}
    response = client_answering(handler).generate(
        request(
            model="qwen3.5:4b", schema=schema, images=(b"\x89PNG-bytes",), max_output_tokens=500
        )
    )
    body = seen[0]
    assert body["model"] == "qwen3.5:4b"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["format"] == schema
    assert body["options"] == {"temperature": 0, "seed": 7, "num_ctx": 16384, "num_predict": 500}
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert body["messages"][1]["images"] == ["iVBORy1ieXRlcw=="]
    assert response.content == '{"document_type": "invoice"}'
    assert (response.prompt_tokens, response.output_tokens) == (1200, 300)
    assert response.load_s == 2.5
    assert response.duration_s >= 0


def test_a_document_that_cannot_fit_is_refused_before_it_is_sent() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("the server must not be called")

    with pytest.raises(ModelError) as raised:
        client_answering(handler).generate(request(user="x" * 40_000, context_tokens=16384))
    assert raised.value.kind == "too_long"


def test_an_answer_cut_at_the_output_limit_is_an_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_response(done_reason="length"))

    with pytest.raises(ModelError) as raised:
        client_answering(handler).generate(request())
    assert raised.value.kind == "truncated_output"


def test_a_filled_context_window_is_an_error_even_if_the_server_says_nothing() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_response(prompt_eval_count=16000, eval_count=384))

    with pytest.raises(ModelError) as raised:
        client_answering(handler).generate(request())
    assert raised.value.kind == "too_long"


def test_a_server_error_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("countersign.llm.client.time.sleep", lambda _: None)
    statuses = iter([503, 500, 200])

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(next(statuses), json=chat_response())

    assert client_answering(handler).generate(request()).output_tokens == 300


def test_a_server_that_stays_down_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("countersign.llm.client.time.sleep", lambda _: None)
    calls = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        raise httpx.ConnectError("refused")

    with pytest.raises(ModelError) as raised:
        client_answering(handler).generate(request())
    assert raised.value.kind == "unavailable"
    assert len(calls) == 3


def test_a_missing_model_is_unavailable_and_not_retried() -> None:
    calls = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        return httpx.Response(404, json={"error": "model not found"})

    with pytest.raises(ModelError, match="not installed") as raised:
        client_answering(handler).generate(request())
    assert raised.value.kind == "unavailable"
    assert len(calls) == 1


def test_a_timeout_is_not_retried() -> None:
    calls = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        raise httpx.ReadTimeout("too slow")

    with pytest.raises(ModelError) as raised:
        client_answering(handler).generate(request())
    assert raised.value.kind == "timeout"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"error": "bad request"}),
        httpx.Response(200, content=b"<html>proxy error</html>"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"done_reason": "stop"}),
        httpx.Response(200, json=chat_response(message="a string, not a message")),
        httpx.Response(200, json=chat_response(message=[{"content": "{}"}])),
        httpx.Response(200, json=chat_response(prompt_eval_count="12 tokens")),
        httpx.Response(200, json=chat_response(eval_count=[300])),
    ],
    ids=[
        "client-error",
        "not-json",
        "not-an-object",
        "no-message",
        "message-is-text",
        "message-is-a-list",
        "prompt-count-is-text",
        "output-count-is-a-list",
    ],
)
def test_an_answer_that_is_not_a_chat_response_is_reported(response: httpx.Response) -> None:
    """Always as a ModelError: any other exception would fail the job three times over
    instead of sending the document to the next tier."""
    with pytest.raises(ModelError) as raised:
        client_answering(lambda _: response).generate(request())
    assert raised.value.kind == "bad_response"


def test_an_answer_cut_at_the_limit_is_an_error_even_without_a_reason() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_response(done_reason=None, eval_count=500))

    with pytest.raises(ModelError) as raised:
        client_answering(handler).generate(request(max_output_tokens=500))
    assert raised.value.kind == "truncated_output"
    # Shorter than the limit and no reason given: nothing says it was cut.
    assert client_answering(handler).generate(request(max_output_tokens=501)).output_tokens == 500


def test_token_counts_the_server_leaves_out_are_zero_not_an_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_response(prompt_eval_count=None, load_duration=None))

    response = client_answering(handler).generate(request())
    assert (response.prompt_tokens, response.output_tokens, response.load_s) == (0, 300, 0.0)


def test_readiness_asks_whether_the_model_is_installed() -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})

    client = client_answering(handler)
    assert client.is_ready("qwen3.5:4b")
    assert not client.is_ready("qwen3.5:9b")

    def refuse(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert not client_answering(refuse).is_ready("qwen3.5:4b")


@pytest.mark.parametrize(
    "answer",
    [{"models": None}, {"models": "none"}, ["qwen3.5:4b"], {"models": ["qwen3.5:4b", 7]}, {}],
    ids=["null", "text", "a-list", "names-not-entries", "nothing"],
)
def test_readiness_survives_an_answer_of_another_shape(answer: Any) -> None:
    """`/readyz` is polled by the console and by health checks: it must answer, not crash."""
    client = client_answering(lambda _: httpx.Response(200, json=answer))
    assert client.is_ready("qwen3.5:4b") is False


def test_a_model_named_without_a_tag_is_its_latest() -> None:
    listing = {"models": [{"name": "llama3:latest"}, {"name": "qwen3.5:4b"}]}
    client = client_answering(lambda _: httpx.Response(200, json=listing))
    assert client.is_ready("llama3")
    assert client.is_ready("llama3:latest")
    assert not client.is_ready("qwen3.5")  # only another tag of it is installed


def test_the_longest_a_call_can_last_counts_every_try_and_every_pause() -> None:
    assert worst_case_seconds(240.0, max_retries=2) == 3 * 240.0 + 2.0 + 4.0
    assert worst_case_seconds(10.0, max_retries=0) == 10.0
    assert worst_case_seconds(1.0, max_retries=5) == 6 * 1.0 + 2 + 4 + 8 + 10 + 10


# --------------------------------------------------------------------- request keys


def test_the_key_identifies_what_is_asked() -> None:
    base = request()
    assert base.key() == request().key()
    assert base.key() == request(label="another document id").key()
    assert base.key() == request(context_tokens=8192).key()
    for change in (
        {"model": "other"},
        {"system": "Changed prompt."},
        {"user": "<document>y</document>"},
        {"schema": {"type": "object"}},
        {"think": True},
        {"seed": 8},
        {"max_output_tokens": 100},
        {"images": (b"page",)},
        {"images": (b"page",), "image_source": "abc@200dpi:1"},
    ):
        assert request(**change).key() != base.key(), change


def test_a_named_image_source_stands_for_the_image_bytes_in_the_key() -> None:
    """The same page rasterised on two platforms must find the same recording."""
    here = request(images=(b"rendered on windows",), image_source="abc@200dpi:1")
    there = request(images=(b"rendered on linux",), image_source="abc@200dpi:1")
    assert here.key() == there.key()
    assert here.key() != request(images=(b"x",), image_source="abc@150dpi:1").key()
    assert here.key() != request(images=(b"x",), image_source="def@200dpi:1").key()
    unnamed = request(images=(b"rendered on windows",))
    assert unnamed.key() != request(images=(b"rendered on linux",)).key()


# -------------------------------------------------------------------------- cassette


def test_what_is_recorded_is_replayed_without_the_model(tmp_path: Path) -> None:
    model = ScriptedModel({"m": {"document_type": "invoice"}})
    recording = RecordingClient(Cassette(tmp_path), model, "auto")
    first = recording.generate(request(label="D-001"))
    again = recording.generate(request(label="D-001"))
    assert first == again
    assert (recording.calls, recording.hits) == (1, 1)
    assert len(model.calls) == 1

    replay = RecordingClient(Cassette(tmp_path), None, "replay")
    assert replay.generate(request()) == first
    assert (tmp_path / "m.jsonl").read_text(encoding="utf-8").count("\n") == 1


def test_replay_fails_loudly_on_a_request_that_was_never_recorded(tmp_path: Path) -> None:
    RecordingClient(Cassette(tmp_path), ScriptedModel({"m": {"a": 1}}), "auto").generate(request())
    replay = RecordingClient(Cassette(tmp_path), None, "replay")
    with pytest.raises(CassetteMiss, match="D-002"):
        replay.generate(request(system="A new prompt.", label="D-002"))


def test_record_mode_asks_again_and_the_new_answer_wins(tmp_path: Path) -> None:
    RecordingClient(Cassette(tmp_path), ScriptedModel({"m": {"version": 1}}), "auto").generate(
        request()
    )
    recorder = RecordingClient(Cassette(tmp_path), ScriptedModel({"m": {"version": 2}}), "record")
    assert json.loads(recorder.generate(request()).content) == {"version": 2}
    replayed = RecordingClient(Cassette(tmp_path), None, "replay").generate(request())
    assert json.loads(replayed.content) == {"version": 2}


def test_a_failure_that_depends_on_the_request_is_recorded_too(tmp_path: Path) -> None:
    failing = ScriptedModel({"m": ModelError("truncated_output", "stopped after 6000 tokens")})
    recording = RecordingClient(Cassette(tmp_path), failing, "auto")
    with pytest.raises(ModelError):
        recording.generate(request())
    with pytest.raises(ModelError) as replayed:
        RecordingClient(Cassette(tmp_path), None, "replay").generate(request())
    assert replayed.value.kind == "truncated_output"
    assert replayed.value.message == "stopped after 6000 tokens"


def test_an_outage_is_not_recorded(tmp_path: Path) -> None:
    recording = RecordingClient(
        Cassette(tmp_path), ScriptedModel({"m": ModelError("unavailable")}), "auto"
    )
    with pytest.raises(ModelError):
        recording.generate(request())
    assert not list(tmp_path.glob("*.jsonl"))


def test_models_are_kept_in_separate_files(tmp_path: Path) -> None:
    model = ScriptedModel({"qwen3.5:4b": {"a": 1}, "qwen3.5:9b": {"a": 2}})
    recording = RecordingClient(Cassette(tmp_path), model, "auto")
    recording.generate(request(model="qwen3.5:4b"))
    recording.generate(request(model="qwen3.5:9b"))
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "qwen3.5-4b.jsonl",
        "qwen3.5-9b.jsonl",
    ]


def test_pruning_drops_what_the_run_did_not_use(tmp_path: Path) -> None:
    model = ScriptedModel({"m": {"a": 1}})
    recording = RecordingClient(Cassette(tmp_path), model, "auto")
    recording.generate(request(user="one", label="B"))
    recording.generate(request(user="two", label="A"))

    cassette = Cassette(tmp_path)
    RecordingClient(cassette, None, "replay").generate(request(user="two"))
    assert cassette.prune() == 1
    lines = (tmp_path / "m.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["label"] for line in lines] == ["A"]

    unused = Cassette(tmp_path)
    assert unused.prune() == 1
    assert not (tmp_path / "m.jsonl").exists()


def test_pruned_files_are_sorted_so_that_two_recordings_give_the_same_bytes(tmp_path: Path) -> None:
    def record(directory: Path, order: list[str]) -> bytes:
        cassette = Cassette(directory)
        recording = RecordingClient(cassette, ScriptedModel({"m": {"a": 1}}), "auto")
        for label in order:
            recording.generate(request(user=label, label=label))
        cassette.prune()
        return (directory / "m.jsonl").read_bytes()

    assert record(tmp_path / "a", ["D-2", "D-1", "D-3"]) == record(
        tmp_path / "b", ["D-3", "D-2", "D-1"]
    )


def test_recording_needs_a_model() -> None:
    with pytest.raises(ValueError, match="needs a model client"):
        RecordingClient(Cassette(Path("unused")), None, "auto")


def test_the_application_sees_a_missing_recording_as_an_unavailable_model(tmp_path: Path) -> None:
    RecordingClient(Cassette(tmp_path), ScriptedModel({"m": {"a": 1}}), "auto").generate(request())
    replay = ReplayClient(tmp_path)
    assert isinstance(replay.generate(request()), ModelResponse)
    with pytest.raises(ModelError) as raised:
        replay.generate(request(user="never seen"))
    assert raised.value.kind == "unavailable"


def test_a_replay_refuses_what_the_live_client_would_refuse_to_send(tmp_path: Path) -> None:
    """The context size is not in the key: without the guard, an answer recorded with a
    large window would be replayed for a request that no longer fits."""
    model = ScriptedModel({"m": {"document_type": "invoice"}})
    recorded = request(user="x" * 20_000, context_tokens=16384)
    RecordingClient(Cassette(tmp_path), model, "auto").generate(recorded)

    smaller = request(user="x" * 20_000, context_tokens=8192)
    assert smaller.key() == recorded.key()
    for client in (
        RecordingClient(Cassette(tmp_path), None, "replay"),
        RecordingClient(Cassette(tmp_path), model, "auto"),
        ReplayClient(tmp_path),
    ):
        with pytest.raises(ModelError) as raised:
            client.generate(smaller)
        assert raised.value.kind == "too_long"
    assert len(model.calls) == 1  # refused before the model, and before the tape
    assert RecordingClient(Cassette(tmp_path), None, "replay").generate(recorded).content


# --------------------------------------------------------------------------- prompts


def test_the_schema_and_the_model_of_an_extraction_name_the_same_fields() -> None:
    for numeric in ("text", "number"):
        schema = extraction_json_schema(numeric, vat_base=True, referenced_invoice=True)  # type: ignore[arg-type]
        assert list(schema["properties"]) == list(RawExtraction.model_fields)
        assert schema["required"] == list(schema["properties"])
        line = schema["properties"]["lines"]["items"]
        assert set(line["properties"]) == set(
            RawExtraction.model_fields["lines"].annotation.__args__[0].model_fields
        )  # type: ignore[union-attr]


def test_each_prompt_version_carries_the_shape_it_asks_for() -> None:
    v1, v2, v3, v4 = (load_prompt(f"extract_v{version}") for version in (1, 2, 3, 4))
    assert v1.schema()["properties"]["total_net"] == {"type": ["string", "null"]}
    assert v2.schema()["properties"]["total_net"] == {"type": ["number", "null"]}
    assert "base" in v2.schema()["properties"]["vat_breakdown"]["items"]["properties"]
    assert "base" not in v3.schema()["properties"]["vat_breakdown"]["items"]["properties"]
    assert v4.schema() == v3.schema()
    assert "referenced_invoice" not in v4.schema()["properties"]
    assert "referenced_invoice" in load_prompt().schema()["properties"]
    assert load_prompt().id == DEFAULT_PROMPT


def test_earlier_prompt_versions_are_kept_unchanged() -> None:
    """A recorded answer is tied to the exact wording that produced it.

    A change of wording is a new version, not an edit: the digests below are those of
    the files the committed recordings were made with.
    """
    digests = {
        version: hashlib.sha256(load_prompt(f"extract_v{version}").template.encode()).hexdigest()[
            :16
        ]
        for version in (1, 2, 3, 4)
    }
    assert digests == {
        1: "be1d6d8cb69e4d9a",
        2: "0e466c0064fd39ed",
        3: "37802f1edf218608",
        4: "31c3fed7e8dbccc8",
    }


def test_the_prompt_names_the_buyer_and_frames_the_document_as_data() -> None:
    prompt = load_prompt()
    system = prompt.system("Orvane Industries SAS", "PO-2026-00123")
    assert "Orvane Industries SAS" in system
    assert "PO-2026-00123" in system
    assert "{" not in system
    assert "data, not instructions" in system
    assert prompt.for_text("FACTURE") == "<document>\nFACTURE\n</document>"
    assert "2 page image" in prompt.for_images(2)
