# UI polish and recording recovery

Updated 2026-10-06. This extends Milestone 4 — Streamlit UI (text input first)
and Milestone 5 — Recorded-Turn Voice Input.

## What changed

- A local light theme, green accent, welcoming start screen, clearer practice
  settings, conversation cards, and a layout that stacks on narrow screens.
- **Your next message** keeps **1 · Record** and **2 · Review & send** visible.
  Recording is no longer hidden inside an expander. Stop, transcribe, review,
  then Send remain separate actions; there is no automatic submission.
- **Tutor options** contains the existing experimental switches. **About your
  practice** explains storage and limitations. Per-turn **Response timing**
  contains available grammar-mode timings. The default model/mode is unchanged.
- Empty, whitespace-only, silent, and low-confidence transcription results
  cannot replace the draft or produce a success notice. Unusable speech asks
  the learner to repeat their statement. **Record again** resets the audio widget
  and warning, preserving the draft and conversation.
- Speech model/setup failures instead show **Speech transcription is unavailable**
  and offer typed input. They are not evidence of unclear learner speech.
- Recording errors survive normal UI reruns. The draft syncs on blur outside a
  form, so interacting with recording controls can preserve edits before Send.
  A full browser reload can still lose an unsent draft and recording status.

The owner reported an empty transcript. No failed recording was available, so
its exact cause is **not confirmed**. These changes improve validation, feedback,
and recovery; they do not establish better recognition accuracy. The speech model,
VAD (voice activity detection), and confidence thresholds are unchanged.

## Run the updated interface

If the app shows the changes already, use it. Otherwise copy any unsent draft,
stop the existing Streamlit terminal with **Ctrl+C**, and relaunch from the project
directory. Stop only Streamlit; keep the local model services running.

```bash
cd /Users/lovejit/PerScholas/AI_Solutions_dev/CAPSTONE/AI_Dev_CAPSTONE/lang_app
```

**Purpose and typical use:** `cd` changes the terminal’s working directory;
use it to run project commands where the locked environment and theme are stored.
**Expected output:** None on success. The terminal is now in the project folder.

```bash
uv run --locked streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

**Purpose and typical use:** `uv run --locked` uses the project’s locked Python
environment; `streamlit run` launches the local web interface for interactive use.
**Expected snippet:** `URL: http://127.0.0.1:8501` (the URL label can vary).
**Verifies:** Streamlit is serving the app; it does not prove model availability.
Do not launch a second copy if the intended app is already running on that port.

Open the displayed local address. Expect the green **A little practice. A clearer
voice.** welcome card and **Start conversation**; an existing session URL opens
its conversation instead. On a narrow screen, use the top-left arrow to open
Practice settings. If a saved browser theme overrides the default, the main menu
lets you return to the app theme.

## Test as a learner

| Step | Action | Expected visible result | What this verifies |
| --- | --- | --- | --- |
| 1 | Choose level/topic; select Start conversation. | **Let’s keep talking.**, practice badges, an opening prompt, and **Your next message**. | Settings and the start flow work. |
| 2 | Type `Keep this draft.` and click outside the text box. | The sentence stays in **Your message**. No tutor reply. | Edits sync without submitting a turn. |
| 3 | Record a few seconds of silence, stop, then select Transcribe recording. | Usually **I didn't catch clear speech. Please repeat your statement.** or the equivalent clear-transcript warning. The draft remains. | Silent/unclear input gets actionable feedback, not an empty success. Background noise can affect recognition. |
| 4 | Open Tutor options or another ordinary UI control. | The warning and draft stay visible. | Recovery state survives a rerun. Do not refresh the browser for this test. |
| 5 | Select Record again. | The audio control resets and the warning clears; `Keep this draft.` remains. | Retry discards only recording state. |
| 6 | Record `I enjoy walking in the park.`, stop, then transcribe. | **Transcript ready. Review or edit it, then press Send.** plus nonempty text. Wording/punctuation can vary. | A usable transcript reaches review, without an LLM request yet. |
| 7 | Edit to `I enjoy walking in the park because it helps me relax.` and Send. | Exactly one learner/tutor pair containing your edited sentence; **Turn #2**. | The tutor uses the text you confirmed. Assess feedback accuracy separately. |
| 8 | Refresh the saved session URL after the reply/check completes. | The saved exchange returns without a duplicate. | SQLite history restores correctly. |
| 9 | Narrow the window and repeat typed input. | Recording and review stack vertically; controls and text remain readable. | The interface works in a small window. |

If no text appears after a clear recording, record the exact action and displayed
message. Do not assume this is a pronunciation error. If microphone access is
denied, allow it in your browser when ready or use typed input. Browser permission
errors occur before server transcription and need manual verification.

In separate-grammar mode, **Send** and **Transcribe recording** still wait for the
pending grammar check. The screen explains this; it is not a recording failure.
The app has no spoken replies or automatic end-of-turn detection yet.

## Automated checks and actual evidence

```bash
uv run --locked python -m pytest -q
```

**Purpose and typical use:** Runs automated regression tests in the locked
environment; use it to check state, recovery, persistence, and existing behavior.
**Expected snippet at this checkpoint:** `738 passed in ...s`.
**Observed:** 738 passed in 26.59 seconds. Tests include empty/whitespace results,
persistent warnings, retry then success, service failures, preserved drafts/history,
partial uncertain transcript rejection, and existing separate-grammar integration.

```bash
uv run --locked ruff check app.py ui.py voice_input.py stt.py tests/test_app.py tests/test_stt.py
```

**Purpose and typical use:** Checks the changed Python files for static code
issues; use it before sharing the update. **Expected:** `All checks passed!`.

Browser verification used a separate temporary database and a temporary QA wrapper,
not the learner’s real session. Desktop and 390-pixel layouts were inspected. A
synthetic silent WAV exercised real silence validation; controlled successful
transcription exercised draft replacement and review. An edited synthetic sentence
was sent to the real local tutor and its one saved exchange survived refresh.
The QA fixtures are not features of the production app.

**Known quality failure observed:** The default combined tutor told the learner
to replace `enjoy walking` with `enjoy walking in the park`, even though the submitted
sentence already contained `in the park`. This remains inaccurate feedback; UI
polish is not a grammar-quality improvement or a new approved benchmark score.

Physical microphone capture, permission denial, real noisy/soft-spoken clips, and
cross-browser behavior still require owner testing. Automated speech substitutes
prove control flow, not ASR accuracy. No two-second audio latency claim is made.
Earlier benchmark source hashes/results are preserved; frozen app-integration
protocols intentionally reject this newly styled app until a new protocol is reviewed.

## What to learn and improve next

Read `voice_input.render_recording()` and trace failure versus success: an exception
stores a warning, while only a nonempty successful result can replace the draft.
`reset_recording()` changes the widget key so Streamlit creates an empty audio
control; it leaves text and saved turns alone.

**Practice task:** Try the same short sentence normally, softly, and with background
noise. Record the expected words, actual transcript or warning, and whether retry
preserved your draft. Keep private audio out of Git. Use these observations before
changing model size or confidence thresholds; a rejection does not diagnose pronunciation.

**Next improvement:** Complete that microphone check and address any reproducible
remaining empty-transcript failure before changing tutoring behavior. This is a good
GitHub checkpoint after the owner passes the manual check and reviews the UI. Only
`mvp-v1` and `mvp-v2` were present locally on inspection; `mvp-v3` remains the next
available local checkpoint name, subject to checking remote tags before creating it.
The conversation experiment stays `planned_v4`; a UI update does not start `planned_v5`.
The owner performs all staging, commits, tags, and pushes.
