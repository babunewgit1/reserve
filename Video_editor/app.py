#!/usr/bin/env python3
"""
Follow Please — Web UI Backend (v2)
Flask server with live Canva-style preview, X/Y positioning, and batch processing.
"""

import os
import sys
import base64
import subprocess
import time
import tempfile
import threading
import uuid
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("❌ Pillow লাগবে: pip3 install Pillow")
    sys.exit(1)

app = Flask(__name__)

# ─── Global State ───
jobs = {}
_overlay_cache = {}
_temp_dir = tempfile.mkdtemp(prefix="follow_text_")

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv",
    ".wmv", ".webm", ".m4v", ".ts", ".mts",
}

DEFAULT_CONFIG = {
    "text": "Follow Please",
    "start_time": 0,
    "end_time": 2.5,
    "fade": 0.4,
    "fontsize": 52,
    "workers": 4,
    "text_color": "#ffffff",
    "box_color": "#ffd700",
    "box_opacity": 0.86,
    "x_percent": 50,   # 0-100, center of text box
    "y_percent": 50,   # 0-100, center of text box
    "padding_x": 30,
    "padding_y": 18,
    "border_radius": 12,
    "use_gpu": True,
}


def hex_to_rgba(hex_color, alpha=255):
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return (r, g, b, alpha)


def create_text_overlay(config, temp_dir):
    """Create transparent PNG with text overlay box"""
    text = config.get("text", "Follow Please")
    fontsize = config.get("fontsize", 52)
    padding_x = config.get("padding_x", 30)
    padding_y = config.get("padding_y", 18)
    text_color = hex_to_rgba(config.get("text_color", "#ffffff"))
    box_alpha = int(config.get("box_opacity", 0.86) * 255)
    box_color = hex_to_rgba(config.get("box_color", "#ffd700"), box_alpha)
    radius = config.get("border_radius", 12)

    font = None
    font_paths = [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/SFNS.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, fontsize)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    temp_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp_img)
    bbox = temp_draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    img_w = text_w + padding_x * 2
    img_h = text_h + padding_y * 2
    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle(
        [0, 0, img_w - 1, img_h - 1],
        radius=radius,
        fill=box_color,
    )

    text_x = padding_x - bbox[0]
    text_y = padding_y - bbox[1]
    draw.text((text_x, text_y), text, font=font, fill=text_color)

    overlay_path = os.path.join(temp_dir, "overlay.png")
    img.save(overlay_path, "PNG")
    return overlay_path


def get_video_files(input_dir):
    videos = []
    input_path = Path(input_dir)
    if not input_path.is_dir():
        return videos
    for f in sorted(input_path.iterdir()):
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            videos.append({
                "path": str(f),
                "name": f.name,
                "size": f.stat().st_size,
            })
    return videos


