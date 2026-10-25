# ScriptReel Studio

A local-first Windows desktop app that turns a narration script into a finished educational video by driving
**G-Labs Voice Studio** (narration) and **G-Labs Studio** (images and video clips) through their documented
webhook APIs. Subtitles are aligned on your PC, and **FFmpeg** builds the final MP4.

```
script ─► Voice Studio (narration) ─► local alignment (editable SRT) ─► scene plan ─► LLM / manual prompts
       ─► G-Labs Studio images ─► G-Labs Studio clips (optional end-frame chaining) ─► FFmpeg ─► final MP4
                                                                              └─► optional YouTube package
```

Output in every project folder: `renders/final_animated_explainer.mp4`, the narration audio, `subtitles.srt`,
`project.json`, all generated assets (versioned, never overwritten) and an optional `youtube_metadata.md` / `.json`.

---

## 1. Requirements

| | |
|---|---|
| OS | Windows 10/11 (also runs on macOS/Linux for development) |
| Python | 3.11 or newer (64-bit) |
| G-Labs Voice Studio | running locally, **Webhook API** enabled |
| G-Labs Studio | running locally, **Webhook API** enabled (needs a MAX license), accounts logged in |
| FFmpeg + ffprobe | `winget install Gyan.FFmpeg`, or put `ffmpeg.exe`/`ffprobe.exe` in `bin\`, or choose paths in Settings |
| Optional | `faster-whisper` for real speech-based subtitle alignment |

## 2. Install and run

```bat
setup.bat      :: creates .venv, installs requirements (asks about faster-whisper)
run.bat        :: starts the app without a console window
```

Manual / other platforms:

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-alignment.txt   # optional, recommended
python -m scriptreel               # optionally: python -m scriptreel "C:\path\to\project folder"
```

## 3. Connect the two G-Labs apps

They are **separate apps with separate base URLs and separate API keys**.

| App | Default URL | Where to get the key |
|---|---|---|
| Voice Studio | `http://127.0.0.1:8766` | Voice Studio → Settings → Webhook API → Start, copy key |
| G-Labs Studio | `http://127.0.0.1:8765` | G-Labs Studio → Settings → Webhook API → Start, copy key |

In ScriptReel open **Connections & settings**, paste each key into its own card and press **Save key**, then
**Test connection**.

- Keys are stored in **Windows Credential Manager** (via `keyring`, service name `ScriptReel Studio`). They are
  never written to source, `project.json`, `settings.json`, logs, exported metadata or error dialogs. All log
  output passes through a redactor that also strips `X-API-Key` headers and base64 image payloads.
- **Clear all stored credentials** is in Settings → General. If no OS keyring is available the app keeps keys
  for the current session only and says so.
- Keep both servers on loopback (`127.0.0.1`). Do not expose them to the internet. ScriptReel itself opens no
  server ports.
- Generation runs on the accounts you are logged into **inside G-Labs Studio** and uses their quotas and plan
  limits. ScriptReel cannot see or change those accounts.

**Refresh connections** only calls `GET /api/health` and an authenticated read (`GET /api/voices` for Voice
Studio, `GET /api/tasks` for G-Labs Studio) to verify the key. It does **not** fetch model names — see §5.

## 4. Workflow (pages)

1. **Welcome** – new / recent / open project folder, live connection status and a setup checklist.
2. **Connections & settings** – URLs, keys, prompt LLM, FFmpeg, alignment engine, polling/timeouts, output folder,
   interface language (English / বাংলা), model catalog viewer.
3. **Project setup** – title, script (`.txt`/`.md` import), voice preset, language, image model, video model/mode,
   16:9 or 9:16, speed, Flexible vs Fixed-8 s clips, subtitles burn-in, YouTube package, style & character
   continuity, resolution, manual vs automatic run.
4. **Narration & voice** – presets from `GET /api/voices` (name + tags), language, speed, WAV/MP3, optional
   quality steps, short voice preview, generate, task status, waveform player, all takes kept.
5. **Subtitles** – local alignment, editable cue table (add / split / merge / delete / auto-fix / import / export),
   overlap and negative-time validation, precision note, *Mark reviewed & continue*. `subtitles.srt` is always
   exported, even when subtitles are not burned in.
