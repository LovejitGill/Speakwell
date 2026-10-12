"""Text and recorded-turn practice UI. Run with Streamlit, not plain Python."""

import os
import uuid
import warnings
from pathlib import Path
from time import perf_counter

import streamlit as st

import db
import feedback_store
import planned_conversation
import separate_feedback
import ui
import voice_input
from errors import user_message
from feedback_worker import FeedbackWorker
from llm_client import MAX_LEARNER_CHARS, HistorySaveWarning, LLMError, ask_tutor
from prompts import LEVELS, SCENARIOS, get_opening_prompt

DB_PATH = Path(os.environ.get("SPEAKWELL_DB_PATH", str(db.DEFAULT_DB_PATH)))


def restore_page():
    """Hydrate once per browser session, not on every form/widget rerun."""
    if "conversation" in st.session_state:
        return
    st.session_state.conversation = None
    st.session_state.turns = []
    st.session_state.load_error = None
    session_id = st.query_params.get("session")
    if session_id:
        try:
            uuid.UUID(session_id)
            db.init_db(DB_PATH)
            session, turns = db.load_session(session_id, DB_PATH)
            if session["level"] not in LEVELS or session["scenario"] not in SCENARIOS:
                raise ValueError("Unknown saved practice settings.")
            st.session_state.conversation = session
            st.session_state.turns = turns
        except (ValueError, db.StorageError) as exc:
            st.session_state.load_error = str(exc)


def new_conversation():
    # Leave saved rows intact. Clearing the screen is not a deletion operation.
    st.query_params.clear()
    for key in (
        "conversation",
        "turns",
        "load_error",
        "draft",
        "clear_draft",
        "recording_version",
        "transcription_ready",
        "recording_error",
    ):
        st.session_state.pop(key, None)
    st.rerun()


@st.cache_resource
def grammar_worker():
    """Share one CPU grammar worker; it never calls Streamlit from its thread."""
    return FeedbackWorker()


def refresh_grammar():
    session = st.session_state.conversation
    if not session:
        return False
    changed = False
    try:
        statuses = feedback_store.load(session["session_id"], DB_PATH)
        for turn in st.session_state.turns:
            status = statuses.get(turn.get("id"))
            if not status:
                continue
            if status["state"] in {
                "pending",
                "running",
            } and not grammar_worker().is_active(status["job_id"]):
                # After a server restart, do not silently repeat a model call.
                job = {**status, "db_path": DB_PATH}
                feedback_store.finish(
                    job,
                    feedback_store.unavailable(
                        "Grammar feedback was interrupted or could not be saved. Your conversational reply is saved."
                    ),
                )
                status = feedback_store.load(session["session_id"], DB_PATH)[turn["id"]]
            if turn.get("grammar") != status:
                turn["grammar"] = status
                if status.get("conversation"):
                    turn["conversation"] = status["conversation"]
                changed = True
    except db.StorageError:
        st.warning(
            "Grammar status could not be loaded. Your displayed replies are still available."
        )
    return changed


@st.fragment(run_every=1)
def poll_grammar():
    """Poll local storage; refreshing the display never resubmits inference."""
    if (
        any(
            t.get("grammar", {}).get("state") in {"pending", "running"}
            for t in st.session_state.turns
        )
        and refresh_grammar()
    ):
        st.rerun()


def render_turn(number, turn):
    st.caption(f"Turn {number}")
    with st.chat_message("user"):
        st.caption("YOU")
        st.text(turn["learner_text"])
    with st.chat_message("assistant"):
        st.caption("SPEAKWELL")
        conversation = turn.get("conversation") or {}
        quick = conversation.get("correction") or {}
        if quick.get("state") == "offered":
            st.markdown("**Quick correction**")
            st.text(quick["corrected_text"])
            st.text(quick["explanation"])
        st.text(turn["tutor_reply"])
        grammar = turn.get("grammar")
        if grammar:
            st.markdown("**Grammar feedback**")
            state, result = grammar["state"], grammar.get("result") or {}
            if state in {"pending", "running"}:
                st.caption("Checking grammar… Your conversational reply is ready.")
            elif state == "offered":
                edit = result["edit"]
                st.text(f"{edit['original']} → {edit['replacement']}")
                st.text(result["explanation"])
                st.text(f"Suggested sentence: {result['corrected_text']}")
            elif state == "unavailable":
                st.warning(result.get("message", "Grammar feedback is unavailable."))
            else:
                st.caption(result.get("message", "No supported correction to show."))
            timing = f"Reply generation: {grammar['reply_seconds']:.2f} s"
            if "feedback_seconds" in result:
                timing += f" · Grammar processing: {result['feedback_seconds']:.2f} s"
            if "total_seconds" in result:
                timing += (
                    f" · Feedback ready after Send: {result['total_seconds']:.2f} s"
                )
            with st.expander("Response timing"):
                st.caption(timing)
        else:
            st.markdown("**Language feedback**")
            if turn["feedback"]:
                for point in turn["feedback"]:
                    st.text(f"• {point}")
            else:
                st.caption(
                    "No corrections suggested. This is not a guarantee of correctness."
                )
        if not turn["saved"]:
            st.warning(
                "Not saved. This reply will disappear on refresh and will not be remembered by the tutor."
            )