def process_single_video(input_file, overlay_path, output_file, config, job_id, video_index):
    """Process a single video with GPU/CPU encoding, pause/stop support"""
    job = jobs[job_id]

    # ─── Check cancel before starting ───
    if job.get("cancelled"):
        job["videos"][video_index]["status"] = "cancelled"
        return

    # ─── Wait if paused ───
    pause_event = job.get("pause_event")
    if pause_event:
        pause_event.wait()  # blocks if paused

    # Check cancel again after unpause
    if job.get("cancelled"):
        job["videos"][video_index]["status"] = "cancelled"
        return

    start_time_cfg = config.get("start_time", 0)
    end_time_cfg = config.get("end_time", 2.5)
    fade = config.get("fade", 0.4)
    use_gpu = config.get("use_gpu", True)

    x_pct = config.get("x_percent", 50)
    y_pct = config.get("y_percent", 50)
    x_expr = f"(W-w)*{x_pct}/100"
    y_expr = f"(H-h)*{y_pct}/100"

    filter_complex = (
        f"[1:v]format=rgba,"
        f"fade=t=in:st={start_time_cfg}:d={fade}:alpha=1,"
        f"fade=t=out:st={end_time_cfg - fade}:d={fade}:alpha=1"
        f"[overlay];"
        f"[0:v][overlay]overlay="
        f"x={x_expr}:y={y_expr}:"
        f"enable='between(t,{start_time_cfg},{end_time_cfg})'"
        f"[outv]"
    )

    # ─── GPU vs CPU encoding ───
    if use_gpu:
        encode_args = ["-c:v", "h264_videotoolbox", "-q:v", "65"]
    else:
        encode_args = ["-c:v", "libx264", "-crf", "18", "-preset", "medium"]

    cmd = [
        "ffmpeg",
        "-i", input_file,
        "-loop", "1",
        "-i", overlay_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",
        *encode_args,
        "-codec:a", "copy",
        "-shortest",
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        output_file,
    ]

    job["videos"][video_index]["status"] = "processing"
    proc_start = time.time()

    try:
        # Use Popen so we can kill on stop
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        # Track active process for stop/kill
        job.setdefault("_active_procs", []).append(proc)

        # Wait for completion, checking cancel periodically
        while proc.poll() is None:
            if job.get("cancelled"):
                proc.kill()
                job["videos"][video_index]["status"] = "cancelled"
                # Clean up partial output
                try:
                    if os.path.exists(output_file):
                        os.remove(output_file)
                except OSError:
                    pass
                return
            # Wait if paused
            if pause_event and not pause_event.is_set():
                proc.send_signal(19)  # SIGSTOP — pause ffmpeg
                pause_event.wait()    # wait until resumed
                proc.send_signal(18)  # SIGCONT — resume ffmpeg
            time.sleep(0.2)

        elapsed = time.time() - proc_start
        stderr_out = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""

        if proc.returncode == 0:
            output_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
            job["videos"][video_index]["status"] = "done"
            job["videos"][video_index]["time"] = round(elapsed, 1)
            job["videos"][video_index]["output_size"] = output_size
        else:
            job["videos"][video_index]["status"] = "error"
            job["videos"][video_index]["error"] = stderr_out.strip()[:200]

        # Remove from active procs
        if proc in job.get("_active_procs", []):
            job["_active_procs"].remove(proc)

    except Exception as e:
        job["videos"][video_index]["status"] = "error"
        job["videos"][video_index]["error"] = str(e)[:200]

    done_count = sum(1 for v in job["videos"] if v["status"] in ("done", "error", "cancelled"))
    job["completed"] = done_count
    job["progress"] = round(done_count / job["total"] * 100, 1)


def run_batch_job(job_id):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    job = jobs[job_id]
    config = job["config"]
    output_dir = job["output_dir"]

    os.makedirs(output_dir, exist_ok=True)
    job["status"] = "running"
    job["start_time"] = time.time()

    with tempfile.TemporaryDirectory(prefix="follow_text_") as temp_dir:
        overlay_path = create_text_overlay(config, temp_dir)

        workers = config.get("workers", 4)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for i, video in enumerate(job["videos"]):
                # Skip if cancelled
                if job.get("cancelled"):
                    video["status"] = "cancelled"
                    continue

                input_file = video["path"]
                output_file = os.path.join(output_dir, video["name"])
                if os.path.abspath(input_file) == os.path.abspath(output_file):
                    name, ext = os.path.splitext(video["name"])
                    output_file = os.path.join(output_dir, f"{name}_follow{ext}")

                video["output_path"] = output_file
                future = executor.submit(
                    process_single_video,
                    input_file, overlay_path, output_file,
                    config, job_id, i
                )
                futures[future] = i

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass

    # Mark remaining pending videos as cancelled if job was stopped
    if job.get("cancelled"):
        for v in job["videos"]:
            if v["status"] == "pending":
                v["status"] = "cancelled"
        job["status"] = "stopped"
    else:
        job["status"] = "completed"

    job["end_time"] = time.time()
    job["elapsed"] = round(job["end_time"] - job["start_time"], 1)
    success = sum(1 for v in job["videos"] if v["status"] == "done")
    cancelled = sum(1 for v in job["videos"] if v["status"] == "cancelled")
    job["success_count"] = success
    job["error_count"] = job["total"] - success - cancelled
    job["cancelled_count"] = cancelled


# ═══════════════════════════════════════
#  Routes
# ═══════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/browse", methods=["POST"])
def browse_directory():
    data = request.json or {}
    path = data.get("path", os.path.expanduser("~"))
    if not os.path.isdir(path):
        path = os.path.expanduser("~")

    try:
        items = []
        for entry in sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.name.startswith('.'):
                continue
            item = {
                "name": entry.name,
                "path": entry.path,
                "is_dir": entry.is_dir(),
            }
            if entry.is_file():
                try:
                    item["size"] = entry.stat().st_size
                except OSError:
                    item["size"] = 0
            items.append(item)

        parent = str(Path(path).parent)
        return jsonify({"current": path, "parent": parent, "items": items})
    except PermissionError:
        return jsonify({"error": "Permission denied", "current": path, "items": []}), 403


