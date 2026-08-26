# -*- coding: utf-8 -*-
"""Shared helpers: config, cache, ffmpeg invocation, spend log."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:  # Windows consoles default to a legacy codepage and mangle Cyrillic
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOME = Path(os.environ.get("PROMPTCUT_HOME") or (Path.home() / ".promptcut"))
CONFIG_PATH = HOME / "config.json"
SPEND_LOG = HOME / "spend.jsonl"

DEFAULT_CONFIG = {
    "openrouter_api_key": "",
    "image_model": "bytedance-seed/seedream-5-0-pro",
    "image_resolution": "2K",
    "image_format": "png",
    "tts_provider": "openrouter",          # openrouter | edge | none
    "tts_model": "openai/gpt-audio-mini",
    "tts_voice": "alloy",
    "edge_voice": "ru-RU-DmitryNeural",
    "transcribe_model": "openai/whisper-1",
    "chat_model": "google/gemini-2.5-flash",
    "image_edit_model": "google/gemini-2.5-flash-image",
    "ytdlp_cookies": "",
    "capcut_drafts_dir": "",
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffprobe",
    "http_referer": "https://github.com/promptcut",
    "app_title": "PromptCut",
}


def info(msg: str) -> None:
    print(f"[promptcut] {msg}", file=sys.stderr, flush=True)


def warn(msg: str) -> None:
    print(f"[promptcut] ! {msg}", file=sys.stderr, flush=True)


def die(msg: str, code: int = 1):
    print(f"[promptcut] ERROR: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception as exc:
            warn(f"cannot read config {CONFIG_PATH} ({exc}), using defaults")
    return cfg


def save_config(cfg: dict) -> Path:
    HOME.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in cfg.items() if v != DEFAULT_CONFIG.get(k) or k == "openrouter_api_key"}
    CONFIG_PATH.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except Exception:
        pass
    return CONFIG_PATH


def api_key(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    return (os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("PROMPTCUT_OPENROUTER_KEY")
            or cfg.get("openrouter_api_key")
            or "").strip()


def cache_dir() -> Path:
    d = HOME / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sha(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:20]


def slug(text: str, limit: int = 40) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^\w\-]+", "-", text, flags=re.UNICODE).strip("-")
    return (text[:limit] or "project")


def _bin(cfg: dict, key: str, env: str) -> str:
    val = os.environ.get(env) or cfg.get(key) or key
    return val


def ffmpeg_bin(cfg: dict | None = None) -> str:
    return _bin(cfg or load_config(), "ffmpeg", "PROMPTCUT_FFMPEG")


def ffprobe_bin(cfg: dict | None = None) -> str:
    return _bin(cfg or load_config(), "ffprobe", "PROMPTCUT_FFPROBE")


def have(binary: str) -> bool:
    return shutil.which(binary) is not None or Path(binary).exists()


def run(cmd: list, desc: str = "", quiet: bool = True, timeout: int | None = None) -> str:
    try:
        proc = subprocess.run(
            [str(c) for c in cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if quiet else None,
            timeout=timeout,
        )
    except FileNotFoundError:
        die(f"executable not found: {cmd[0]}")
    except subprocess.TimeoutExpired:
        die(f"timed out: {desc or cmd[0]}")
    out = (proc.stdout or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        tail = "\n".join(out.strip().splitlines()[-25:])
        die(f"{desc or cmd[0]} failed (exit {proc.returncode}):\n{tail}")
    return out


def ffprobe_duration(path, cfg: dict | None = None) -> float:
    out = run([ffprobe_bin(cfg), "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)], desc=f"ffprobe {Path(path).name}")
    try:
        return float(out.strip().splitlines()[-1])
    except Exception:
        die(f"cannot read duration of {path}")


def log_spend(kind: str, model: str, cost, detail: str = "") -> None:
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        with SPEND_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "kind": kind, "model": model,
                "cost_usd": cost, "detail": detail[:200],
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def spend_total() -> float:
    if not SPEND_LOG.exists():
        return 0.0
    total = 0.0
    for line in SPEND_LOG.read_text(encoding="utf-8").splitlines():
        try:
            total += float(json.loads(line).get("cost_usd") or 0)
        except Exception:
            continue
    return total


def fmt_ts(seconds: float, comma: bool = False) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    sep = "," if comma else "."
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", sep)