def send_separate(text, session, *, planned=False):
    """Render the conversational reply before scheduling the grammar worker."""
    start = perf_counter()
    response = (
        planned_conversation if planned else separate_feedback
    ).conversation_reply(
        text,
        level=session["level"],
        scenario=session["scenario"],
        session_id=session["session_id"],
        db_path=DB_PATH,
    )
    reply, conversation = response if planned else (response, None)
    reply_seconds = perf_counter() - start
    job = None
    try:
        job = feedback_store.save_reply(
            session["session_id"],
            text.strip(),
            reply,
            reply_seconds,
            start,
            DB_PATH,
            conversation=conversation,
        )
        grammar = {"state": "pending", "reply_seconds": reply_seconds, "result": None}
    except db.StorageError:
        grammar = {
            "state": "unavailable",
            "reply_seconds": reply_seconds,
            "result": feedback_store.unavailable(
                "The reply was not saved, so separate grammar feedback was not started."
            ),
        }
    turn = {
        "learner_text": text.strip(),
        "tutor_reply": reply,
        "feedback": [],
        "saved": job is not None,
        "grammar": grammar,
        "conversation": conversation,
    }
    if job:
        turn["id"] = job["turn_id"]
    st.session_state.turns.append(turn)
    st.session_state.clear_draft = True
    render_turn(len(st.session_state.turns), turn)
    if job:
        grammar_worker().start(job)
    st.rerun()


