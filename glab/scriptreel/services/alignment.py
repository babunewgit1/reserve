"""Local subtitle alignment / transcription.

Voice Studio returns audio only, so subtitle timing is produced here.
Engines implement `AlignmentEngine` and are replaceable:

* FasterWhisperEngine — local speech recognition with word timestamps
  (optional `faster-whisper` package). In "script" method the recognized
  words are aligned to the ORIGINAL script text (sequence alignment), so the
  subtitle text is exactly the script while timing comes from the audio.
  Typical accuracy is ~0.1–0.3 s; it is not millisecond-perfect.
* EstimateEngine — no ML. Finds pauses with FFmpeg's silencedetect (Voice
  Studio joins sentences with ~0.3 s gaps) and distributes script sentences
  and words over the speech regions. Approximate; always needs review.
"""
from __future__ import annotations

import importlib.util
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from .ffmpeg_tools import probe, silence_detect
from .http_base import CancelToken

log = logging.getLogger("scriptreel.alignment")

ProgressFn = Callable[[float, str], None]

LANG_CODES = {
    "english": "en", "bengali": "bn", "bangla": "bn", "hindi": "hi", "urdu": "ur", "spanish": "es",
    "french": "fr", "german": "de", "portuguese": "pt", "italian": "it", "arabic": "ar",
    "indonesian": "id", "vietnamese": "vi", "japanese": "ja", "korean": "ko", "chinese": "zh",
    "russian": "ru", "turkish": "tr", "dutch": "nl", "polish": "pl", "thai": "th", "tamil": "ta",
}
SENTENCE_END = re.compile(r"[.!?।…؟。！？]['\"”’)\]]*$")
CLAUSE_END = re.compile(r"[,;:—–]['\"”’)\]]*$")


@dataclass
class TimedWord:
    start: float
    end: float
    text: str
    matched: bool = True


@dataclass
class AlignmentResult:
    words: list[TimedWord]
    engine: str
    model: str
    method: str
    precision_note: str
    match_ratio: float | None = None
    warnings: list[str] = field(default_factory=list)


class AlignmentError(Exception):
    pass


class AlignmentEngine(ABC):
    id = "base"
    label = "Base"

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        ...

    @abstractmethod
    def align(self, audio: Path, script: str, language: str, *, method: str,
              progress: ProgressFn, cancel: CancelToken) -> AlignmentResult:
        ...


# ---------------------------------------------------------------- helpers
def _norm(token: str) -> str:
    return re.sub(r"[^\w]", "", token.lower())


def _distribute(tokens: list[str], start: float, end: float) -> list[tuple[float, float]]:
    weights = [max(1, len(t)) + 1 for t in tokens]
    total = sum(weights) or 1
    out, t = [], start
    for w in weights:
        d = (end - start) * w / total
        out.append((t, t + d))
        t += d
    return out


