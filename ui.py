"""Presentation helpers. Learner/model content stays in native Streamlit widgets."""

from html import escape
from pathlib import Path

import streamlit as st


def apply_style():
    # Only this trusted, local stylesheet is rendered as HTML.
    css = (Path(__file__).parent / "assets" / "style.css").read_text()
    st.html(f"<style>{css}</style>")


def brand():
    st.html(
        '<div class="sw-brand"><span class="sw-mark" aria-hidden="true">s<span>·</span></span>'
        "<div><strong>SpeakWell</strong><small>A little practice, every day.</small></div></div>"
    )


def page_header(session, turn_count):
    st.html('<div class="sw-eyebrow">SPEAKWELL <span> / </span> ENGLISH PRACTICE</div>')
    if session:
        st.title("Let’s keep talking.")
        chips = [session["level"].capitalize(), session["scenario"].capitalize()]
        chips.append(f"{turn_count} {'reply' if turn_count == 1 else 'replies'}")
        st.html(
            '<div class="sw-chips">'
            + "".join(f"<span>{escape(chip)}</span>" for chip in chips)
            + "</div>"
        )
    else:
        st.html("""<div class="sw-hero">
          <div class="sw-eyebrow">YOUR SPACE TO PRACTICE</div>
          <h1>A little practice.<br>A clearer voice.</h1>
          <p>Find the words. Follow your curiosity.<br>Build confidence, one conversation at a time.</p>
          <div class="sw-hero-note">English practice · Runs on your computer</div>
        </div>""")


def welcome_steps():
    st.html("""<div class="sw-steps">
      <div><span>01</span><strong>Make it yours</strong><p>Choose a level and an everyday topic.</p></div>
      <div><span>02</span><strong>Say something</strong><p>Record a thought, or type it out.</p></div>
      <div><span>03</span><strong>Keep it going</strong><p>Review your words, send, and read the tutor’s reply.</p></div>
    </div>""")
