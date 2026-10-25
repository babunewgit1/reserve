Optional: put ffmpeg.exe and ffprobe.exe here.

ScriptReel Studio looks for FFmpeg in this order:
  1. The paths chosen in Settings -> FFmpeg
  2. This bin\ folder (next to the app / repository)
  3. Your PATH (e.g. after `winget install Gyan.FFmpeg`)

If you redistribute a build that includes FFmpeg, you must follow the license of the
FFmpeg build you ship (LGPL or GPL) and include its license text. The binaries are
git-ignored and are NOT part of this repository.