6. **Scenes & prompts** – scene segmentation from subtitle timing (Flexible 3–10 s or Fixed 8 s) that respects the
   model's native clip lengths, LLM prompt writing (all / missing / per scene), offline draft, manual editing,
   split / merge / delete / retime, per-scene model & mode overrides, style & character bible with reference
   images, optional *review prompts before generation*.
7. **Images** – grid with prompt, model, preview and task state; generate missing / selected / all; upload your
   own; versions; approval gate (review mode).
8. **Video clips** – global default and per-scene overrides, grouped by API route, native length/trim plan,
   optional chaining, generate missing / selected, queue status with remote task IDs, documented fallbacks.
9. **Edit & export** – preview, timeline (scenes / waveform / subtitles, drag cuts), reorder visuals, trim
   leading edge, Fill/Fit with focal point, safe zones, subtitle style, narration volume, background music with
   ducking, resolution / fps / CRF / preset, render with progress and cancel, editable output file name.
10. **YouTube package** – 3–5 titles, SEO description, chapters from the final scene timing, tags, hashtags,
    thumbnail concept + prompt (and optional thumbnail generation). Never blocks the render.

**Automatic mode** (`Run automatically` in the header) runs every remaining step and stops only on errors or on
review points you enabled. **Review mode** lets you approve prompts and images before continuing. The activity
panel at the bottom shows running tasks (with stop buttons) and a timestamped, redacted log.

## 5. Supported APIs (and what is deliberately *not* used)

