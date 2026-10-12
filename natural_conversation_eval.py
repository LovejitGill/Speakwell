"""Evaluate natural follow-ups and correction-first rendering under one time budget."""

import bounded_conversation as base
import natural_conversation as flow
from benchmark import ROOT, timing
from conversation_eval_support import run_cli, run_evaluation
from conversation_quality_eval import verify

DIRECTORY = ROOT / "evaluation/conversation_quality/natural_v4"


async def _warmup(client, report):
    probe = flow.prepare("I prepared a meal.")
    response = await client.post(
        base.HOST + "/api/chat",
        json={
            "model": base.MODEL,
            "messages": flow.messages(probe, []),
            "think": False,
            "stream": False,
            "keep_alive": "10m",
            "options": flow.OPTIONS,
        },
    )
    response.raise_for_status()
    raw = response.json()
    check = await client.post(
        "http://127.0.0.1:8081/v2/check",
        data={"language": "en-US", "text": "We practice English."},
    )
    check.raise_for_status()
    report["checker_readiness"] = {
        "software": check.json()["software"],
        "warnings": check.json().get("warnings"),
    }
    report["readiness_probe"] = {
        "raw": raw,
        "text": "I prepared a meal.",
    }


def _summarize(rows, denominator):
    return {
        "denominator": denominator,
        "completed": len(rows),
        "timing": timing(rows),
        "within_two_seconds": sum(r["seconds"] <= 2 for r in rows),
        "model_generated": sum(r["path"] == "model_generated" for r in rows),
        "local_fallback": sum(r["path"] == "local_fallback" for r in rows),
        "deterministic": sum(r["path"] == "deterministic" for r in rows),
        "unsupported_questions": sum(
            r["support"] == "unsupported_question" for r in rows
        ),
        "timely_corrections": sum(r["correction"]["state"] == "offered" for r in rows),
        "checker_unavailable": sum(
            r["correction"]["state"] == "unavailable" for r in rows
        ),
        "human_useful": None,
        "human_review_status": "pending",
    }


async def run(output, *, cold=False):
    return await run_evaluation(
        output,
        cold=cold,
        root=ROOT,
        directory=DIRECTORY,
        protocol_filename="protocol.json",
        verify=verify,
        flow=flow,
        model_source=base,
        warmup=_warmup,
        summarize=_summarize,
        timing_scope="In-memory preparation + concurrent conversation and fast checker + correction-first complete text assembly. Excludes DB/UI/STT/TTS/readiness and full grammar pipeline. Not a voice measurement.",
        display_key="display_text",
    )


if __name__ == "__main__":
    run_cli(run, __doc__)
