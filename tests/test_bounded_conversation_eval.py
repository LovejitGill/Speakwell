"""The benchmark must preserve failures and the full denominator."""

import asyncio
import importlib
import json

import httpx
import pytest

import bounded_conversation_eval as evaluation
import conversation_eval_support
from benchmark import digest


@pytest.mark.parametrize(
    "name",
    [
        "bounded_conversation_eval",
        "contextual_conversation_eval",
        "natural_conversation_eval",
        "dialogue_planner_eval",
    ],
)
@pytest.mark.parametrize("cold", [False, True])
def test_report_checkpoints_responses_before_aggregation(
    monkeypatch, tmp_path, name, cold
):
    evaluation = importlib.import_module(name)
    model_source = getattr(evaluation, "base", evaluation.flow)
    directory = tmp_path / "prepared"
    directory.mkdir()
    case = {
        "id": "test-1",
        "text": "Pottery.",
        "history": [],
        "level": "beginner",
        "scenario": "daily activities",
    }
    (directory / "cases.json").write_text(json.dumps({"cases": [case]}))
    protocol_name = (
        "protocol_runner_v3.json"
        if name == "bounded_conversation_eval"
        else "protocol.json"
    )
    (directory / protocol_name).write_text(
        json.dumps(
            {
                "source_sha256": {},
                "dataset_sha256": digest(directory / "cases.json"),
            }
        )
    )
    monkeypatch.setattr(evaluation, "DIRECTORY", directory)
    monkeypatch.setattr(evaluation, "verify", lambda: None)
    real_client = httpx.AsyncClient

    def transport(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": model_source.MODEL,
                            "digest": model_source.MODEL_DIGEST,
                        }
                    ]
                },
            )
        if request.url.path == "/v2/check":
            return httpx.Response(200, json={"software": {"version": "6.6"}})
        return httpx.Response(
            200, json={"done": True, "done_reason": "stop", "message": {"content": "0"}}
        )

    monkeypatch.setattr(
        conversation_eval_support.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(transport), **kw),
    )

    async def respond(*args, **kwargs):
        return {
            "reply": "A preserved response.",
            "display_text": "A preserved response.",
            "correction": {"state": "no_supported_correction"},
            "path": "local_fallback",
            "support": "guided_practice",
            "seconds": 0.9,
            "raw_selector": None,
        }

    monkeypatch.setattr(evaluation.flow, "respond", respond)
    output = tmp_path / "result.json"
    original_timing = evaluation.timing

    def broken_summary(rows):
        raise RuntimeError("summary failed")

    monkeypatch.setattr(evaluation, "timing", broken_summary)
    with pytest.raises(RuntimeError, match="summary failed"):
        asyncio.run(evaluation.run(output, cold=cold))
    retained = json.loads(output.read_text())
    assert retained["rows"][0]["reply"] == "A preserved response."
    assert retained["rows"][0]["attempt_state"] == "complete"
    with pytest.raises(ValueError, match="unused output"):
        asyncio.run(evaluation.run(output, cold=cold))
    monkeypatch.setattr(evaluation, "timing", original_timing)
    report = asyncio.run(evaluation.run(tmp_path / "second.json", cold=cold))
    assert report["summary"]["denominator"] == 1
    assert report["summary"]["local_fallback"] == 1
    assert report["summary"]["human_useful"] is None


def test_tampered_source_stops_before_model_access(monkeypatch, tmp_path):
    source = tmp_path / "source.py"
    source.write_text("changed")
    (tmp_path / "protocol_runner_v3.json").write_text(
        json.dumps({"source_sha256": {"source.py": "prepared_hash"}})
    )
    monkeypatch.setattr(evaluation, "DIRECTORY", tmp_path)
    monkeypatch.setattr(evaluation, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="Prepared source changed"):
        asyncio.run(evaluation.run(tmp_path / "output.json"))
    assert not (tmp_path / "output.json").exists()
