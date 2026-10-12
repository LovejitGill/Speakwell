"""Project paths and Unicode offsets shared by runtime and evaluation code."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent


def utf16_span(text, offset, length):
    """Java offsets count UTF-16 units; Python indexes Unicode code points."""
    raw = text.encode("utf-16-le")
    if (
        type(offset) is not int
        or type(length) is not int
        or offset < 0
        or length < 0
        or 2 * (offset + length) > len(raw)
    ):
        raise ValueError("Invalid LanguageTool span.")
    start = len(raw[: 2 * offset].decode("utf-16-le"))
    end = start + len(raw[2 * offset : 2 * (offset + length)].decode("utf-16-le"))
    return start, end
