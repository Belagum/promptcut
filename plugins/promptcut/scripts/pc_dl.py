# -*- coding: utf-8 -*-
"""yt-dlp wrapper: search the web for media and download clips or audio."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from pc_common import die, load_config

AUDIO_EXT = {".mp3", ".m4a", ".wav", ".opus", ".flac", ".aac"}


def _ytdlp() -> list:
    exe = shutil.which("yt-dlp")
    if exe:
        cmd = [exe]
    else:
        try:
            import yt_dlp  # noqa: F401,PLC0415
            cmd = [sys.executable, "-m", "yt_dlp"]
        except ImportError:
            die("yt-dlp is not installed: pip install yt-dlp")
    cookies = (load_config().get("ytdlp_cookies") or "").strip()
    if cookies:
        cmd += ["--cookies", cookies] if Path(cookies).exists() \
            else ["--cookies-from-browser", cookies]
    return cmd


def _run(cmd: list, timeout: int = 900) -> str:
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        die("yt-dlp timed out")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.decode("utf-8", "replace").strip().splitlines()[-8:])
        if "not a bot" in tail or "Sign in" in tail:
            tail += ("\nhint: promptcut config --set ytdlp_cookies=firefox "
                     "(or chrome/edge, or a cookies.txt path)")
        die(f"yt-dlp failed:\n{tail}")
    return proc.stdout.decode("utf-8", "replace")


def search(query: str, n: int = 5) -> list:
    out = _run(_ytdlp() + [f"ytsearch{n}:{query}", "--flat-playlist", "--dump-json",
                           "--no-warnings"], timeout=120)
    hits = []
    for line in out.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        hits.append({"title": e.get("title"), "url": e.get("url") or e.get("webpage_url"),
                     "duration": e.get("duration"),
                     "channel": e.get("channel") or e.get("uploader"),
                     "views": e.get("view_count")})
    return hits


def fetch(url: str, out, audio: bool = False, start: float | None = None,
          end: float | None = None, fmt: str | None = None) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    base = out.with_suffix("")
    suffix = out.suffix.lower()
    audio = audio or suffix in AUDIO_EXT
    cmd = _ytdlp() + ["--no-playlist", "--no-warnings", "--quiet", "--no-simulate",
                      "--print", "after_move:filepath", "-o", f"{base}.%(ext)s"]
    if audio:
        cmd += ["-x", "--audio-format", suffix.lstrip(".") if suffix in AUDIO_EXT else "mp3",
                "--audio-quality", "0"]
    else:
        cmd += ["-f", fmt or "bv*[height<=1080]+ba/b[height<=1080]/b",
                "--merge-output-format", "mp4"]
    if start is not None or end is not None:
        cmd += ["--download-sections",
                f"*{start or 0}-{end if end is not None else 'inf'}",
                "--force-keyframes-at-cuts"]
    text = _run(cmd + [url])
    for line in reversed(text.strip().splitlines()):
        if line.strip() and Path(line.strip()).exists():
            return Path(line.strip())
    cands = sorted(base.parent.glob(base.name + ".*"), key=lambda p: p.stat().st_mtime)
    cands = [c for c in cands if c.suffix.lower() != ".part"]
    if not cands:
        die("yt-dlp finished but the output file was not found")
    return cands[-1]
