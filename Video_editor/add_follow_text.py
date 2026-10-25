#!/usr/bin/env python3
"""
=============================================================
  Follow Please — Batch Video Text Overlay Tool
=============================================================
  100+ video-তে "Follow Please" text বসাবে (প্রথম 2-3 সেকেন্ড)
  
  ✔ White bold text + Yellow/Gold background box
  ✔ Fade in → Display → Fade out (smooth)
  ✔ Center position
  ✔ Parallel processing (fast!)
  
  Approach: Pillow দিয়ে text overlay PNG বানায়,
            FFmpeg overlay filter দিয়ে video-তে বসায়
=============================================================
"""

import os
import sys
import subprocess
import argparse
import time
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("❌ Pillow লাগবে। Install করো: pip3 install Pillow")
    sys.exit(1)

# ─────────────────────────────────────────────
#  Configuration — তোমার পছন্দ অনুযায়ী পরিবর্তন করো
# ─────────────────────────────────────────────

TEXT = "Follow Please"           # যে text দেখাবে
TEXT_DISPLAY_DURATION = 2.5      # কত সেকেন্ড text থাকবে (total, fade সহ)
FADE_DURATION = 0.4              # fade in/out কত সেকেন্ডে হবে

# Text style
FONT_SIZE = 52                   # text এর size
TEXT_COLOR = (255, 255, 255, 255)  # White, fully opaque
PADDING_X = 30                   # text এর বাম-ডানে কতটুকু padding
PADDING_Y = 18                   # text এর উপর-নিচে কতটুকু padding

# Background box style (Gold/Yellow)
BOX_COLOR = (255, 215, 0, 220)   # RGBA — Gold yellow, slightly transparent

# Processing
MAX_WORKERS = 4                  # একসাথে কয়টা video process করবে
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv",
    ".wmv", ".webm", ".m4v", ".ts", ".mts",
}

# Overlay image will be cached here
_overlay_cache = {}


