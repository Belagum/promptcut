# -*- coding: utf-8 -*-
"""CapCut draft export: tracks, transitions, animations, filters, masks, effects,
keyframes, subtitles. Requires pycapcut. The draft opens in CapCut for manual
finishing; CapCut does the final render.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pc_common import die, info, load_config, warn

ALIASES = {
    "transition": {"dissolve": "叠化", "fade": "叠化", "flash": "闪白", "white_flash": "White_Flash",
                   "blur": "模糊", "zoom": "推近", "spin": "旋转", "glitch": "信号故障",
                   "slide_left": "向左滑动", "slide_right": "向右滑动", "up": "上移", "down": "下移"},
    "intro": {"zoom_in": "动感放大", "zoom": "放大", "slide_up": "向上滑动", "fade_in": "渐显",
              "shake": "上下抖动", "spin": "旋转开幕", "soft_zoom": "轻微放大"},
    "outro": {"zoom_out": "缩小", "fade_out": "渐隐", "slide_down": "向下滑动"},
    "mask": {"circle": "圆形", "rect": "矩形", "rectangle": "矩形", "linear": "线性",
             "mirror": "镜面", "heart": "爱心", "star": "星形"},
}

KINDS = {
    "transition": "TransitionType",
    "intro": "IntroType",
    "outro": "OutroType",
    "group": "GroupAnimationType",
    "effect": "VideoSceneEffectType",
    "character": "VideoCharacterEffectType",
    "filter": "FilterType",
    "mask": "MaskType",
    "audio": "AudioSceneEffectType",
    "text_intro": "TextIntro",
    "text_outro": "TextOutro",
    "text_loop": "TextLoopAnim",
    "font": "FontType",
    "keyframe": "KeyframeProperty",
}


def _cc():
    try:
        import pycapcut  # noqa: PLC0415
    except ImportError:
        die("pycapcut is not installed: pip install pycapcut")
    return pycapcut


def _secs(v) -> str:
    return f"{float(v):.6f}s"


def default_drafts_dirs() -> list:
    home = Path.home()
    cands = []
    local = os.environ.get("LOCALAPPDATA")
    roaming = os.environ.get("APPDATA")
    for base in filter(None, [local, roaming]):
        cands += [Path(base) / "CapCut/User Data/Projects/com.lveditor.draft",
                  Path(base) / "JianyingPro/User Data/Projects/com.lveditor.draft"]
    cands += [
        home / "Movies/CapCut/User Data/Projects/com.lveditor.draft",
        home / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft",
        home / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft",
    ]
    return [c for c in cands if c.exists()]


def drafts_dir(cfg: dict | None = None, override: str | None = None) -> Path:
    cfg = cfg or load_config()
    for cand in [override, os.environ.get("PROMPTCUT_CAPCUT_DIR"), cfg.get("capcut_drafts_dir")]:
        if cand:
            p = Path(str(cand)).expanduser()
            if p.exists():
                return p
            warn(f"configured drafts folder does not exist: {p}")
    found = default_drafts_dirs()
    if found:
        return found[0]
    die("CapCut drafts folder not found. Copy it from CapCut > Settings > Draft location "
        "and set it: promptcut config --set capcut_drafts_dir=\"<path>\"")


def enum_for(kind: str):
    cc = _cc()
    name = KINDS.get(kind)
    if not name:
        die(f"unknown effect type '{kind}'. Available: {', '.join(KINDS)}")
    return getattr(cc, name)


def search_effects(kind: str, query: str = "", limit: int = 60) -> list:
    members = list(enum_for(kind).__members__)
    if not query:
        return members[:limit]
    q = query.strip().lower()
    alias = ALIASES.get(kind, {}).get(q)
    hits = [m for m in members if q in m.lower()]
    if alias and alias in members:
        hits = [alias] + [h for h in hits if h != alias]
    if not hits:
        hits = [m for m in members if re.search("|".join(re.escape(c) for c in q.split()), m, re.I)]
    return hits[:limit]


def resolve(kind: str, value: str):
    """Effect name -> enum member: exact name, English alias, or substring match."""
    if value in (None, "", False):
        return None
    enum = enum_for(kind)
    members = enum.__members__
    if value in members:
        return members[value]
    alias = ALIASES.get(kind, {}).get(str(value).strip().lower())
    if alias and alias in members:
        return members[alias]
    lower = {k.lower(): k for k in members}
    if str(value).lower() in lower:
        return members[lower[str(value).lower()]]
    hits = search_effects(kind, str(value), limit=8)
    if hits:
        info(f"{kind} '{value}' -> '{hits[0]}'")
        return members[hits[0]]
    die(f"no {kind} matches '{value}'. Browse them: "
        f"promptcut capcut-effects --type {kind} --search <part of the name>")


def _clamp(cc, material, conf, trange, src):
    # ffprobe and CapCut disagree by a millisecond or two; asking for more than the
    # material holds is a hard error in pycapcut, so trim the request instead.
    limit = int(getattr(material, "duration", 0) or 0)
    if limit <= 0:
        return trange, src
    speed = float(conf.get("speed") or 1.0)
    if src is not None:
        if src.duration > limit:
            src = cc.Timerange(src.start, max(1000, limit - src.start))
            trange = cc.Timerange(trange.start, int(src.duration / speed))
        return trange, src
    if trange.duration * speed > limit:
        trange = cc.Timerange(trange.start, max(1000, int(limit / speed)))
    return trange, src


def _clip(cc, conf: dict):
    if not conf:
        return None
    return cc.ClipSettings(
        alpha=float(conf.get("alpha", 1.0)),
        flip_horizontal=bool(conf.get("flip_h", False)),
        flip_vertical=bool(conf.get("flip_v", False)),
        rotation=float(conf.get("rotation", 0.0)),
        scale_x=float(conf.get("scale_x", conf.get("scale", 1.0))),
        scale_y=float(conf.get("scale_y", conf.get("scale", 1.0))),
        transform_x=float(conf.get("x", 0.0)),
        transform_y=float(conf.get("y", 0.0)),
    )


def _text_style(cc, conf: dict):
    color = conf.get("color", [1, 1, 1])
    if isinstance(color, str):
        h = color.lstrip("#")
        color = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return cc.TextStyle(
        size=float(conf.get("size", 8.0)),
        bold=bool(conf.get("bold", True)),
        italic=bool(conf.get("italic", False)),
        underline=bool(conf.get("underline", False)),
        color=tuple(color),
        alpha=float(conf.get("alpha", 1.0)),
        align=int(conf.get("align", 1)),
        vertical=bool(conf.get("vertical", False)),
        letter_spacing=int(conf.get("letter_spacing", 0)),
        line_spacing=int(conf.get("line_spacing", 0)),
        auto_wrapping=bool(conf.get("auto_wrap", True)),
        max_line_width=float(conf.get("max_line_width", 0.82)),
    )


def _apply_visual_extras(cc, seg, conf: dict):
    for key, kind in (("animation_in", "intro"), ("animation_out", "outro"),
                      ("animation_group", "group")):
        if conf.get(key):
            dur = conf.get(f"{key}_dur")
            seg.add_animation(resolve(kind, conf[key]),
                              _secs(dur) if dur else None)
    if conf.get("transition"):
        dur = conf.get("transition_dur")
        seg.add_transition(resolve("transition", conf["transition"]),
                           duration=_secs(dur) if dur else None)
    if conf.get("filter"):
        seg.add_filter(resolve("filter", conf["filter"]),
                       float(conf.get("filter_intensity", 100.0)))
    mask = conf.get("mask")
    if mask:
        mask = {"type": mask} if isinstance(mask, str) else mask
        seg.add_mask(resolve("mask", mask.get("type", "circle")),
                     center_x=float(mask.get("cx", 0.0)), center_y=float(mask.get("cy", 0.0)),
                     size=float(mask.get("size", 0.5)), rotation=float(mask.get("rotation", 0.0)),
                     feather=float(mask.get("feather", 0.0)), invert=bool(mask.get("invert", False)),
                     rect_width=mask.get("rect_width"), round_corner=mask.get("round_corner"))
    for eff in (conf.get("effects") or ([conf["effect"]] if conf.get("effect") else [])):
        kind = "character" if str(eff).startswith("char:") else "effect"
        seg.add_effect(resolve(kind, str(eff).replace("char:", "")))
    if conf.get("background"):
        bg = conf["background"]
        bg = {"type": bg} if isinstance(bg, str) else bg
        seg.add_background_filling(bg.get("type", "blur"), float(bg.get("blur", 0.0625)),
                                   bg.get("color", "#00000000"))
    for kf in conf.get("keyframes") or []:
        seg.add_keyframe(resolve("keyframe", kf["prop"]), _secs(kf["at"]), float(kf["value"]))


def build_spec(spec: dict, *, cfg: dict | None = None, drafts: str | None = None,
               dump_to: str | None = None) -> dict:
    cc = _cc()
    cfg = cfg or load_config()
    w, h = (spec.get("size") or [1080, 1920])[:2]
    fps = int(spec.get("fps") or 30)
    name = spec.get("name") or "promptcut_draft"

    if dump_to:
        script = cc.ScriptFile(int(w), int(h), fps)
        folder = None
    else:
        folder = cc.DraftFolder(str(drafts_dir(cfg, drafts)))
        script = folder.create_draft(name, int(w), int(h), fps=fps,
                                     allow_replace=bool(spec.get("replace", True)))

    counts = {"segments": 0, "tracks": 0}
    for track in spec.get("tracks") or []:
        ttype = str(track.get("type", "video")).lower()
        tname = track.get("name") or f"{ttype}_{counts['tracks'] + 1}"
        script.add_track(getattr(cc.TrackType, ttype), tname,
                         mute=bool(track.get("mute", False)),
                         relative_index=int(track.get("index", 0)))
        counts["tracks"] += 1
        for conf in track.get("segments") or []:
            start, dur = _secs(conf.get("start", 0)), _secs(conf.get("duration", 3))
            trange = cc.trange(start, dur)
            src = None
            if conf.get("source_in") is not None:
                src = cc.trange(_secs(conf["source_in"]),
                                _secs(conf.get("source_duration", conf.get("duration", 3))))
            if ttype == "video":
                path = str(Path(str(conf["file"])).expanduser())
                material = cc.VideoMaterial(path)
                trange, src = _clamp(cc, material, conf, trange, src)
                seg = cc.VideoSegment(material, trange, source_timerange=src,
                                      speed=conf.get("speed"),
                                      volume=float(conf.get("volume", 1.0)),
                                      clip_settings=_clip(cc, conf.get("clip")))
                _apply_visual_extras(cc, seg, conf)
            elif ttype == "audio":
                path = str(Path(str(conf["file"])).expanduser())
                material = cc.AudioMaterial(path)
                trange, src = _clamp(cc, material, conf, trange, src)
                seg = cc.AudioSegment(material, trange, source_timerange=src,
                                      speed=conf.get("speed"),
                                      volume=float(conf.get("volume", 1.0)))
                if conf.get("fade_in") or conf.get("fade_out"):
                    seg.add_fade(_secs(conf.get("fade_in", 0)), _secs(conf.get("fade_out", 0)))
                if conf.get("effect"):
                    seg.add_effect(resolve("audio", conf["effect"]))
                for kf in conf.get("keyframes") or []:
                    seg.add_keyframe(cc.tim(_secs(kf["at"])), float(kf["value"]))
            elif ttype == "text":
                border = conf.get("border")
                bg = conf.get("background")
                seg = cc.TextSegment(
                    conf.get("text", ""), trange,
                    font=resolve("font", conf["font"]) if conf.get("font") else None,
                    style=_text_style(cc, conf),
                    clip_settings=_clip(cc, conf.get("clip")),
                    border=cc.TextBorder(
                        alpha=float((border or {}).get("alpha", 1.0)),
                        color=tuple((border or {}).get("color", (0, 0, 0))),
                        width=float((border or {}).get("width", 40.0))) if border else None,
                    background=cc.TextBackground(
                        color=(bg or {}).get("color", "#000000"),
                        alpha=float((bg or {}).get("alpha", 0.6)),
                        round_radius=float((bg or {}).get("round", 0.2)),
                        height=float((bg or {}).get("height", 0.14)),
                        width=float((bg or {}).get("width", 0.14))) if bg else None)
                for key, kind in (("anim_in", "text_intro"), ("anim_out", "text_outro"),
                                  ("loop_anim", "text_loop")):
                    if conf.get(key):
                        seg.add_animation(resolve(kind, conf[key]),
                                          _secs(conf.get(f"{key}_dur", 0.5)))
                for kf in conf.get("keyframes") or []:
                    seg.add_keyframe(resolve("keyframe", kf["prop"]), _secs(kf["at"]),
                                     float(kf["value"]))
            elif ttype == "sticker":
                seg = cc.StickerSegment(conf["resource_id"], trange,
                                        clip_settings=_clip(cc, conf.get("clip")))
            elif ttype == "effect":
                script.add_effect(resolve("character" if conf.get("character") else "effect",
                                          conf["effect"]), trange, tname,
                                  params=conf.get("params"))
                counts["segments"] += 1
                continue
            elif ttype == "filter":
                script.add_filter(resolve("filter", conf["filter"]), trange, tname,
                                  intensity=float(conf.get("intensity", 100.0)))
                counts["segments"] += 1
                continue
            else:
                warn(f"track type '{ttype}' is not supported, skipping")
                continue
            script.add_segment(seg, tname)
            counts["segments"] += 1

    srt = spec.get("srt")
    if srt and srt.get("file"):
        script.add_track(cc.TrackType.text, srt.get("track", "subs"))
        script.import_srt(str(Path(str(srt["file"])).expanduser()), srt.get("track", "subs"),
                          time_offset=_secs(srt.get("offset", 0)),
                          text_style=_text_style(cc, srt))
        counts["srt"] = True

    if dump_to:
        Path(dump_to).parent.mkdir(parents=True, exist_ok=True)
        script.dump(str(dump_to))
        target = str(dump_to)
    else:
        script.save()
        target = str(Path(str(drafts_dir(cfg, drafts))) / name)
    info(f"CapCut draft ready: {target} ({counts['tracks']} tracks, "
         f"{counts['segments']} segments)")
    return {"draft": target, "name": name, **counts}


def spec_from_plan(plan: dict, wd: Path, *, use_clips: bool = False,
                   name: str | None = None, transitions: bool = False) -> dict:
    video, audio, sfx = [], [], []
    for i, shot in enumerate(plan["shots"]):
        src = shot.get("clip_file") if use_clips else shot.get("image_file")
        if not src:
            continue
        conf = {
            "file": src, "start": shot["start"],
            "duration": shot["duration"],
            "animation_in": {"zoom_in": "轻微放大", "zoom_out": "缩小", "pan_left": "向左滑动",
                             "pan_right": "向右滑动", "pan_up": "向上滑动",
                             "pan_down": "向下滑动"}.get(shot.get("motion"), None),
            "animation_in_dur": min(1.2, shot["duration"] * 0.9),
        }
        if not use_clips:
            conf["background"] = {"type": "blur"}
        # CapCut transitions consume time from both neighbours, which would drift the
        # voiceover track; opt in only when exact sync does not matter.
        if transitions and shot.get("transition") not in (None, "cut") and i < len(plan["shots"]) - 1:
            conf["transition"] = "dissolve"
            conf["transition_dur"] = shot.get("t_out") or 0.4
        video.append({k: v for k, v in conf.items() if v is not None})
        if shot.get("vo_file"):
            audio.append({"file": shot["vo_file"], "start": shot["vo_start"],
                          "duration": shot["vo_duration"]})
        if shot.get("sfx"):
            sfx.append({"file": shot["sfx"], "start": shot["start"], "duration": 2.0,
                        "volume": 10 ** (float(shot.get("sfx_gain_db", -8)) / 20)})
    tracks = [{"type": "video", "name": "main", "segments": video},
              {"type": "audio", "name": "vo", "segments": audio}]
    music = (plan.get("music") or {}).get("file")
    if music:
        tracks.append({"type": "audio", "name": "music", "segments": [{
            "file": str(music), "start": 0, "duration": plan["total_duration"],
            "volume": 10 ** (float(plan["music"].get("gain_db", -21)) / 20),
            "fade_in": 1.2, "fade_out": float(plan["music"].get("fade", 2.0))}]})
    if sfx:
        tracks.append({"type": "audio", "name": "sfx", "segments": sfx})
    spec = {
        "name": name or f"promptcut_{plan.get('project', 'draft')}",
        "size": [plan["width"], plan["height"]], "fps": plan["fps"], "tracks": tracks,
    }
    srt = wd / "subs.srt"
    if not srt.exists():
        import pc_subs
        pc_subs.build_srt(plan, srt)
    sub = plan.get("subtitles") or {}
    spec["srt"] = {"file": str(srt), "track": "subs", "size": 7.5,
                   "color": sub.get("color", "FFFFFF"), "bold": True, "align": 1}
    (wd / "capcut.spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    return spec
