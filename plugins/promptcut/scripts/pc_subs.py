# -*- coding: utf-8 -*-
"""Subtitles: split lines per shot, emit .ass for burn-in and a .srt sidecar."""
from __future__ import annotations

import re
from pathlib import Path

from pc_common import fmt_ts

SENT_END = re.compile(r"(?<=[.!?…:])\s+")
SOFT_BREAK = re.compile(r"(?<=[,;—–-])\s+")


def split_line(text: str, max_chars: int) -> list:
    text = " ".join((text or "").split())
    if not text:
        return []
    parts, out = SENT_END.split(text), []
    for part in parts:
        if len(part) <= max_chars:
            out.append(part)
            continue
        for piece in SOFT_BREAK.split(part):
            if len(piece) <= max_chars:
                out.append(piece)
                continue
            words, cur = piece.split(), ""
            for w in words:
                if cur and len(cur) + len(w) + 1 > max_chars:
                    out.append(cur)
                    cur = w
                else:
                    cur = f"{cur} {w}".strip()
            if cur:
                out.append(cur)
    return [p.strip() for p in out if p.strip()]


def two_lines(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    words, best, target = text.split(), None, len(text) / 2
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        score = abs(len(a) - target)
        if best is None or score < best[0]:
            best = (score, a, b)
    return f"{best[1]}\\N{best[2]}" if best else text


def cues(plan: dict) -> list:
    sub = plan["subtitles"]
    if not sub.get("enabled", True):
        return []
    max_chars = int(sub.get("max_chars") or 38)
    out = []
    for shot in plan["shots"]:
        if shot.get("overlay"):
            out.append((shot["start"] + 0.1,
                        shot["start"] + min(3.5, max(0.6, shot["duration"] - 0.1)),
                        f"{{OVERLAY}}{shot['overlay']}"))
        text = shot.get("subtitle")
        if text is False:
            continue
        text = text or shot.get("vo") or ""
        if not text.strip():
            continue
        span_start = float(shot.get("vo_start", shot["start"]))
        span = float(shot.get("vo_duration") or 0.0) or float(shot["duration"]) * 0.9
        chunks = split_line(text, max_chars * 2)
        total = sum(len(c) for c in chunks) or 1
        clock = span_start
        for chunk in chunks:
            dur = max(0.7, span * len(chunk) / total)
            body = chunk.upper() if sub.get("uppercase") else chunk
            out.append((round(clock, 3), round(min(clock + dur, span_start + span + 0.25), 3),
                        two_lines(body, max_chars)))
            clock += dur
    return sorted(out, key=lambda c: c[0])


def _ass_color(hex_rgb: str, alpha: str = "00") -> str:
    h = (hex_rgb or "FFFFFF").lstrip("#&Hh")[-6:]
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha}{b}{g}{r}".upper()


def build_ass(plan: dict, path: Path) -> Path:
    sub = plan["subtitles"]
    w, h = plan["width"], plan["height"]
    align = {"bottom": 2, "center": 5, "top": 8}.get(str(sub.get("position", "bottom")), 2)
    border = 3 if sub.get("box") else 1
    size = int(sub["size"])
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{sub.get('font','Arial')},{size},{_ass_color(sub.get('color','FFFFFF'))},&H000000FF,{_ass_color(sub.get('outline_color','000000'))},&H90000000,{-1 if sub.get('bold', True) else 0},0,0,0,100,100,0,0,{border},{sub.get('outline',3)},{sub.get('shadow',1)},{align},{int(w*0.06)},{int(w*0.06)},{int(sub['margin'])},1
Style: Title,{sub.get('font','Arial')},{int(size*1.25)},{_ass_color('FFFFFF')},&H000000FF,{_ass_color('000000')},&H90000000,-1,0,0,0,100,100,0,0,1,{int(sub.get('outline',3))+1},1,8,{int(w*0.06)},{int(w*0.06)},{int(h*0.06)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for start, end, text in cues(plan):
        style = "Main"
        if text.startswith("{OVERLAY}"):
            style, text = "Title", text[len("{OVERLAY}"):]
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{text}")
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def _ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def build_srt(plan: dict, path: Path) -> Path:
    body = [c for c in cues(plan) if not c[2].startswith("{OVERLAY}")]
    rows = []
    for i, (start, end, text) in enumerate(body):
        if i + 1 < len(body):
            end = min(end, body[i + 1][0])
        if end <= start:
            continue
        rows.append(f"{len(rows) + 1}\n{fmt_ts(start, True)} --> {fmt_ts(end, True)}\n"
                    f"{text.replace(chr(92) + 'N', chr(10))}\n")
    path.write_text("\n".join(rows), encoding="utf-8")
    return path
