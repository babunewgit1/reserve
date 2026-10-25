"""Optional YouTube metadata package (titles, description, chapters, tags)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .http_base import CancelToken
from .prompt_provider import PromptProvider

log = logging.getLogger("scriptreel.youtube")

YT_SYSTEM = """You are a YouTube SEO specialist for educational explainer videos.
Return ONLY JSON with keys:
"titles": 3-5 compelling titles (max 70 chars each),
"description": an SEO-focused description (2-4 short paragraphs, include key terms naturally, a call to action; no chapter list),
"chapter_titles": one short title per provided chapter, same order,
"tags": 10-20 search tags,
"hashtags": 3-5 hashtags starting with #,
"thumbnail_concept": one paragraph describing a high-CTR thumbnail,
"thumbnail_prompt": an image-generation prompt for that thumbnail (no text in image)."""


def fmt_chapter_ts(t: float) -> str:
    t = int(t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_chapters(scenes: list[tuple[float, float, str]], min_len: float = 10.0) -> list[dict]:
    """YouTube rules: first chapter at 0:00, ≥3 chapters, each ≥10 s."""
    if not scenes:
        return []
    chapters: list[dict] = []
    cur = {"start": 0.0, "end": scenes[0][1], "text": scenes[0][2]}
    for s, e, text in scenes[1:]:
        if cur["end"] - cur["start"] < min_len * 1.5:
            cur["end"] = e
            cur["text"] += " " + text
        else:
            chapters.append(cur)
            cur = {"start": s, "end": e, "text": text}
    if chapters and cur["end"] - cur["start"] < min_len:
        chapters[-1]["end"] = cur["end"]
        chapters[-1]["text"] += " " + cur["text"]
    else:
        chapters.append(cur)
    if len(chapters) < 3:
        return []
    for c in chapters:
        words = c["text"].split()
        c["title"] = " ".join(words[:6]).rstrip(",.;:") + ("…" if len(words) > 6 else "")
    return chapters


def generate(provider: PromptProvider | None, *, title: str, script: str, chapters: list[dict],
             cancel: CancelToken) -> tuple[dict, str]:
    """Return (data, warning). Falls back to local data if the LLM fails."""
    data: dict = {"titles": [title], "description": "", "tags": [], "hashtags": [],
                  "thumbnail_concept": "", "thumbnail_prompt": "",
                  "chapters": [{"time": fmt_chapter_ts(c["start"]), "start": c["start"], "title": c["title"]} for c in chapters]}
    if provider is None or not provider.configured:
        return data, "No prompt LLM configured — only chapters were generated locally."
    cancel.check()
    user = "\n".join([
        f"Working title: {title}", "", "Narration script:", script[:6000], "",
        "Chapters (start time — opening words):",
        *[f"{i + 1}. {fmt_chapter_ts(c['start'])} — {c['text'][:160]}" for i, c in enumerate(chapters)],
    ])
    try:
        res = provider.complete_json(YT_SYSTEM, user)
    except Exception as exc:
        log.warning("YouTube metadata LLM call failed: %s", exc)
        return data, f"LLM metadata generation failed ({exc}); chapters were generated locally."
    if isinstance(res, dict):
        for k in ("titles", "description", "tags", "hashtags", "thumbnail_concept", "thumbnail_prompt"):
            if res.get(k):
                data[k] = res[k]
        ct = res.get("chapter_titles") or []
        for i, c in enumerate(data["chapters"]):
            if i < len(ct) and str(ct[i]).strip():
                c["title"] = str(ct[i]).strip()
    return data, ""


def to_markdown(data: dict, video_title: str) -> str:
    out = [f"# YouTube package — {video_title}", "", "## Title options"]
    out += [f"{i + 1}. {t}" for i, t in enumerate(data.get("titles") or [])]
    out += ["", "## Description", "", data.get("description") or "_(not generated)_", ""]
    chapters = data.get("chapters") or []
    out.append("## Chapters")
    if chapters:
        out += ["", *[f"{c['time']} {c['title']}" for c in chapters]]
    else:
        out.append("_(video too short for YouTube chapters: needs ≥3 chapters of ≥10 s)_")
    out += ["", "## Tags", "", ", ".join(data.get("tags") or []) or "_(not generated)_",
            "", "## Hashtags", "", " ".join(data.get("hashtags") or []) or "_(not generated)_",
            "", "## Thumbnail", "", f"**Concept:** {data.get('thumbnail_concept') or '—'}", "",
            f"**Image prompt:** {data.get('thumbnail_prompt') or '—'}", ""]
    return "\n".join(out)


def export(folder: Path, data: dict, video_title: str) -> tuple[Path, Path]:
    md = Path(folder) / "youtube_metadata.md"
    js = Path(folder) / "youtube_metadata.json"
    md.write_text(to_markdown(data, video_title), encoding="utf-8")
    js.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return md, js