def main():
    st.set_page_config(
        page_title="SpeakWell · English practice", page_icon="💬", layout="wide"
    )
    ui.apply_style()
    restore_page()
    if st.session_state.pop("clear_draft", False):
        st.session_state.draft = ""
        st.session_state.pop("transcription_ready", None)

    session = st.session_state.conversation
    refresh_grammar()
    pending_grammar = any(
        t.get("grammar", {}).get("state") in {"pending", "running"}
        for t in st.session_state.turns
    )
    if "separate_grammar" not in st.session_state:
        st.session_state.separate_grammar = bool(
            st.session_state.turns and st.session_state.turns[-1].get("grammar")
        )
    if "planned_conversation" not in st.session_state:
        st.session_state.planned_conversation = any(
            (t.get("conversation") or {}).get("engine") == planned_conversation.ENGINE
            for t in st.session_state.turns[-1:]
        )
    with st.sidebar:
        ui.brand()
        st.header("Practice settings")
        level = st.selectbox(
            "Level",
            list(LEVELS),
            index=list(LEVELS).index(session["level"]) if session else 0,
            disabled=bool(session),
            format_func=str.capitalize,
        )
        scenario = st.selectbox(
            "Scenario",
            list(SCENARIOS),
            index=list(SCENARIOS).index(session["scenario"]) if session else 0,
            disabled=bool(session),
            format_func=str.capitalize,
        )
        st.caption(
            "Settings stay fixed during a conversation. Start a new one to change them."
        )
        with st.expander("Tutor options"):
            separate = st.checkbox(
                "Separate grammar feedback (experimental)",
                key="separate_grammar",
                disabled=pending_grammar,
            )
            if separate:
                st.caption(
                    "Read the reply first; grammar feedback follows. This can take several seconds."
                )
                planned = st.checkbox(
                    "Context-aware conversation (experimental)",
                    key="planned_conversation",
                    disabled=pending_grammar,
                )
                if planned:
                    st.caption(
                        "Uses recent replies to guide follow-up questions. Some responses use prepared wording."
                    )
            else:
                planned = False
        if session and st.button("New conversation", key="new", width="stretch"):
            new_conversation()
        st.divider()
        with st.expander("About your practice"):
            st.caption(
                "English practice with written replies. Live conversation, spoken replies, and pronunciation assessment are not available yet."
            )
            st.caption(
                "Sent text is saved on this computer. Recordings are held in memory, not saved to disk by the app. New conversation keeps earlier history."
            )
            st.caption("Keep session URLs private; this local demo has no accounts.")
            if session:
                st.caption(f"Conversation: {session['session_id']}")

    ui.page_header(session, len(st.session_state.turns))
    st.caption(
        "AI feedback can be inaccurate. Transcription does not assess pronunciation."
    )

    if st.session_state.load_error:
        st.error(f"Could not restore history: {st.session_state.load_error}")
        if st.button("Start over", key="reset"):
            new_conversation()
        st.stop()

    if not session:
        st.write("Choose your level and topic in Practice settings, then begin.")
        if st.button("Start conversation", key="start", type="primary"):
            session_id = str(uuid.uuid4())
            try:
                db.init_db(DB_PATH)
                db.create_session(session_id, level, scenario, DB_PATH)
            except db.StorageError as exc:
                st.error(user_message(exc))
            else:
                st.session_state.conversation = {
                    "session_id": session_id,
                    "level": level,
                    "scenario": scenario,
                }
                st.query_params["session"] = session_id
                st.rerun()
        ui.welcome_steps()
        st.stop()

    st.subheader("Conversation")
    if not st.session_state.turns:
        with st.container(border=True, key="starter"):
            st.markdown("**Let’s start here**")
            st.info(get_opening_prompt(session["level"], session["scenario"]))
            st.caption(
                "Try two short sentences. Share only what you feel comfortable sharing."
            )
    for number, turn in enumerate(st.session_state.turns, 1):
        render_turn(number, turn)
    poll_grammar()
    if pending_grammar:
        st.info(
            "Checking grammar. You can draft your next message; Send and Transcribe will be available when the check finishes."
        )

    with st.container(border=True, key="composer"):
        st.subheader("Your next message")
        st.caption(
            f"Turn #{len(st.session_state.turns) + 1} · Record or type. You choose when to send."
        )
        record_column, review_column = st.columns([1, 1.25], gap="large")
        with record_column:
            voice_input.render_recording(pending_grammar=pending_grammar)
        with review_column:
            st.markdown("**2 · Review & send**")
            st.caption("Check the transcript, or type your own message.")
            if (
                st.session_state.get("transcription_ready")
                and st.session_state.get("draft", "").strip()
            ):
                st.success("Transcript ready. Review or edit it, then press Send.")
            # Outside a form: edits sync on blur before recording controls rerun.
            text = st.text_area(
                "Your message",
                key="draft",
                max_chars=MAX_LEARNER_CHARS,
                height=160,
                placeholder="Your transcript appears here. You can also type a message…",
            )
            submitted = st.button(
                "Send",
                key="send",
                disabled=pending_grammar,
                type="primary",
                width="stretch",
            )
    if submitted:
        if pending_grammar:
            return
        if not text.strip():
            st.error("Enter a message before sending.")
            return
        if separate:
            try:
                with st.spinner("The tutor is responding…"):
                    send_separate(text, session, planned=planned)
            except (ValueError, LLMError, db.StorageError) as exc:
                st.error(user_message(exc))
                st.caption(
                    "Your message is still in the box. Fix the issue, then press Send to retry."
                )
            return
        try:
            with (
                st.spinner("The tutor is responding…"),
                warnings.catch_warnings(record=True) as notices,
            ):
                warnings.simplefilter("always", HistorySaveWarning)
                result = ask_tutor(
                    text,
                    level=session["level"],
                    scenario=session["scenario"],
                    session_id=session["session_id"],
                    db_path=DB_PATH,
                )
        except (ValueError, LLMError, db.StorageError) as exc:
            st.error(user_message(exc))
            st.caption(
                "Your message is still in the box. Fix the issue, then press Send to retry."
            )
            return
        saved = not any(issubclass(n.category, HistorySaveWarning) for n in notices)
        st.session_state.turns.append(
            {
                "learner_text": text.strip(),
                "tutor_reply": result["reply"],
                "feedback": result["feedback"],
                "saved": saved,
            }
        )
        st.session_state.clear_draft = True
        st.rerun()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- final UI safety boundary
        # Streamlit's rerun/stop signals inherit BaseException and pass through.
        # Do not expose arbitrary exception messages or learner text in the UI.
        st.error(user_message(RuntimeError()))
        st.caption(
            f"Diagnostic type: {type(exc).__name__}. Report this with the failed action."
        )