@app.route("/api/scan", methods=["POST"])
def scan_videos():
    data = request.json or {}
    input_dir = data.get("input_dir", "")
    if not input_dir or not os.path.isdir(input_dir):
        return jsonify({"error": "Invalid directory path"}), 400

    videos = get_video_files(input_dir)
    return jsonify({"count": len(videos), "videos": videos, "input_dir": input_dir})


@app.route("/api/preview-frame", methods=["POST"])
def preview_frame():
    """Extract a frame from a video and return as base64 JPEG for the live preview"""
    data = request.json or {}
    video_path = data.get("video_path", "")
    timestamp = data.get("timestamp", 1)  # default: 1 second in

    if not video_path or not os.path.isfile(video_path):
        return jsonify({"error": "Video file not found"}), 400

    frame_path = os.path.join(_temp_dir, f"preview_{uuid.uuid4().hex[:8]}.jpg")

    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "3",
            "-hide_banner", "-loglevel", "error",
            frame_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

        if result.returncode != 0 or not os.path.exists(frame_path):
            return jsonify({"error": "Failed to extract frame"}), 500

        # Read and encode as base64
        with open(frame_path, "rb") as f:
            frame_data = base64.b64encode(f.read()).decode("utf-8")

        # Get dimensions
        img = Image.open(frame_path)
        width, height = img.size
        img.close()

        # Cleanup
        try:
            os.remove(frame_path)
        except OSError:
            pass

        return jsonify({
            "frame": frame_data,
            "width": width,
            "height": height,
            "mime": "image/jpeg",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/generate-preview", methods=["POST"])
def generate_preview():
    """Generate a full preview image (frame + overlay) server-side"""
    data = request.json or {}
    config = {**DEFAULT_CONFIG, **data.get("config", {})}
    video_path = data.get("video_path", "")

    # Create background
    width = data.get("width", 1080)
    height = data.get("height", 1920)

    if video_path and os.path.isfile(video_path):
        # Extract frame
        frame_path = os.path.join(_temp_dir, f"gen_preview_{uuid.uuid4().hex[:8]}.jpg")
        try:
            cmd = [
                "ffmpeg", "-y", "-ss", "1",
                "-i", video_path,
                "-frames:v", "1", "-q:v", "3",
                "-hide_banner", "-loglevel", "error",
                frame_path,
            ]
            subprocess.run(cmd, capture_output=True, timeout=15)
            if os.path.exists(frame_path):
                bg = Image.open(frame_path).convert("RGBA")
                width, height = bg.size
            else:
                bg = _create_demo_background(width, height)
        except Exception:
            bg = _create_demo_background(width, height)
        finally:
            try:
                os.remove(frame_path)
            except OSError:
                pass
    else:
        bg = _create_demo_background(width, height)

    # Create overlay
    overlay_path = create_text_overlay(config, _temp_dir)
    overlay = Image.open(overlay_path).convert("RGBA")

    # Position overlay
    x_pct = config.get("x_percent", 50)
    y_pct = config.get("y_percent", 50)
    max_x = max(width - overlay.width, 0)
    max_y = max(height - overlay.height, 0)
    pos_x = int(max_x * x_pct / 100)
    pos_y = int(max_y * y_pct / 100)

    # Composite
    result = bg.copy()
    result.paste(overlay, (pos_x, pos_y), overlay)

    # Scale down for preview (max 600px wide)
    max_preview = 600
    if width > max_preview:
        scale = max_preview / width
        new_w = int(width * scale)
        new_h = int(height * scale)
        result = result.resize((new_w, new_h), Image.LANCZOS)

    # Encode
    import io
    buf = io.BytesIO()
    result.convert("RGB").save(buf, format="JPEG", quality=85)
    buf.seek(0)
    frame_data = base64.b64encode(buf.read()).decode("utf-8")

    return jsonify({
        "preview": frame_data,
        "width": width,
        "height": height,
        "overlay_width": overlay.width,
        "overlay_height": overlay.height,
        "mime": "image/jpeg",
    })


def _create_demo_background(width, height):
    """Create a demo gradient background to show preview"""
    img = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(img)

    # Dark gradient background
    for y in range(height):
        ratio = y / height
        r = int(15 + 20 * ratio)
        g = int(10 + 15 * ratio)
        b = int(30 + 25 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    # Subtle grid pattern
    for x in range(0, width, 40):
        draw.line([(x, 0), (x, height)], fill=(255, 255, 255, 12))
    for y in range(0, height, 40):
        draw.line([(0, y), (width, y)], fill=(255, 255, 255, 12))

    # Center crosshair
    cx, cy = width // 2, height // 2
    draw.line([(cx - 30, cy), (cx + 30, cy)], fill=(255, 255, 255, 40), width=1)
    draw.line([(cx, cy - 30), (cx, cy + 30)], fill=(255, 255, 255, 40), width=1)

    return img


@app.route("/api/start", methods=["POST"])
def start_job():
    data = request.json or {}
    input_dir = data.get("input_dir", "")
    output_dir = data.get("output_dir", "")
    config = {**DEFAULT_CONFIG, **data.get("config", {})}

    if not input_dir or not os.path.isdir(input_dir):
        return jsonify({"error": "Invalid input directory"}), 400
    if not output_dir:
        output_dir = os.path.join(input_dir, "output")

    videos = get_video_files(input_dir)
    if not videos:
        return jsonify({"error": "No video files found"}), 400

    job_id = str(uuid.uuid4())[:8]
    for v in videos:
        v["status"] = "pending"
        v["time"] = None
        v["error"] = None
        v["output_size"] = None
        v["output_path"] = None

    pause_event = threading.Event()
    pause_event.set()  # starts in "running" state (not paused)

    jobs[job_id] = {
        "id": job_id,
        "status": "starting",
        "input_dir": input_dir,
        "output_dir": output_dir,
        "config": config,
        "videos": videos,
        "total": len(videos),
        "completed": 0,
        "progress": 0,
        "success_count": 0,
        "error_count": 0,
        "cancelled_count": 0,
        "start_time": None,
        "end_time": None,
        "elapsed": None,
        "paused": False,
        "cancelled": False,
        "pause_event": pause_event,
        "_active_procs": [],
    }

    thread = threading.Thread(target=run_batch_job, args=(job_id,), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id, "total": len(videos)})


@app.route("/api/status/<job_id>")
def job_status(job_id):
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    elapsed = 0
    if job["start_time"]:
        elapsed = round(time.time() - job["start_time"], 1)
    if job["elapsed"]:
        elapsed = job["elapsed"]

    return jsonify({
        "id": job["id"],
        "status": job["status"],
        "total": job["total"],
        "completed": job["completed"],
        "progress": job["progress"],
        "success_count": job.get("success_count", 0),
        "error_count": job.get("error_count", 0),
        "cancelled_count": job.get("cancelled_count", 0),
        "paused": job.get("paused", False),
        "elapsed": elapsed,
        "output_dir": job["output_dir"],
        "videos": job["videos"],
    })


@app.route("/api/pause/<job_id>", methods=["POST"])
def pause_job(job_id):
    """Toggle pause/resume for a running job"""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    if job["status"] not in ("running", "starting"):
        return jsonify({"error": "Job is not running"}), 400

    pause_event = job.get("pause_event")
    if not pause_event:
        return jsonify({"error": "No pause event"}), 500

    if job.get("paused"):
        # Resume
        job["paused"] = False
        pause_event.set()
        return jsonify({"paused": False, "message": "Resumed"})
    else:
        # Pause
        job["paused"] = True
        pause_event.clear()
        return jsonify({"paused": True, "message": "Paused"})


@app.route("/api/stop/<job_id>", methods=["POST"])
def stop_job(job_id):
    """Stop/cancel a running job"""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    if job["status"] in ("completed", "stopped"):
        return jsonify({"error": "Job already finished"}), 400

    # Set cancel flag
    job["cancelled"] = True

    # Unpause if paused (so threads can exit)
    pause_event = job.get("pause_event")
    if pause_event:
        pause_event.set()

    # Kill all active FFmpeg processes
    for proc in job.get("_active_procs", []):
        try:
            proc.kill()
        except Exception:
            pass

    return jsonify({"stopped": True, "message": "Job stopped"})


@app.route("/api/defaults")
def get_defaults():
    home = os.path.expanduser("~")
    return jsonify({"config": DEFAULT_CONFIG, "home": home})


if __name__ == "__main__":
    print("\n🎬 Follow Please — Web UI v2")
    print("─" * 40)
    print("  📍 Open: http://localhost:5555")
    print("  ✨ Canva-style live preview")
    print("  📐 X/Y axis positioning")
    print("─" * 40)
    print()
    app.run(host="0.0.0.0", port=5555, debug=False)
