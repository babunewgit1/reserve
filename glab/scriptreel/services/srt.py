"""SRT parsing/writing and timing validation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol


class CueLike(Protocol):
    start: float
    end: float
    text: str


@dataclass
class SrtCue:
    start: float
    end: float
    text: str


@dataclass
class Issue:
    index: int  # 0-based cue index
    severity: str  # error | warning
    message: str


_TS_RE = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[,.](\d{1,3}))?\s*$")


def fmt_ts(t: float, sep: str = ",") -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def fmt_short(t: float) -> str:
    """m:ss.mmm for tables."""
    ms = int(round(max(0.0, t) * 1000))
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{m}:{s:02d}.{ms:03d}"


def parse_ts(text: str) -> float:
    text = text.strip()
    m = _TS_RE.match(text)
    if m:
        h, mi, s, frac = m.groups()
        frac = (frac or "0").ljust(3, "0")
        return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(frac) / 1000.0
    try:  # plain seconds
        v = float(text.replace(",", "."))
        if v >= 0:
            return v
    except ValueError:
        pass
    raise ValueError(f"Invalid timestamp: {text!r}")


def wrap_text(text: str, width: int = 42) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    mid = len(text) // 2
    left = text.rfind(" ", 0, mid + 1)
    right = text.find(" ", mid)
    candidates = [i for i in (left, right) if i > 0]
    if not candidates:
        return text
    cut = min(candidates, key=lambda i: abs(i - mid))
    return text[:cut] + "\n" + text[cut + 1:]


def to_srt(cues: Iterable[CueLike], wrap: bool = True) -> str:
    out = []
    for i, c in enumerate(cues, 1):
        body = wrap_text(c.text) if wrap else c.text
        out.append(f"{i}\n{fmt_ts(c.start)} --> {fmt_ts(c.end)}\n{body}\n")
    return "\n".join(out)


def write_srt(path: Path, cues: Iterable[CueLike]) -> Path:
    path.write_text(to_srt(cues), encoding="utf-8")
    return path


def parse_srt(text: str) -> list[SrtCue]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    cues: list[SrtCue] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not lines:
            continue
        if "-->" not in lines[0] and len(lines) > 1:
            lines = lines[1:]
        if "-->" not in lines[0]:
            continue
        a, b = lines[0].split("-->", 1)
        b = b.strip().split(" ")[0]
        try:
            start, end = parse_ts(a), parse_ts(b)
        except ValueError:
            continue
        cues.append(SrtCue(start, end, " ".join(ln.strip() for ln in lines[1:])))
    return cues


def validate(cues: list[CueLike], duration: float | None = None) -> list[Issue]:
    issues: list[Issue] = []
    for i, c in enumerate(cues):
        if c.start < 0 or c.end < 0:
            issues.append(Issue(i, "error", "Negative timestamp"))
        if c.end <= c.start:
            issues.append(Issue(i, "error", "End time is not after start time"))
        if not c.text.strip():
            issues.append(Issue(i, "warning", "Empty subtitle text"))
        if i + 1 < len(cues):
            nxt = cues[i + 1]
            if nxt.start < c.start:
                issues.append(Issue(i + 1, "error", "Cue starts before the previous cue (out of order)"))
            elif c.end > nxt.start + 1e-3:
                issues.append(Issue(i, "error", f"Overlaps next cue by {c.end - nxt.start:.3f}s"))
        if duration and c.end > duration + 0.05:
            issues.append(Issue(i, "warning", f"Ends after the narration ({duration:.2f}s)"))
        if c.end - c.start > 8:
            issues.append(Issue(i, "warning", "Longer than 8 s — consider splitting"))
        cps = len(c.text) / max(0.001, c.end - c.start)
        if cps > 25:
            issues.append(Issue(i, "warning", f"Fast reading speed ({cps:.0f} chars/s)"))
    return issues


def auto_fix(cues: list[SrtCue], duration: float | None = None) -> list[SrtCue]:
    """Sort, clamp negatives, resolve overlaps, clamp to duration."""
    fixed = sorted((SrtCue(max(0.0, c.start), max(0.0, c.end), c.text) for c in cues), key=lambda c: c.start)
    for i, c in enumerate(fixed):
        if duration:
            c.start = min(c.start, max(0.0, duration - 0.1))
            c.end = min(c.end, duration)
        if c.end <= c.start:
            c.end = c.start + 0.4
        if i + 1 < len(fixed) and c.end > fixed[i + 1].start:
            c.end = max(c.start + 0.05, fixed[i + 1].start)
    return fixed