Source of truth: the official webhook docs
([G-Labs Studio](https://github.com/duckmartians/G-Labs-Automation/blob/main/WEBHOOK_INTEGRATION.en.md),
[Voice Studio](https://github.com/duckmartians/G-Labs-Voice-Studio/blob/main/WEBHOOK_INTEGRATION.en.md)).

| Purpose | Call |
|---|---|
| Health | `GET /api/health` (both apps, no key) |
| Voice presets | `GET {voice}/api/voices` |
| Narration | `POST {voice}/api/voice/design` `{preset_id, script, language, speed, output_format}` |
| Images | `POST {glabs}/api/image/generate` (`model` = `nano_banana_*`), `/api/openai/generate` (GPT Image 2), `/api/grok/generate` (`t2i`/`i2i`), `/api/meta/generate` |
| Veo / Omni clips | `POST {glabs}/api/video/generate` with `model` + `mode` (`text_to_video`, `start_image`, `start_end_image`) |
| Grok clips | `POST {glabs}/api/grok/generate` with `mode` `t2v` / `i2v` (modes, not model IDs) |
| Meta clips | `POST {glabs}/api/meta/generate` with `mode` `t2v` / `i2v` |
| Polling | `GET /api/status/{task_id}` with `X-API-Key` |
| Results | the `/api/files/...` URLs in `results` (no key needed) |
| Key check | `GET {glabs}/api/tasks` |

Behaviour details:

- All generation is asynchronous: submit → keep `task_id` (saved in `project.json`) → poll → download.
- Timeouts are configurable. Only safe transient errors are retried (connection refused, GET timeouts, 502/503/504).
  POSTs are not re-sent after a timeout, to avoid duplicate paid tasks.
- 401 / 403 / 404 / 413 / 429 and provider task failures are mapped to clear messages with hints. Failed tasks stay
  visible on their scene; other scenes are not affected.
- **Not used because not documented:** a model-list endpoint (`/api/models` does not exist), task cancellation,
  and SRT output from Voice Studio. *Stop* therefore only stops polling here; the remote task may still finish
  and use quota (the UI says so).
- Tasks live in the G-Labs apps' memory. If an app restarts, polling an old `task_id` returns 404 → shown as
  **Lost** with a *generate again* hint. Tasks interrupted by closing ScriptReel are marked **Interrupted** and can be
  resumed with **Resume** while the remote app still knows them.
- Request bodies are capped below the documented 50 MB limit. Reference images are sent as local file paths when
  G-Labs runs on the same PC, otherwise as base64 (Settings → Generation → Reference transfer).

## 6. Model catalog (`scriptreel/config/model_catalog.json`)

Because there is no documented model-list API, image models and video options come from a **versioned local
catalog**. Being listed in the catalog does not mean a model is available to your accounts; G-Labs reports that
when you generate.

Each entry contains: `id`, `label`, `route`, `request_style`, `model` **or** `modes`, `aspect_ratios`,
`durations` / `ultra_durations`, `resolutions` / `ultra_resolutions`, `max_reference_images`, `requirements`
(account / plan), `supports_end_frame` (chaining), `notes`, `doc_section`, `enabled`. The file also stores
`catalog_version`, `updated`, `verified_against` and `sources`.

Initial entries: images `nano_banana_pro`, `nano_banana_2`, `nano_banana_2_lite`, `gpt_image_2`, Grok and Meta
images; video `veo_31_fast`, `veo_31_lite`, `veo_31_quality`, `veo_31_lite_relaxed`, `omni_flash`, `omni_vids`
(**disabled by default** – enable only if your G-Labs version supports it), Grok video (`t2v`/`i2v`) and Meta video.

**Editing:** Settings → Model catalog → **Edit** copies the catalog to your user folder
(`%APPDATA%\ScriptReel\model_catalog.json`) and opens it. Your copy takes precedence; **Reload** applies changes,
**Reset** restores the bundled version (your copy is kept as `model_catalog.previous.json`). The loader validates
every entry: unknown routes are disabled, Grok/Meta entries may not carry a `model` value, and invalid files fall
back to the bundled catalog with a warning. The **ULTRA** checkbox in Settings unlocks options the docs mark as
ULTRA-only (4 s / 6 s Veo clips, 4K). The app never silently switches the model you chose; if a mode is
unsupported it shows the documented fallback as a button.

## 7. Subtitle alignment

Voice Studio returns audio only, so subtitle timing is created locally by a replaceable engine
(`services/alignment.py`, interface `AlignmentEngine`).

| Engine | How | Precision |
|---|---|---|
| **faster-whisper** (recommended) | local speech recognition with word timestamps; in *Script-guided* mode the recognized words are sequence-aligned to your original script, so the text is exactly your script and the timing comes from the audio | typically 0.1–0.3 s, not millisecond-perfect |
| **Estimate** (no ML) | FFmpeg `silencedetect` finds the pauses Voice Studio leaves between sentences and distributes the script over the speech regions | approximate – always review |

Setup: `pip install -r requirements-alignment.txt`, then Settings → Alignment: pick the model size
(`tiny`…`large-v3`, default `small`), device (`auto`/`cpu`/`cuda`) and an optional model folder, and press
**Download model** (or let it download on first use). The Subtitles page always shows which engine produced the
cues and how much to trust them. Every cue is editable before scene planning.

To add another engine (e.g. a forced aligner), subclass `AlignmentEngine` and register it in `create_engine()`.

## 8. Prompt LLM (optional)

Settings → Prompt generation. Providers are adapters behind `PromptProvider` (`services/prompt_provider.py`):
**Google Antigravity CLI (agy)**, **9router**, **OpenAI-compatible** (OpenAI, OpenRouter, Ollama, LM Studio…;
set base URL + model), **Google Gemini**, **Anthropic Claude**, or **None**. Keys go to Credential Manager. With
no provider you can draft prompts from the narration offline or write them yourself; YouTube metadata then
contains chapters only. The ⟳ button next to *Model* pulls the provider's model list (OpenAI-compatible
`GET {base}/models`, or `agy models`); you can always type a model ID instead.

**Google Antigravity CLI (`agy`)** — uses the Google account you signed into in the CLI (e.g. Google AI Pro), no
API key. Install the CLI, run `agy` once in a terminal and sign in. ScriptReel then runs, in an empty temporary
folder and without a console window:

```text
agy models                                                      # model list (id <TAB> label)
agy --output-format json --sandbox --disable-slash-commands \
    --print-timeout 300s --model <id>      < prompt-on-stdin     # one non-interactive turn
```

and reads `response` from the JSON result. Temperature does not apply (the effort level is part of the model ID,
e.g. `gemini-3.8-flash-high`). If `agy` is not on the GUI app's PATH, ScriptReel also looks in `~/.local/bin`;
otherwise set the path in the *agy executable* field. Usage counts against that account's plan.

**9router** ([9router.com](https://9router.com), local AI gateway) — `npm install -g 9router`, start it with
`9router` (dashboard at `http://localhost:20128`), connect your accounts there (Antigravity → `ag/…` models, Codex →
`cx/…`, …) and create an API key in the dashboard. In ScriptReel choose *9router*, paste that key, press ⟳ and pick
a model. Base URL defaults to `http://localhost:20128/v1` (OpenAI-compatible). The gateway must be running while
ScriptReel writes prompts.

## 9. Scenes, chaining and timing

- Scenes always tile the narration timeline. Cuts are placed in pauses, preferring sentence ends.
- For each scene the app picks the shortest native clip length ≥ the scene length and trims the rest. If a scene is
  longer than any native length, the last frame is held. The plan is shown per scene ("generate 8 s · ✂ trim 1.5 s").
- **Chaining** (optional, for models with `supports_end_frame`): (1) extract the last clean frame of clip N with
  FFmpeg, (2) send it as the start image of scene N+1, (3) drop the duplicated first frame of clip N+1 when editing.
  Chained clips are generated one after another.
- The final video has exactly `round(narration_seconds × fps)` frames. The export page and the render report show
  the frame-rounding difference in milliseconds.
- Burned-in subtitles need an FFmpeg build with libass (`subtitles` filter). Without it the app adds a selectable
  subtitle track instead and tells you.

## 10. Projects

A project is a plain folder – no database:

```
My Project/
  project.json          schema-versioned, relative paths, task IDs, statuses (never keys)
  script.txt
  narration.wav|mp3     selected take (all takes in assets/voice/)
  subtitles.srt
  assets/images/  assets/videos/  assets/frames/  assets/refs/  assets/voice/
  renders/final_animated_explainer.mp4
  youtube_metadata.md / .json   (optional)
```

Save (Ctrl+S), Save As (copies the folder), Open (Ctrl+O), autosave, and resume. Regenerating never overwrites:
new files get `_v2`, `_v3`… and you choose which version to use. Replacing a render asks first. Newer/older
schema versions are migrated or opened in compatibility mode.

## 11. Development and tests

```bash
pip install -r requirements-dev.txt
pytest -q                                   # unit + client + full end-to-end pipeline
```

`tools/mock_glabs_servers.py` is a **development-only** mock of the documented endpoints of both apps (synthetic
voice, gradient images, pan clips via FFmpeg; inject failures with `FAIL401`, `FAIL403`, `FAIL429`, `FAILTASK` in
a prompt or script):

```bash
python tools/mock_glabs_servers.py --voice-key test-voice --glabs-key test-glabs
```

Then point the app at the default URLs and save those test keys. Use `SCRIPTREEL_CONFIG_DIR=.devconfig` to keep
dev settings separate from your real ones.

Code layout:

```
scriptreel/
  app/controller.py        workflow orchestration (GUI thread owns the project; workers do I/O)
  workers/jobs.py          QThreadPool job manager, progress signals, cancellation
  services/                voice_studio_client, glabs_client, http_base, alignment, srt, scene_planner,
                           prompt_provider, video_renderer, ffmpeg_tools, project_store, youtube_package
  core/                    settings, secrets (keyring), logging + redaction, project schema, catalog, i18n
  ui/                      main_window, pages/, widgets, media players, timeline, activity panel, theme
  config/model_catalog.json, config/i18n/bn.json
tools/mock_glabs_servers.py
tests/
```

## 12. Packaging (Windows)

```bat
build_windows.bat
```

This creates `dist\ScriptReel Studio\ScriptReel Studio.exe` (PyInstaller one-folder build using
`ScriptReel.spec`; the catalog, translations and icons are bundled). FFmpeg is **not** bundled by default. If
`bin\ffmpeg.exe` / `bin\ffprobe.exe` exist they are copied next to the exe — only do this if you comply with the
license of that FFmpeg build (LGPL/GPL) and ship its license text. faster-whisper models are downloaded to the
user's cache, not bundled.

## 13. Localization

The interface is English by default, with a Bengali (বাংলা) translation table in `config/i18n/bn.json`
(navigation, steps, page titles, main actions). Missing strings fall back to English. Switch in Settings → General
and restart. To add a language, add `config/i18n/<code>.json` mapping English source text to translations and
register the code in `core/i18n.py`.

## 14. Known limitations

- No documented model list, cancel endpoint or SRT output in the G-Labs APIs (see §5); the app works around them
  and says so in the UI.
- Remote tasks are in-memory in the G-Labs apps; a restart of those apps loses running tasks (shown as *Lost*).
- Model availability, quotas and plan restrictions are decided by G-Labs and your logged-in accounts.
- Subtitle timing is as good as the alignment engine (§7); review it before planning scenes.
- Burned-in subtitles require FFmpeg with libass.
