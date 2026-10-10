"""Recording controls and recoverable UI state; never submits text to the tutor."""

import streamlit as st

import stt
from llm_client import MAX_LEARNER_CHARS
from stt import SpeechServiceError, TranscriptionError, UnclearSpeechError


def reset_recording():
    """Replace the audio widget, keeping the learner's draft and saved turns."""
    st.session_state.recording_version = (
        st.session_state.get("recording_version", 0) + 1
    )
    st.session_state.pop("recording_error", None)
    st.session_state.pop("transcription_ready", None)


def render_recording(*, pending_grammar=False):
    st.markdown("**1 · Record**")
    st.caption("Speak in English, stop recording, then select Transcribe recording.")
    version = st.session_state.get("recording_version", 0)
    recording = st.audio_input(
        "Record your message", sample_rate=16000, key=f"recording_{version}"
    )
    if st.button(
        "Transcribe recording",
        key="transcribe",
        disabled=recording is None or pending_grammar,
        width="stretch",
    ):
        st.session_state.pop("transcription_ready", None)
        try:
            with st.spinner("Turning your recording into text…"):
                transcript = stt.transcribe_audio(recording.getvalue())
            # Defend the UI boundary too: a blank result must never erase a draft.
            if not isinstance(transcript, str):
                raise SpeechServiceError(
                    "The speech service returned an invalid result."
                )
            transcript = transcript.strip()
            if not transcript:
                raise UnclearSpeechError(
                    "I couldn't get a clear transcript. Please repeat your statement."
                )
            if len(transcript) > MAX_LEARNER_CHARS:
                raise TranscriptionError(
                    "Transcript is too long. Record a shorter message."
                )
        except TranscriptionError as exc:
            st.session_state.recording_error = {
                "message": str(exc),
                "code": exc.code,
                "service": isinstance(exc, SpeechServiceError),
                "unclear": isinstance(exc, UnclearSpeechError),
            }
        else:
            st.session_state.draft = transcript
            reset_recording()
            st.session_state.transcription_ready = True
            st.rerun()

    error = st.session_state.get("recording_error")
    if error:
        if error["service"]:
            st.error(
                "Speech transcription is unavailable. You can type your message below."
            )
            with st.expander("Speech service details"):
                st.caption(f"{error['code']}: {error['message']}")
        else:
            st.warning(error["message"])
            if error["unclear"]:
                st.caption(
                    "Try a quieter place, move closer to the microphone, and use a short sentence."
                )
        st.caption(
            "Nothing was sent from this recording. Record again, or continue by typing."
        )
    if (recording is not None or error) and st.button(
        "Record again", key="record_again", width="stretch"
    ):
        reset_recording()
        st.rerun()
    st.caption("Up to 60 seconds. A successful transcription replaces your draft.")
    if pending_grammar:
        st.caption("Transcription will be available when the grammar check finishes.")
