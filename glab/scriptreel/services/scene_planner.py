"""Scene segmentation from word timings.

Scenes always tile the narration timeline contiguously (0 → duration), so
every frame of the final video belongs to exactly one scene. Cuts are placed
in the pauses between words, preferring sentence ends, then clause ends.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Sequence

SENT_END = re.compile(r"[.!?।…؟。！？]['\"”’)\]]*$")
CLAUSE_END = re.compile(r"[,;:—–]['\"”’)\]]*$")


@dataclass
class W:
    start: float
    end: float
    text: str


@dataclass
class PlannedScene:
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start


def _words(raw: Sequence) -> list[W]:
    out = []
    for r in raw:
        if isinstance(r, W):
            out.append(r)
        elif isinstance(r, (list, tuple)):
            out.append(W(float(r[0]), float(r[1]), str(r[2])))
        else:
            out.append(W(float(r.start), float(r.end), str(r.text)))
    return out


def assign_text(words: Sequence, start: float, end: float) -> str:
    return " ".join(w.text for w in _words(words) if start <= (w.start + w.end) / 2 < end)


def _score(word: W, nxt: W | None) -> float:
    s = 1.0
    if SENT_END.search(word.text):
        s = 3.0
    elif CLAUSE_END.search(word.text):
        s = 2.0
    if nxt is not None and nxt.start - word.end > 0.25:
        s += 0.5
    return s


def plan_flexible(raw_words: Sequence, duration: float, min_s: float = 3.0, target_s: float = 6.0,
                  max_s: float = 10.0) -> list[PlannedScene]:
    words = _words(raw_words)
    max_s = max(max_s, min_s + 0.5)
    target_s = min(max(target_s, min_s), max_s)
    if not words:
        return plan_fixed([], duration, target_s)
    cuts: list[float] = []
    scene_start = 0.0
    candidates: list[tuple[float, float, float]] = []  # (score, elapsed, boundary)
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None:
            break
        boundary = (w.end + nxt.start) / 2.0
        elapsed = boundary - scene_start
        if elapsed >= min_s and elapsed <= max_s:
            sc = _score(w, nxt)
            candidates.append((sc, elapsed, boundary))
            if sc >= 3.0 and elapsed >= target_s:
                cuts.append(boundary)
                scene_start, candidates = boundary, []
                continue
        if nxt.end - scene_start > max_s:
            if candidates:
                best = max(candidates, key=lambda c: (c[0], -abs(c[1] - target_s)))
                cut = best[2]
            else:
                cut = boundary if boundary > scene_start + 0.5 else scene_start + max_s
            cuts.append(cut)
            scene_start = cut
            candidates = [c for c in candidates if c[2] > cut]
            candidates = [(c[0], c[2] - cut, c[2]) for c in candidates if c[2] - cut >= min_s]
    # trailing remainder
    if cuts and duration - cuts[-1] < min_s:
        prev_start = cuts[-2] if len(cuts) > 1 else 0.0
        if duration - prev_start <= max_s + 0.5:
            cuts.pop()
    # break up any over-long scenes (e.g. long silence at the end)
    bounds = [0.0, *cuts, duration]
    final: list[float] = [0.0]
    for a, b in zip(bounds, bounds[1:]):
        n = math.ceil((b - a) / max_s) if b - a > max_s + 0.5 else 1
        for k in range(1, n):
            final.append(a + (b - a) * k / n)
        final.append(b)
    scenes = []
    for a, b in zip(final, final[1:]):
        if b - a > 1e-3:
            scenes.append(PlannedScene(round(a, 3), round(b, 3), assign_text(words, a, b)))
    if scenes:
        scenes[-1].end = round(duration, 3)
    return scenes


def plan_fixed(raw_words: Sequence, duration: float, length: float = 8.0) -> list[PlannedScene]:
    words = _words(raw_words)
    scenes = []
    t = 0.0
    while t < duration - 1e-3:
        e = min(duration, t + length)
        if duration - e < 0.5:  # avoid a sliver at the end; final clip holds its last frame briefly
            e = duration
        scenes.append(PlannedScene(round(t, 3), round(e, 3), assign_text(words, t, e)))
        t = e
    return scenes


def plan(raw_words: Sequence, duration: float, mode: str, *, min_s: float, target_s: float, max_s: float,
         fixed_len: float = 8.0) -> list[PlannedScene]:
    if duration <= 0:
        return []
    if mode == "fixed8":
        return plan_fixed(raw_words, duration, fixed_len)
    return plan_flexible(raw_words, duration, min_s, target_s, max_s)


def choose_generation_length(scene_dur: float, durations: Sequence[int], default: int | None) -> tuple[int | None, float, float]:
    """Pick a native clip length. Returns (length, trim_seconds, hold_seconds)."""
    ds = sorted(set(int(d) for d in durations))
    if not ds:
        return default, 0.0, 0.0
    fit = [d for d in ds if d >= scene_dur - 0.05]
    if fit:
        d = fit[0]
        return d, max(0.0, d - scene_dur), 0.0
    d = ds[-1]
    return d, 0.0, scene_dur - d


def best_split_time(raw_words: Sequence, start: float, end: float) -> float:
    """Split point near the middle of [start, end], preferring sentence/clause pauses."""
    words = [w for w in _words(raw_words) if start <= (w.start + w.end) / 2 < end]
    mid = (start + end) / 2
    best, best_cost = mid, float("inf")
    for i in range(len(words) - 1):
        b = (words[i].end + words[i + 1].start) / 2
        if b - start < 0.5 or end - b < 0.5:
            continue
        cost = abs(b - mid) / max(0.1, end - start) * 3 - _score(words[i], words[i + 1])
        if cost < best_cost:
            best, best_cost = b, cost
    return round(best, 3)