def map_script_to_asr(script: str, asr: list[TimedWord], audio_end: float) -> tuple[list[TimedWord], float]:
    """Assign times from recognized words to the original script tokens."""
    tokens = script.split()
    if not tokens:
        return [], 0.0
    if not asr:
        spans = _distribute(tokens, 0.0, audio_end)
        return [TimedWord(a, b, t, False) for t, (a, b) in zip(tokens, spans)], 0.0
    s_norm = [_norm(t) for t in tokens]
    a_norm = [_norm(w.text) for w in asr]
    times: list[tuple[float, float] | None] = [None] * len(tokens)
    matched_flags = [False] * len(tokens)
    matched = 0
    sm = SequenceMatcher(None, s_norm, a_norm, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                w = asr[j1 + k]
                times[i1 + k] = (w.start, w.end)
                matched_flags[i1 + k] = True
                matched += 1
        elif tag == "replace":
            for k, span in enumerate(_distribute(tokens[i1:i2], asr[j1].start, asr[j2 - 1].end)):
                times[i1 + k] = span
    # interpolate deletions (script words the recognizer missed)
    i = 0
    n = len(tokens)
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 and times[i - 1] else 0.0
        right = times[j][0] if j < n and times[j] else max(left + 0.3 * (j - i), audio_end)
        right = max(right, left + 0.05 * (j - i))
        for k, span in enumerate(_distribute(tokens[i:j], left, right)):
            times[i + k] = span
        i = j
    words = [TimedWord(t[0], t[1], tok, m) for tok, t, m in zip(tokens, times, matched_flags)]  # type: ignore[index]
    # enforce monotonic times
    for k in range(1, len(words)):
        if words[k].start < words[k - 1].end - 1e-3:
            words[k].start = words[k - 1].end
        if words[k].end < words[k].start:
            words[k].end = words[k].start + 0.05
    return words, matched / len(tokens)


def build_cues(words: list[TimedWord], *, max_chars: int = 84, max_dur: float = 6.0,
               min_dur: float = 0.8, gap_break: float = 0.6) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    cur: list[TimedWord] = []

    def flush() -> None:
        if cur:
            cues.append((cur[0].start, cur[-1].end, " ".join(w.text for w in cur)))
            cur.clear()

    for w in words:
        if cur:
            gap = w.start - cur[-1].end
            length = sum(len(x.text) + 1 for x in cur) + len(w.text)
            if gap > gap_break or length > max_chars or (w.end - cur[0].start) > max_dur:
                flush()
        cur.append(w)
        dur = cur[-1].end - cur[0].start
        text_len = sum(len(x.text) + 1 for x in cur)
        if SENTENCE_END.search(w.text) and dur >= min_dur:
            flush()
        elif CLAUSE_END.search(w.text) and text_len > max_chars * 0.6:
            flush()
    flush()
    # tidy: no overlaps, minimum display time where room allows
    out = []
    for i, (s, e, t) in enumerate(cues):
        nxt = cues[i + 1][0] if i + 1 < len(cues) else None
        if e - s < min_dur:
            e = s + min_dur if nxt is None else min(s + min_dur, nxt)
        if nxt is not None and e > nxt:
            e = nxt
        out.append((round(s, 3), round(max(e, s + 0.05), 3), t))
    return out


def split_sentences(script: str) -> list[str]:
    text = " ".join(script.split())
    parts = re.split(r"(?<=[.!?।…؟。！？])['\"”’)\]]*\s+", text)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------- engines
class FasterWhisperEngine(AlignmentEngine):
    id = "faster_whisper"
    label = "faster-whisper (local speech recognition)"

    def __init__(self, model_size: str = "small", device: str = "auto", compute_type: str = "auto",
                 download_root: str = "") -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root or None

    def available(self) -> tuple[bool, str]:
        if importlib.util.find_spec("faster_whisper") is None:
            return False, "faster-whisper is not installed (pip install -r requirements-alignment.txt)."
        return True, "faster-whisper installed."

    def load_model(self, local_only: bool = False):
        from faster_whisper import WhisperModel  # type: ignore

        return WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type,
                            download_root=self.download_root, local_files_only=local_only)

    def model_cached(self) -> bool:
        try:
            self.load_model(local_only=True)
            return True
        except Exception:
            return False

    def align(self, audio, script, language, *, method, progress, cancel):
        ok, why = self.available()
        if not ok:
            raise AlignmentError(why)
        progress(0.02, f"Loading speech model '{self.model_size}' (first run downloads it)…")
        try:
            model = self.load_model()
        except Exception as exc:
            raise AlignmentError(f"Could not load faster-whisper model '{self.model_size}': {exc}") from exc
        cancel.check()
        code = LANG_CODES.get((language or "").strip().lower())
        progress(0.08, "Transcribing narration…")
        segments, info = model.transcribe(str(audio), language=code, word_timestamps=True, beam_size=5,
                                          condition_on_previous_text=False, vad_filter=False)
        total = float(getattr(info, "duration", 0.0) or 0.0)
        asr: list[TimedWord] = []
        for seg in segments:
            cancel.check()
            for w in seg.words or []:
                txt = (w.word or "").strip()
                if txt:
                    asr.append(TimedWord(float(w.start), float(w.end), txt))
            if total:
                progress(0.08 + 0.85 * min(1.0, seg.end / total), f"Transcribing… {seg.end:.0f}/{total:.0f}s")
        if not asr:
            raise AlignmentError("No speech was recognized in the narration audio.")
        if method == "script" and script.strip():
            words, ratio = map_script_to_asr(script, asr, total or asr[-1].end)
            note = (f"Script-guided alignment: subtitle text is your script; timing comes from local speech recognition "
                    f"(faster-whisper {self.model_size}). {ratio:.0%} of script words matched the audio. Typical timing error "
                    f"is ~0.1–0.3 s — not millisecond-exact. Review before continuing.")
            warnings = [] if ratio >= 0.8 else [
                "Less than 80% of the script matched the audio. The narration may differ from the script, or the language setting may be wrong."]
            return AlignmentResult(words, self.id, self.model_size, "script", note, ratio, warnings)
        note = (f"Recognized-text subtitles from faster-whisper {self.model_size}. The text may differ from your script "
                f"(spelling, names, numbers). Review every cue.")
        return AlignmentResult(asr, self.id, self.model_size, "asr", note, None, [])


