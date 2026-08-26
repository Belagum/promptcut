# -*- coding: utf-8 -*-
"""Storyboard schema (plan.json): defaults, validation, timing."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from pc_common import die, slug, warn

ASPECTS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "4:3": (1440, 1080),
    "21:9": (2560, 1080),
}

MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "still", "auto")
TRANSITIONS = ("cut", "fade", "dissolve", "wipeleft", "wiperight", "wipeup", "wipedown",
               "slideleft", "slideright", "slideup", "slidedown", "circleopen", "circleclose",
               "radial", "smoothleft", "smoothright", "pixelize", "hblur", "fadeblack",
               "fadewhite", "distance", "zoomin", "diagtl", "diagbr")

DEFAULTS = {
    "project": "promptcut",
    "aspect": "16:9",
    "fps": 30,
    "language": "ru",
    "voice": {"provider": None, "model": None, "voice": None, "speed": 1.0, "instructions": None},
    "image": {"model": None, "resolution": None, "style": "", "negative": ""},
    "subtitles": {"enabled": True, "font": "Arial", "size": None, "max_chars": 38,
                  "position": "bottom", "uppercase": False, "outline": 3, "shadow": 1,
                  "color": "FFFFFF", "outline_color": "000000", "box": False, "margin": None,
                  "bold": True},
    "music": {"file": None, "gain_db": -21.0, "duck": True, "fade": 2.0},
    "timing": {"lead": 0.15, "tail": 0.45, "transition": "dissolve",
               "transition_duration": 0.45, "motion_amp": 0.12, "min_shot": 2.0},
    "shots": [],
}

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".wmv"}

SHOT_DEFAULTS = {
    "id": None, "vo": "", "image_prompt": "", "image": None, "video": None,
    "video_in": 0.0, "video_speed": 1.0, "motion": "auto",
    "focus": None, "ease": False, "motion_amp": None,
    "transition": None, "transition_duration": None, "min_duration": None,
    "sfx": None, "sfx_gain_db": -8.0, "overlay": None, "subtitle": None, "seed": None,
}


def _merge(base: dict, over: dict) -> dict:
    out = deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def normalize(raw: dict) -> dict:
    plan = _merge(DEFAULTS, raw or {})
    aspect = str(plan.get("aspect") or "16:9")
    w, h = ASPECTS.get(aspect, ASPECTS["16:9"])
    plan["width"] = int(raw.get("width") or w)
    plan["height"] = int(raw.get("height") or h)
    plan["aspect"] = aspect
    plan["fps"] = int(plan.get("fps") or 30)
    if plan["subtitles"].get("size") in (None, 0):
        plan["subtitles"]["size"] = max(28, int(plan["height"] * 0.045))
    if plan["subtitles"].get("margin") in (None, 0):
        plan["subtitles"]["margin"] = int(plan["height"] * (0.14 if plan["height"] > plan["width"] else 0.07))

    shots = []
    for i, raw_shot in enumerate(plan.get("shots") or []):
        shot = _merge(SHOT_DEFAULTS, raw_shot if isinstance(raw_shot, dict) else {"vo": str(raw_shot)})
        shot["index"] = i
        shot["id"] = str(shot["id"] or f"s{i + 1:02d}")
        shot["vo"] = (shot.get("vo") or "").strip()
        shot["image_prompt"] = (shot.get("image_prompt") or "").strip()
        if shot["motion"] == "auto":
            shot["motion"] = ("zoom_in", "pan_right", "zoom_out", "pan_left")[i % 4]
        if shot["transition"] is None:
            shot["transition"] = plan["timing"]["transition"]
        if shot["transition_duration"] is None:
            shot["transition_duration"] = plan["timing"]["transition_duration"]
        if shot["transition"] == "cut":
            shot["transition_duration"] = round(1.0 / plan["fps"], 4)
        shots.append(shot)
    plan["shots"] = shots
    plan["project"] = slug(plan.get("project") or "promptcut")
    return plan


def validate(plan: dict) -> list:
    errs = []
    if not plan["shots"]:
        errs.append("plan has no shots")
    for shot in plan["shots"]:
        tag = f"shot {shot['id']}"
        if not (shot["vo"] or shot["image_prompt"] or shot["image"] or shot["video"]):
            errs.append(f"{tag}: empty, needs at least vo, image_prompt, image or video")
        if shot["motion"] not in MOTIONS:
            errs.append(f"{tag}: motion='{shot['motion']}', allowed: {', '.join(MOTIONS)}")
        if shot["transition"] not in TRANSITIONS:
            errs.append(f"{tag}: transition='{shot['transition']}', allowed: {', '.join(TRANSITIONS[:8])}...")
        if shot["image"] and not Path(str(shot["image"])).expanduser().exists():
            errs.append(f"{tag}: image file not found: {shot['image']}")
        if shot["video"] and not Path(str(shot["video"])).expanduser().exists():
            errs.append(f"{tag}: video file not found: {shot['video']}")
        if shot["sfx"] and not Path(str(shot["sfx"])).expanduser().exists():
            errs.append(f"{tag}: sfx file not found: {shot['sfx']}")
    music = (plan.get("music") or {}).get("file")
    if music and not Path(str(music)).expanduser().exists():
        errs.append(f"music file not found: {music}")
    if plan["width"] % 2 or plan["height"] % 2:
        errs.append("width and height must be even")
    return errs


def load_plan(path) -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        die(f"plan file not found: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"plan.json is not valid JSON ({exc}); check commas and quotes")
    plan = normalize(raw)
    plan["_path"] = str(p)
    errs = validate(plan)
    if errs:
        die("plan validation failed:\n  - " + "\n  - ".join(errs))
    return plan


def workdir(plan: dict) -> Path:
    p = Path(plan["_path"])
    d = p.parent / f"{p.stem}_build"
    d.mkdir(parents=True, exist_ok=True)
    return d


def compute_timeline(plan: dict) -> dict:
    """Assign start/duration per shot. Requires vo_duration (0 when silent)."""
    t = plan["timing"]
    lead, tail = float(t["lead"]), float(t["tail"])
    clock = 0.0
    n = len(plan["shots"])
    for i, shot in enumerate(plan["shots"]):
        vo = float(shot.get("vo_duration") or 0.0)
        base = (vo + lead + tail) if vo else float(shot.get("min_duration") or t["min_shot"] + 1.0)
        dur = max(base, float(shot.get("min_duration") or t["min_shot"]))
        shot["duration"] = round(dur, 3)
        shot["start"] = round(clock, 3)
        shot["vo_start"] = round(clock + (lead if vo else 0.0), 3)
        shot["t_out"] = 0.0 if i == n - 1 else float(shot["transition_duration"])
        clock += dur
    plan["total_duration"] = round(clock, 3)
    return plan


def save_built(plan: dict, wd: Path) -> Path:
    out = wd / "plan.built.json"
    data = {k: v for k, v in plan.items() if not k.startswith("_")}
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
