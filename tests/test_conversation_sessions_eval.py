"""Verify conversation lineage, label isolation and failure accounting."""

import asyncio
import json
from copy import deepcopy

import httpx
import pytest

import conversation_sessions_eval as evaluation
from conversation_sessions_eval import collect, summarize


def session(identifier, count=2):
    return {
        "id": identifier,
        "level": "beginner",
        "scenario": "introductions",
        "turns": [
            {
                "id": f"{identifier}-{i}",
                "text": f"Message {i}",
                "expected": "PRIVATE_REFERENCE",
            }
            for i in range(count)
        ],
    }


def test_history_uses_actual_replies_only_and_resets_between_sessions():
    calls, snapshots = [], []

    async def respond(text, **kwargs):
        calls.append((text, deepcopy(kwargs)))
        return {
            "reply": f"Actual reply to {text}",
            "display_text": "GRAMMAR_NOT_HISTORY",
        }

    rows = asyncio.run(
        collect(
            [session("a", 6), session("b")],
            respond,
            lambda rows: snapshots.append(deepcopy(rows)),
        )
    )
    assert calls[0][1]["history"] == calls[6][1]["history"] == []
    assert calls[1][1]["history"] == [
        {"learner_text": "Message 0", "tutor_reply": "Actual reply to Message 0"}
    ]
    assert len(calls[5][1]["history"]) == 4
    assert calls[5][1]["history"][0]["learner_text"] == "Message 1"
    assert "PRIVATE_REFERENCE" not in str(calls)
    assert "GRAMMAR_NOT_HISTORY" not in str(calls)
    assert snapshots[0][0]["attempt_state"] == "started"
    assert all(r["attempt_state"] == "complete" for r in rows)


def test_failure_is_saved_without_retry_or_invented_history():
    calls = []

    async def respond(text, **kwargs):
        calls.append(text)
        if len(calls) == 1:
            raise TimeoutError("sensitive diagnostic")
        return {"reply": "A reply."}

    rows = asyncio.run(
        collect([session("a"), session("b")], respond, lambda rows: None)
    )
    assert [r["attempt_state"] for r in rows] == [
        "failed",
        "skipped",
        "complete",
        "complete",
    ]
    assert rows[0]["error_type"] == "TimeoutError"
    assert "sensitive diagnostic" not in str(rows)
    assert len(calls) == 3


def test_summary_retains_failed_latency_and_uses_all_turns_as_denominator():
    summary = summarize(
        [
            {
                "attempt_state": "complete",
                "seconds": 1,
                "path": "deterministic",
                "correction": {"state": "no_supported_correction"},
            },
            {"attempt_state": "failed", "seconds": 3},
            {"attempt_state": "skipped"},
        ],
        3,
    )
    assert summary["denominator"] == 3
    assert summary["completed"] == summary["failed"] == summary["skipped"] == 1
    assert summary["within_two_seconds"] == 1
    assert summary["timing"]["maximum_seconds"] == 3
    assert summary["human_useful"] is None


@pytest.mark.parametrize("model_state", ["matching", "missing", "wrong_digest", "http_error"])
def test_run_checks_protocol_model_before_warmup_and_preserves_attempt(
    tmp_path, monkeypatch, model_state
):
    output = tmp_path / "attempt.json"
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text("{}")
    # The session protocol, not the module's default, owns the expected digest.
    protocol = {
        "model_digest": "protocol-specific-digest",
        "dataset_sha256": "controlled-cases",
        "source_sha256": {},
    }
    monkeypatch.setattr(evaluation, "load_protocol", lambda _: (protocol, []))
    requests, probes = [], []
    real_client = httpx.AsyncClient

    def transport(request):
        requests.append(request.url.path)
        # The initial attempt must survive even a failed readiness request.
        assert json.loads(output.read_text())["rows"] == []
        if request.url.path == "/api/tags":
            model = {"name": evaluation.base.MODEL, "digest": protocol["model_digest"]}
            if model_state == "wrong_digest":
                model["digest"] = "unexpected"
            return httpx.Response(
                503 if model_state == "http_error" else 200,
                json={"models": [] if model_state == "missing" else [model]},
            )
        if request.url.path == "/v2/check":
            return httpx.Response(200, json={"software": {"version": "6.6"}})
        return httpx.Response(200, json={"done": True})

    def client(**kwargs):
        assert kwargs == {"trust_env": False, "timeout": 30}
        return real_client(transport=httpx.MockTransport(transport), **kwargs)

    async def reply(plan, history, budget, client):
        probes.append((plan["text"], history, budget))
        return {"path": "model_selected"}

    monkeypatch.setattr(evaluation.httpx, "AsyncClient", client)
    monkeypatch.setattr(evaluation.flow, "_reply", reply)
    if model_state == "matching":
        report = asyncio.run(evaluation.run(output, directory=tmp_path))
        assert report == json.loads(output.read_text())
        assert report["model"]["digest"] == protocol["model_digest"]
        assert requests == ["/api/tags", "/api/chat", "/v2/check"]
        assert [p[0] for p in probes] == ["I prepared a meal.", "I packed my clothes."]
        assert report["summary"]["completed"] == 0
    else:
        error = httpx.HTTPStatusError if model_state == "http_error" else ValueError
        with pytest.raises(error):
            asyncio.run(evaluation.run(output, directory=tmp_path))
        assert requests == ["/api/tags"]
        assert not probes
        assert "summary" not in json.loads(output.read_text())
    before = output.read_bytes()
    with pytest.raises(ValueError, match="unused output"):
        asyncio.run(evaluation.run(output, directory=tmp_path))
    assert output.read_bytes() == before
