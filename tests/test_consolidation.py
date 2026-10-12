"""Contracts at shared evaluation, Unicode, and SQLite boundaries."""

import asyncio
import importlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

import benchmark
import conversation_eval_support
import db
import detection_flow_eval
import feedback_store
import runtime_support

RUNNERS = [
    "bounded_conversation_eval",
    "contextual_conversation_eval",
    "natural_conversation_eval",
    "dialogue_planner_eval",
]


def exercise_runner(evaluation, folder, monkeypatch, cold):
    folder.mkdir()
    cases = [
        {
            "id": "one",
            "text": "I made tea.",
            "history": [],
            "level": "beginner",
            "scenario": "daily activities",
            "private_reference": "DO NOT SEND TO MODEL",
        }
    ]
    (folder / "cases.json").write_text(json.dumps({"cases": cases}))
    protocol_name = (
        "protocol_runner_v3.json"
        if evaluation.__name__.endswith("bounded_conversation_eval")
        else "protocol.json"
    )
    (folder / protocol_name).write_text(
        json.dumps(
            {
                "source_sha256": {},
                "dataset_sha256": benchmark.digest(folder / "cases.json"),
            }
        )
    )
    monkeypatch.setattr(evaluation, "DIRECTORY", folder)
    monkeypatch.setattr(evaluation, "verify", lambda: None)
    monkeypatch.setattr(conversation_eval_support, "perf_counter", lambda: 1.0)
    real_client = httpx.AsyncClient
    requests, calls = [], []
    base = getattr(evaluation, "base", evaluation.flow)

    def transport(request):
        requests.append((request.url.path, request.content.decode()))
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={"models": [{"name": base.MODEL, "digest": base.MODEL_DIGEST}]},
            )
        if request.url.path == "/v2/check":
            return httpx.Response(
                200, json={"software": {"version": "6.6"}, "warnings": {}}
            )
        return httpx.Response(200, json={"done": True, "message": {"content": "0"}})

    monkeypatch.setattr(
        conversation_eval_support.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(transport), **kw),
    )

    async def respond(text, **kw):
        calls.append((text, kw))
        return {
            "reply": "What did you put in your tea?",
            "display_text": "A correction. What did you put in your tea?",
            "path": "model_selected",
            "support": "local_reference",
            "seconds": 0.9,
            "correction": {"state": "offered"},
        }

    async def selector(*args):
        calls.append(("selector", {}))
        return 0, {"message": "0"}

    async def generate(*args):
        calls.append(("generate", {}))
        return {"message": "warm"}

    async def planner(*args):
        calls.append(("planner", {}))
        return {"path": "model_selected"}

    monkeypatch.setattr(evaluation.flow, "respond", respond)
    if evaluation.__name__.endswith("bounded_conversation_eval"):
        monkeypatch.setattr(evaluation.flow, "_select", selector)
    if evaluation.__name__.endswith("contextual_conversation_eval"):
        monkeypatch.setattr(evaluation.flow, "generate", generate)
    if evaluation.__name__.endswith("dialogue_planner_eval"):
        monkeypatch.setattr(evaluation.flow, "_reply", planner)
    output = folder / "result.json"
    report = asyncio.run(evaluation.run(output, cold=cold))
    assert json.loads(output.read_text()) == report
    with pytest.raises(ValueError, match="unused output"):
        asyncio.run(evaluation.run(output, cold=cold))
    assert "DO NOT SEND TO MODEL" not in str(calls)
    return report, requests, calls


@pytest.mark.parametrize("name", RUNNERS)
@pytest.mark.parametrize("cold", [False, True])
def test_each_runner_keeps_warmup_and_report_contract(
    name, cold, monkeypatch, tmp_path
):
    evaluation = importlib.import_module(name)
    report, requests, _calls = exercise_runner(
        evaluation, tmp_path / "run", monkeypatch, cold
    )
    assert report["condition"] == ("cold_first_request" if cold else "prewarmed")
    assert report["rows"][0]["attempt_state"] == "complete"
    summary = report["summary"]
    assert (
        summary["completed"]
        == summary["denominator"]
        == summary["within_two_seconds"]
        == 1
    )
    assert (
        summary["human_useful"] is None and summary["human_review_status"] == "pending"
    )
    chat = next(json.loads(body) for path, body in requests if path == "/api/chat")
    assert chat["keep_alive"] == (0 if cold else "10m")
    correction_mode = name in {"natural_conversation_eval", "dialogue_planner_eval"}
    assert ("timely_corrections" in summary) == correction_mode
    assert ("model_selected" in summary) == (
        name in {"bounded_conversation_eval", "dialogue_planner_eval"}
    )
    assert ("selector_readiness_probe" in report) == (
        name == "dialogue_planner_eval" and not cold
    )
    assert ("checker_readiness" in report) == (correction_mode and not cold)
    assert ("readiness_probe" in report) == (not cold)


@pytest.mark.parametrize("transaction", [False, True])
def test_connection_closes_and_preserves_commit_policy(tmp_path, transaction):
    path = tmp_path / "test.sqlite"
    with db._connection(path, transaction=True) as conn:
        conn.execute("CREATE TABLE example (value TEXT)")
    with db._connection(path, transaction=transaction, rows=True) as conn:
        assert conn.row_factory is sqlite3.Row
        conn.execute("INSERT INTO example VALUES ('one')")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")
    with db._connection(path) as check:
        assert check.execute("SELECT COUNT(*) FROM example").fetchone()[0] == int(
            transaction
        )


def test_failed_transaction_rolls_back_and_closes(tmp_path):
    path = tmp_path / "test.sqlite"
    with db._connection(path, transaction=True) as conn:
        conn.execute("CREATE TABLE example (value TEXT)")
    with (
        pytest.raises(RuntimeError, match="abort"),
        db._connection(path, transaction=True) as conn,
    ):
        conn.execute("INSERT INTO example VALUES ('one')")
        raise RuntimeError("abort")
    with db._connection(path) as check:
        assert check.execute("SELECT COUNT(*) FROM example").fetchone()[0] == 0
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


def test_feedback_connection_keeps_error_contract(tmp_path):
    with (
        pytest.raises(db.StorageError, match="separate grammar feedback storage"),
        feedback_store.connection(tmp_path / "missing" / "db.sqlite"),
    ):
        pass


def test_benchmark_unicode_exports_remain_compatible():
    assert benchmark.ROOT == runtime_support.ROOT
    assert benchmark.utf16_span is runtime_support.utf16_span
    assert benchmark.utf16_span("A😀B", 3, 1) == (2, 3)
    with pytest.raises(UnicodeDecodeError):
        benchmark.utf16_span("😀", 1, 1)


def test_runtime_imports_do_not_load_benchmark_commands():
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import sys; import grammar_gap_detector, timely_corrections; assert 'benchmark' not in sys.modules; assert 'grammar' not in sys.modules",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_old_protocol_rejects_refactored_current_source():
    with pytest.raises(
        ValueError, match="Frozen candidate changed: grammar_gap_detector.py"
    ):
        detection_flow_eval.verify()
