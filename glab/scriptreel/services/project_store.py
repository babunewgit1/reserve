"""Project folders and project.json persistence (no database)."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from pathlib import Path

from .. import __version__
from ..core.project import Project, migrate
from .srt import write_srt

log = logging.getLogger("scriptreel.store")

PROJECT_FILE = "project.json"
SUBDIRS = ("assets/images", "assets/videos", "assets/frames", "assets/refs", "assets/voice", "renders", "cache")


class ProjectLoadError(Exception):
    pass


def slugify(title: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", title, flags=re.U).strip()
    s = re.sub(r"\s+", "_", s)
    return s[:60] or "project"


def is_project_folder(folder: Path) -> bool:
    return (Path(folder) / PROJECT_FILE).is_file()


def rel_path(folder: Path, path: Path) -> str:
    path = Path(path).resolve()
    try:
        return path.relative_to(Path(folder).resolve()).as_posix()
    except ValueError:
        return str(path)  # outside the project (e.g. music file) → absolute


def abs_path(folder: Path, rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else Path(folder) / p


def next_version_path(folder: Path, subdir: str, stem: str, ext: str) -> Path:
    d = Path(folder) / subdir
    d.mkdir(parents=True, exist_ok=True)
    ext = ext if ext.startswith(".") else "." + ext
    n = 1
    while True:
        p = d / f"{stem}_v{n}{ext}"
        if not p.exists() and not p.with_name(p.name + ".part").exists():
            return p
        n += 1


def create_project(parent: Path, title: str) -> tuple[Project, Path]:
    parent = Path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    base = slugify(title)
    folder = parent / base
    n = 2
    while folder.exists():
        folder = parent / f"{base}_{n}"
        n += 1
    folder.mkdir()
    for sd in SUBDIRS:
        (folder / sd).mkdir(parents=True, exist_ok=True)
    project = Project()
    project.settings.title = title
    save_project(project, folder)
    log.info("Created project '%s' at %s", title, folder)
    return project, folder


def load_project(folder: Path) -> tuple[Project, list[str]]:
    folder = Path(folder)
    notes: list[str] = []
    candidates = [folder / PROJECT_FILE, folder / (PROJECT_FILE + ".bak")]
    last_exc: Exception | None = None
    for i, p in enumerate(candidates):
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data, mig = migrate(data)
            notes += mig
            project = Project.model_validate(data)
            if i == 1:
                notes.append("project.json was damaged; the automatic backup was opened instead.")
            for sd in SUBDIRS:
                (folder / sd).mkdir(parents=True, exist_ok=True)
            script_file = folder / "script.txt"
            if not project.script and script_file.exists():
                project.script = script_file.read_text(encoding="utf-8")
            return project, notes
        except Exception as exc:  # try the backup
            last_exc = exc
            log.error("Could not read %s: %s", p.name, exc)
    raise ProjectLoadError(f"No readable project.json in {folder}: {last_exc}")


def save_project(project: Project, folder: Path) -> None:
    folder = Path(folder)
    project.updated_at = time.time()
    project.app_version = __version__
    target = folder / PROJECT_FILE
    tmp = folder / (PROJECT_FILE + ".tmp")
    tmp.write_text(project.model_dump_json(indent=2), encoding="utf-8")
    if target.exists():
        try:
            shutil.copyfile(target, folder / (PROJECT_FILE + ".bak"))
        except OSError:
            pass
    os.replace(tmp, target)
    (folder / "script.txt").write_text(project.script or "", encoding="utf-8")
    if project.cues:
        try:
            write_srt(folder / "subtitles.srt", project.cues)
        except OSError as exc:
            log.warning("Could not write subtitles.srt: %s", exc)


def save_project_as(project: Project, src: Path, dest: Path) -> Path:
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"{dest} is not empty")
    shutil.copytree(src, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("cache", "*.part", "_render_work"))
    save_project(project, dest)
    return dest


def project_summary(folder: Path) -> dict:
    """Light-weight info for the recent-projects list."""
    try:
        data = json.loads((Path(folder) / PROJECT_FILE).read_text(encoding="utf-8"))
        scenes = data.get("scenes") or []
        return {
            "title": (data.get("settings") or {}).get("title") or Path(folder).name,
            "updated_at": data.get("updated_at") or 0,
            "scenes": len(scenes),
            "clips": sum(1 for s in scenes if s.get("videos")),
            "aspect": (data.get("settings") or {}).get("aspect_ratio", ""),
            "rendered": bool((data.get("render") or {}).get("last_output")),
            "ok": True,
        }
    except Exception:
        return {"title": Path(folder).name, "ok": False}