class EstimateEngine(AlignmentEngine):
    id = "estimate"
    label = "Estimated timing (no ML; uses pauses in the audio)"

    def __init__(self, ffmpeg: str | None, ffprobe: str | None) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def available(self) -> tuple[bool, str]:
        if not (self.ffmpeg and self.ffprobe):
            return False, "Needs FFmpeg and ffprobe."
        return True, "Always available (approximate)."

    def align(self, audio, script, language, *, method, progress, cancel):
        ok, why = self.available()
        if not ok:
            raise AlignmentError(why)
        if not script.strip():
            raise AlignmentError("Estimated timing needs the script text.")
        progress(0.1, "Measuring narration and pauses…")
        dur = probe(self.ffprobe, audio)["duration"]  # type: ignore[arg-type]
        if dur <= 0:
            raise AlignmentError("Could not read narration duration.")
        sil = silence_detect(self.ffmpeg, audio, -35.0, 0.18)  # type: ignore[arg-type]
        cancel.check()
        speech: list[tuple[float, float]] = []
        t = 0.0
        for a, b in sil:
            b = min(b, dur)
            if a - t > 0.08:
                speech.append((t, a))
            t = max(t, b)
        if dur - t > 0.08:
            speech.append((t, dur))
        if not speech:
            speech = [(0.0, dur)]
        sentences = split_sentences(script)
        progress(0.5, f"Distributing {len(sentences)} sentences over {len(speech)} speech regions…")
        spans: list[tuple[float, float]]
        if len(speech) == len(sentences):
            spans = speech
        else:
            # map sentences proportionally onto concatenated speech time, then convert back to real time
            total_speech = sum(b - a for a, b in speech)
            weights = [len(s) + 1 for s in sentences]
            wsum = sum(weights)

            def to_real(x: float) -> float:
                acc = 0.0
                for a, b in speech:
                    seg = b - a
                    if x <= acc + seg + 1e-9:
                        return a + (x - acc)
                    acc += seg
                return speech[-1][1]

            spans, acc = [], 0.0
            for w in weights:
                s0 = acc
                acc += total_speech * w / wsum
                spans.append((to_real(s0), to_real(acc)))
            # snap boundaries to nearby pauses
            centers = [((a + min(b, dur)) / 2) for a, b in sil]
            for k in range(len(spans) - 1):
                bnd = spans[k][1]
                near = min(centers, key=lambda c: abs(c - bnd)) if centers else None
                if near is not None and abs(near - bnd) < 0.7:
                    spans[k] = (spans[k][0], near)
                    spans[k + 1] = (near, spans[k + 1][1])
        words: list[TimedWord] = []
        for sent, (a, b) in zip(sentences, spans):
            toks = sent.split()
            for tok, (x, y) in zip(toks, _distribute(toks, a, b)):
                words.append(TimedWord(round(x, 3), round(y, 3), tok, False))
        progress(1.0, "Done")
        note = ("Estimated timing — no speech recognition was used. Sentence breaks follow pauses in the audio, but word "
                "timing is approximate and may drift. Review every cue (or install faster-whisper for real alignment).")
        warn = [] if len(speech) == len(sentences) else [
            f"Found {len(speech)} speech regions for {len(sentences)} sentences; timing was distributed proportionally."]
        return AlignmentResult(words, self.id, "silencedetect", "estimate", note, None, warn)


def create_engine(engine_id: str, *, settings, ffmpeg: str | None, ffprobe: str | None) -> AlignmentEngine:
    fw = FasterWhisperEngine(settings.whisper_model, settings.whisper_device, settings.whisper_compute_type,
                             settings.whisper_model_dir)
    if engine_id == "faster_whisper":
        return fw
    if engine_id == "estimate":
        return EstimateEngine(ffmpeg, ffprobe)
    return fw if fw.available()[0] else EstimateEngine(ffmpeg, ffprobe)


def now() -> float:
    return time.time()
