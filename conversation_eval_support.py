"""Common recording mechanics for independent-case conversation evaluations."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import httpx

from benchmark import digest, save


def load_cases(root, directory, protocol_filename, verify):
    """Reject changed sources/cases before readiness or any model request."""
    protocol_path = directory / protocol_filename
    protocol = json.loads(protocol_path.read_text())
    for name, expected in protocol["source_sha256"].items():
        if digest(root / name) != expected:
            raise ValueError(f"Prepared source changed: {name}")
    if digest(directory / "cases.json") != protocol["dataset_sha256"]:
        raise ValueError("Prepared cases changed.")
    verify()
    cases = json.loads((directory / "cases.json").read_text())["cases"]
    return protocol_path, protocol, cases


async def prepared_model(client, host, name, expected_digest):
    tags = await client.get(host + "/api/tags")
    tags.raise_for_status()
    model = next((m for m in tags.json()["models"] if m["name"] == name), None)
    if not model or model["digest"] != expected_digest:
        raise ValueError("Expected the prepared local model digest.")
    return model


async def record_case(output, report, case, respond, save):
    """Save started/completed states before the caller aggregates or prints."""
    report["rows"].append({"case_id": case["id"], "attempt_state": "started"})
    save(output, report)
    result = await respond(
        case["text"],
        history=case["history"],
        level=case["level"],
        scenario=case["scenario"],
    )
    report["rows"][-1] = {
        "case_id": case["id"],
        "attempt_state": "complete",
        "status": "valid",  # Completed response, not a semantic pass.
        **result,
    }
    save(output, report)
    return result


async def run_evaluation(
    output,
    *,
    cold,
    root,
    directory,
    protocol_filename,
    verify,
    flow,
    model_source,
    warmup,
    summarize,
    timing_scope,
    display_key,
):
    """Run independent cases; each candidate owns its warm-up and scoring policy."""
    if output.exists():
        raise ValueError("Choose an unused output path; preserve earlier attempts.")
    protocol_path, protocol, cases = load_cases(
        root, directory, protocol_filename, verify
    )
    async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
        model = await prepared_model(
            client, model_source.HOST, model_source.MODEL, model_source.MODEL_DIGEST
        )
        report = {
            "created_utc": datetime.now(UTC).isoformat(),
            "protocol_sha256": digest(protocol_path),
            "dataset_sha256": protocol["dataset_sha256"],
            "model": model,
            "condition": "cold_first_request" if cold else "prewarmed",
            "timing_scope": timing_scope,
            "source_sha256": protocol["source_sha256"],
            "rows": [],
        }
        save(output, report, exclusive=True)
        began = perf_counter()
        # Unload only this model for a cold run; leave other local models intact.
        setup = await client.post(
            model_source.HOST + "/api/chat",
            json={
                "model": model_source.MODEL,
                "messages": [],
                "stream": False,
                "keep_alive": 0 if cold else "10m",
                "options": flow.OPTIONS,
            },
        )
        setup.raise_for_status()
        report["readiness_raw"] = setup.json()
        if not cold:
            await warmup(client, report)
        report["readiness_seconds"] = perf_counter() - began
        save(output, report)
        for case in cases:
            result = await record_case(output, report, case, flow.respond, save)
            report["summary"] = summarize(report["rows"], len(cases))
            save(output, report)
            print(
                f"{case['id']} {result['path']} {result['seconds']:.3f}s: {result[display_key]}",
                flush=True,
            )
    return report


def run_cli(run, description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cold",
        action="store_true",
        help="Unload the selector model before the first measured request",
    )
    args = parser.parse_args()
    asyncio.run(run(args.output, cold=args.cold))
