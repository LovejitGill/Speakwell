"""Preserved comparison of contextual question generation and bounded fallback."""

import bounded_conversation as base
import contextual_conversation as flow
from benchmark import ROOT, timing
from conversation_eval_support import run_cli, run_evaluation
from conversation_quality_eval import verify

DIRECTORY = ROOT / "evaluation/conversation_quality/contextual_v2"


async def _warmup(client, report):
    raw = await flow.generate(base.prepare("I made something."), [], client)
    report["readiness_probe"] = {
        "raw": raw,
        "text": "I made something.",
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
        timing_scope="In-memory preparation + HTTP wait/cancellation + rendering a complete text reply. Excludes DB, UI, STT, TTS, and readiness setup. Not a voice measurement.",
        display_key="reply",
    )


if __name__ == "__main__":
    run_cli(run, __doc__)