def create_text_overlay(temp_dir: str) -> str:
    """
    Pillow দিয়ে transparent PNG বানায় — শুধু text + background box
    Resolution-independent: FFmpeg overlay filter সব video-তে center করবে
    """
    cache_key = "text_overlay"
    if cache_key in _overlay_cache:
        return _overlay_cache[cache_key]
    
    # Font — system font try করবে, না পেলে default
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
                font = ImageFont.truetype(fp, FONT_SIZE)
                break
            except Exception:
                continue
    
    if font is None:
        font = ImageFont.load_default()
    
    # Measure text size
    temp_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp_img)
    bbox = temp_draw.textbbox((0, 0), TEXT, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    # Image size = text + padding (just the box, not full video)
    img_w = text_w + PADDING_X * 2
    img_h = text_h + PADDING_Y * 2
    
    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw background box (rounded rectangle, fills entire image)
    radius = 12
    draw.rounded_rectangle(
        [0, 0, img_w - 1, img_h - 1],
        radius=radius,
        fill=BOX_COLOR,
    )
    
    # Draw text centered in the box
    text_x = PADDING_X - bbox[0]  # offset for font baseline
    text_y = PADDING_Y - bbox[1]
    draw.text((text_x, text_y), TEXT, font=font, fill=TEXT_COLOR)
    
    # Save
    overlay_path = os.path.join(temp_dir, "overlay.png")
    img.save(overlay_path, "PNG")
    
    _overlay_cache[cache_key] = overlay_path
    return overlay_path


def get_video_files(input_dir: str) -> list:
    """input folder থেকে সব video file খুঁজে বের করে"""
    videos = []
    input_path = Path(input_dir)
    
    for f in sorted(input_path.iterdir()):
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            videos.append(str(f))
    
    return videos


def build_ffmpeg_command(input_file: str, overlay_path: str, output_file: str) -> list:
    """
    FFmpeg command তৈরি করে — overlay filter + fade effect সহ
    
    Overlay PNG input হিসেবে নেয়, fade in/out effect দেয়,
    enable দিয়ে শুধু নির্দিষ্ট সময়ে দেখায়
    """
    
    fade_out_start = TEXT_DISPLAY_DURATION - FADE_DURATION
    
    # Complex filter: 
    # 1. overlay image-এ fade in/out alpha apply করে
    # 2. তারপর main video-র উপর overlay করে (center position)
    filter_complex = (
        f"[1:v]format=rgba,"
        f"fade=t=in:st=0:d={FADE_DURATION}:alpha=1,"
        f"fade=t=out:st={fade_out_start}:d={FADE_DURATION}:alpha=1"
        f"[overlay];"
        f"[0:v][overlay]overlay="
        f"x=(W-w)/2:y=(H-h)/2:"
        f"enable='between(t,0,{TEXT_DISPLAY_DURATION})'"
        f"[outv]"
    )
    
    cmd = [
        "ffmpeg",
        "-i", input_file,
        "-loop", "1",             # overlay image-কে loop করো (single frame → continuous)
        "-i", overlay_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",           # audio copy (? = optional, audio নাও থাকতে পারে)
        "-c:v", "libx264",        # video codec
        "-crf", "18",             # quality (lower = better, 18 = visually lossless)
        "-preset", "medium",      # encoding speed vs compression
        "-codec:a", "copy",       # audio re-encode করবে না (fast)
        "-shortest",              # main video শেষ হলে stop
        "-y",                     # overwrite if exists
        "-hide_banner",
        "-loglevel", "error",     # শুধু error দেখাবে
        output_file,
    ]
    
    return cmd


def process_video(
    input_file: str, output_dir: str, temp_dir: str,
    index: int, total: int
) -> dict:
    """একটা video process করে"""
    
    filename = os.path.basename(input_file)
    output_file = os.path.join(output_dir, filename)
    
    # যদি output file name same হয়, prefix দিবে
    if os.path.abspath(input_file) == os.path.abspath(output_file):
        name, ext = os.path.splitext(filename)
        output_file = os.path.join(output_dir, f"{name}_follow{ext}")
    
    result = {
        "input": filename,
        "output": output_file,
        "success": False,
        "error": None,
        "index": index,
    }
    
    try:
        # Overlay image তৈরি করো (cached, resolution-independent)
        overlay_path = create_text_overlay(temp_dir)
        
        # FFmpeg command
        cmd = build_ffmpeg_command(input_file, overlay_path, output_file)
        
        start_time = time.time()
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout per video
        )
        elapsed = time.time() - start_time
        
        if process.returncode == 0:
            result["success"] = True
            result["time"] = round(elapsed, 1)
            print(f"  ✅ [{index}/{total}] {filename} — {elapsed:.1f}s")
        else:
            result["error"] = process.stderr.strip()
            print(f"  ❌ [{index}/{total}] {filename} — ERROR")
            if process.stderr.strip():
                error_lines = process.stderr.strip().split("\n")[:2]
                for line in error_lines:
                    print(f"      {line}")
    
    except subprocess.TimeoutExpired:
        result["error"] = "Timeout (10 minutes)"
        print(f"  ⏰ [{index}/{total}] {filename} — TIMEOUT")
    except Exception as e:
        result["error"] = str(e)
        print(f"  ❌ [{index}/{total}] {filename} — {e}")
    
    return result


def main():
    global TEXT, TEXT_DISPLAY_DURATION, FONT_SIZE, MAX_WORKERS, FADE_DURATION
    
    parser = argparse.ArgumentParser(
        description="🎬 100+ video-তে 'Follow Please' text বসাও",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 add_follow_text.py ./videos
  python3 add_follow_text.py ./videos -o ./output
  python3 add_follow_text.py ./videos --text "Subscribe!" --duration 3
  python3 add_follow_text.py ./videos --workers 8
        """,
    )
    
    parser.add_argument(
        "input_dir",
        help="Input folder path (যেখানে videos আছে)",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="Output folder path (default: input_dir/output/)",
    )
    parser.add_argument(
        "--text",
        default=None,
        help=f"Custom text (default: '{TEXT}')",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help=f"Text display duration in seconds (default: {TEXT_DISPLAY_DURATION})",
    )
    parser.add_argument(
        "--fontsize",
        type=int,
        default=None,
        help=f"Font size (default: {FONT_SIZE})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=f"Parallel workers (default: {MAX_WORKERS})",
    )
    parser.add_argument(
        "--fade",
        type=float,
        default=None,
        help=f"Fade in/out duration in seconds (default: {FADE_DURATION})",
    )
    
    args = parser.parse_args()
    
    # Override config from CLI args
    if args.text:
        TEXT = args.text
    if args.duration:
        TEXT_DISPLAY_DURATION = args.duration
    if args.fontsize:
        FONT_SIZE = args.fontsize
    if args.workers:
        MAX_WORKERS = args.workers
    if args.fade:
        FADE_DURATION = args.fade
    
    # Input validation
    input_dir = os.path.abspath(args.input_dir)
    if not os.path.isdir(input_dir):
        print(f"❌ Input folder পাওয়া যায়নি: {input_dir}")
        sys.exit(1)
    
    # Output directory
    if args.output_dir:
        output_dir = os.path.abspath(args.output_dir)
    else:
        output_dir = os.path.join(input_dir, "output")
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Find videos
    videos = get_video_files(input_dir)
    
    if not videos:
        print(f"❌ কোনো video পাওয়া যায়নি: {input_dir}")
        print(f"   Supported formats: {', '.join(sorted(VIDEO_EXTENSIONS))}")
        sys.exit(1)
    
    # ─── Summary ───
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║       🎬  Follow Please — Batch Processor       ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  📂 Input:    {os.path.basename(input_dir):<34} ║")
    print(f"║  📁 Output:   {os.path.basename(output_dir):<34} ║")
    print(f"║  🎥 Videos:   {len(videos):<34} ║")
    print(f"║  📝 Text:     \"{TEXT}\"{'':.<{32 - len(TEXT)}} ║")
    print(f"║  ⏱️  Duration: {TEXT_DISPLAY_DURATION}s (fade: {FADE_DURATION}s){'':.<20} ║")
    print(f"║  ⚡ Workers:  {MAX_WORKERS:<34} ║")
    print("╚══════════════════════════════════════════════════╝")
    print()
    
    # ─── Process all videos ───
    total = len(videos)
    results = []
    overall_start = time.time()
    
    # Temp directory for overlay images
    with tempfile.TemporaryDirectory(prefix="follow_text_") as temp_dir:
        print(f"🚀 Processing শুরু হচ্ছে ({total} videos)...\n")
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for i, video in enumerate(videos, 1):
                future = executor.submit(
                    process_video, video, output_dir, temp_dir, i, total
                )
                futures[future] = video
            
            for future in as_completed(futures):
                results.append(future.result())
    
    # ─── Final Summary ───
    overall_time = time.time() - overall_start
    success_count = sum(1 for r in results if r["success"])
    fail_count = total - success_count
    
    print()
    print("═" * 50)
    print(f"  ✅ সফল:      {success_count}/{total}")
    if fail_count > 0:
        print(f"  ❌ ব্যর্থ:     {fail_count}/{total}")
    print(f"  ⏱️  মোট সময়:  {overall_time:.1f} seconds")
    print(f"  📁 Output:   {output_dir}")
    print("═" * 50)
    
    # Failed files list
    if fail_count > 0:
        print("\n❌ যে video গুলো fail হয়েছে:")
        for r in sorted(results, key=lambda x: x["index"]):
            if not r["success"]:
                print(f"   • {r['input']}: {r['error']}")
    
    print("\n🎉 Done!")
    
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
