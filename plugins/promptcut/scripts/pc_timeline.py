# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from pc_common import die, ffprobe_duration, load_config, warn

DUCK_DB = -12.0
DUCK_ATTACK = 0.15
DUCK_RELEASE = 0.4
TITLE_FADE = 0.2
MUSIC_FADE_IN = 1.2
TRACK_TYPES = ("video", "audio")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def frames(t, fps) -> int:
    return int(round(float(t) * float(fps)))


def db_to_gain(db) -> float:
    return 10 ** (float(db) / 20)


def smoothstep(p: float) -> float:
    return p * p * (3 - 2 * p)


def cover_window(sw, sh, w, h) -> tuple:
    crop_w = min(sw, sh * w / h)
    crop_h = min(sh, sw * h / w)
    return (sw - crop_w) / 2, (sh - crop_h) / 2, crop_w, crop_h


def parse_focus(focus):
    if not focus:
        return None
    if isinstance(focus, str):
        focus = focus.split(",")
    try:
        return float(focus[0]), float(focus[1])
    except (TypeError, ValueError, IndexError):
        return None


def cover_focus(focus, sw, sh, w, h):
    pt = parse_focus(focus)
    if not pt:
        return None
    x0, y0, cw, ch = cover_window(sw, sh, w, h)
    fx = (pt[0] * sw - x0) / cw
    fy = (pt[1] * sh - y0) / ch
    return [round(min(1.0, max(0.0, fx)), 4), round(min(1.0, max(0.0, fy)), 4)]


def motion_path(motion: dict | None, span: float) -> list:
    motion = motion or {}
    kind = motion.get("kind") or "still"
    amp = float(motion.get("amp") or 0.0)
    if kind == "still" or amp <= 0:
        return [(0.0, 1.0, 0.5, 0.5), (round(float(span), 4), 1.0, 0.5, 0.5)]
    eased = bool(motion.get("ease"))
    focus = parse_focus(motion.get("focus")) or (0.5, 0.5)
    n = 6 if eased else 2
    zmax = 1.0 + amp
    out = []
    for i in range(n):
        p = i / (n - 1)
        prog = smoothstep(p) if eased else p
        if kind == "zoom_in":
            z = 1.0 + amp * prog
        elif kind == "zoom_out":
            z = zmax - amp * prog
        else:
            z = zmax
        half = 0.5 / z
        u = v = 0.5
        if kind in ("zoom_in", "zoom_out"):
            u = min(1 - half, max(half, focus[0]))
            v = min(1 - half, max(half, focus[1]))
        elif kind == "pan_right":
            u = half + (1 - 2 * half) * prog
        elif kind == "pan_left":
            u = half + (1 - 2 * half) * (1 - prog)
        elif kind == "pan_down":
            v = half + (1 - 2 * half) * prog
        elif kind == "pan_up":
            v = half + (1 - 2 * half) * (1 - prog)
        out.append((round(p * float(span), 4), round(z, 6), round(u, 6), round(v, 6)))
    return out


def window_rect(clip: dict, size, z: float, u: float, v: float) -> tuple:
    sw, sh = clip["media"]["width"], clip["media"]["height"]
    x0, y0, cw, ch = cover_window(sw, sh, size[0], size[1])
    ww, wh = cw / z, ch / z
    return x0 + u * cw - ww / 2, y0 + v * ch - wh / 2, ww, wh


def motion_span(clip: dict) -> float:
    tr = clip.get("transition") or {}
    return float(clip["duration"]) + float(tr.get("duration") or 0.0)


def duck_levels(spans: list, total: float, depth_db: float = DUCK_DB,
                attack: float = DUCK_ATTACK, release: float = DUCK_RELEASE) -> list:
    merged = []
    for a, b in sorted((float(a), float(b)) for a, b in spans if b > a):
        if merged and a - merged[-1][1] <= attack + release:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out = []
    for a, b in merged:
        for t, db in ((a - attack, 0.0), (a, depth_db), (b, depth_db), (b + release, 0.0)):
            t = round(min(float(total), max(0.0, t)), 3)
            if out and t <= out[-1][0]:
                continue
            out.append([t, db])
    return out


def level_at(levels: list, t: float) -> float:
    if not levels:
        return 0.0
    prev = levels[0]
    if t <= prev[0]:
        return float(prev[1])
    for pt in levels[1:]:
        if t <= pt[0]:
            span = pt[0] - prev[0]
            k = (t - prev[0]) / span if span > 0 else 1.0
            return float(prev[1] + (pt[1] - prev[1]) * k)
        prev = pt
    return float(prev[1])


def slice_levels(levels: list, t0: float, t1: float) -> list:
    if not levels:
        return []
    out = [[0.0, round(level_at(levels, t0), 3)]]
    out += [[round(t - t0, 3), db] for t, db in levels if t0 < t < t1]
    out.append([round(t1 - t0, 3), round(level_at(levels, t1), 3)])
    return out


def probe_media(path, cfg: dict, cache: dict) -> dict:
    key = str(path)
    if key not in cache:
        import pc_edit  # noqa: PLC0415
        if not Path(key).exists():
            die(f"media file not found: {key}")
        m = pc_edit.probe(key, cfg)
        cache[key] = {"width": m.get("width"), "height": m.get("height"),
                      "duration": float(m.get("duration") or 0.0),
                      "channels": int(m.get("channels") or 0),
                      "sample_rate": int(m.get("sample_rate") or 0),
                      "has_audio": bool(m.get("has_audio"))}
    return dict(cache[key])


def hydrate(tl: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    cache = {}
    for track in tl.get("tracks") or []:
        for clip in track.get("clips") or []:
            clip["file"] = str(Path(str(clip["file"])).expanduser().resolve())
            if not clip.get("media"):
                clip["media"] = probe_media(clip["file"], cfg, cache)
            if track.get("type") == "video" and not clip.get("kind"):
                clip["kind"] = "image" if Path(clip["file"]).suffix.lower() in IMAGE_EXT else "video"
    return tl


def validate(tl: dict) -> list:
    errs = []
    if not isinstance(tl.get("tracks"), list) or not tl["tracks"]:
        errs.append("timeline has no tracks")
        return errs
    for ti, track in enumerate(tl["tracks"]):
        ttype = track.get("type")
        if ttype not in TRACK_TYPES:
            errs.append(f"track {ti}: type must be one of {', '.join(TRACK_TYPES)}")
        last_end = -1.0
        clips = sorted(track.get("clips") or [], key=lambda c: float(c.get("start", 0)))
        for ci, clip in enumerate(clips):
            tag = f"track {track.get('name') or ti} clip {clip.get('id') or ci}"
            if not clip.get("file"):
                errs.append(f"{tag}: missing file")
            elif not Path(str(clip["file"])).expanduser().exists():
                errs.append(f"{tag}: file not found: {clip['file']}")
            try:
                start, dur = float(clip.get("start", 0)), float(clip["duration"])
            except (KeyError, TypeError, ValueError):
                errs.append(f"{tag}: start and duration must be numbers")
                continue
            if dur <= 0:
                errs.append(f"{tag}: duration must be positive")
            if start < last_end - 1e-6:
                errs.append(f"{tag}: overlaps the previous clip on the same track")
            last_end = start + dur
    return errs


def load_spec(path, cfg: dict | None = None) -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        die(f"timeline file not found: {p}")
    try:
        tl = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"timeline is not valid JSON ({exc})")
    tl.setdefault("name", p.stem)
    tl.setdefault("size", [1920, 1080])
    tl.setdefault("fps", 30)
    tl.setdefault("markers", [])
    for track in tl.get("tracks") or []:
        for clip in track.get("clips") or []:
            clip.setdefault("start", 0.0)
            clip.setdefault("source_in", 0.0)
            clip.setdefault("speed", 1.0)
    errs = validate(tl)
    if errs:
        die("timeline validation failed:\n  - " + "\n  - ".join(errs))
    ends = [float(c["start"]) + float(c["duration"])
            for t in tl["tracks"] for c in (t.get("clips") or [])]
    tl["duration"] = float(tl.get("duration") or (max(ends) if ends else 0.0))
    return hydrate(tl, cfg)


def _vo_length(shot: dict, cfg: dict) -> float:
    if shot.get("sentence"):
        return round(ffprobe_duration(shot["vo_file"], cfg), 3)
    return float(shot.get("vo_duration") or 0.0)


def _music_clips(plan: dict, total: float, vo_spans: list, cfg: dict) -> list:
    music = plan.get("music") or {}
    if not music.get("file"):
        return []
    path = Path(str(music["file"])).expanduser()
    if not path.exists():
        warn(f"music file not found: {path}")
        return []
    gain = float(music.get("gain_db", -21.0))
    fade = float(music.get("fade", 2.0))
    levels = duck_levels(vo_spans, total) if music.get("duck", True) and vo_spans else []
    length = ffprobe_duration(path, cfg)
    clips, cursor, i = [], 0.0, 0
    while cursor < total - 0.05:
        dur = round(min(length, total - cursor), 3)
        clip = {"id": f"music{i + 1}", "file": str(path.resolve()), "start": round(cursor, 3),
                "duration": dur, "source_in": 0.0, "speed": 1.0, "gain_db": gain}
        if i == 0:
            clip["fade_in"] = MUSIC_FADE_IN
        if cursor + dur >= total - 0.05:
            clip["fade_out"] = fade
        if levels:
            clip["levels"] = slice_levels(levels, cursor, cursor + dur)
        clips.append(clip)
        cursor += dur
        i += 1
    return clips


def from_plan(plan: dict, wd: Path, *, use_clips: bool = False, transitions: bool = True,
              name: str | None = None, out_dir=None, cfg: dict | None = None) -> dict:
    import pc_draw  # noqa: PLC0415
    import pc_render  # noqa: PLC0415
    import pc_subs  # noqa: PLC0415
    cfg = cfg or load_config()
    pc_render.finalize_timeline(plan)
    out = (Path(out_dir).expanduser() if out_dir else wd / "export").resolve()
    (out / "overlays").mkdir(parents=True, exist_ok=True)
    w, h, fps = plan["width"], plan["height"], plan["fps"]
    total = float(plan["total_duration"])
    shots = plan["shots"]
    cache = {}
    main, titles, vo, sfx, vo_spans = [], [], [], [], []
    for i, shot in enumerate(shots):
        src = shot.get("clip_file") if use_clips else (shot.get("video_file") or shot.get("image_file"))
        if not src or not Path(src).exists():
            warn(f"shot {shot['id']}: no media, left as a gap")
        else:
            media = probe_media(src, cfg, cache)
            footage = bool(shot.get("video_file")) and not use_clips
            clip = {"id": shot["id"], "file": str(Path(src).resolve()),
                    "kind": "video" if (footage or use_clips) else "image",
                    "start": float(shot["start"]), "duration": float(shot["duration"]),
                    "source_in": float(shot.get("video_in") or 0.0) if footage else 0.0,
                    "speed": float(shot.get("video_speed") or 1.0) if footage else 1.0,
                    "media": media, "note": shot.get("vo") or ""}
            t_out = float(shot.get("t_out") or 0.0)
            if (transitions and i < len(shots) - 1 and shot.get("transition") not in (None, "cut")
                    and t_out >= 2.0 / fps):
                clip["transition"] = {"type": shot["transition"], "duration": round(t_out, 4)}
            if clip["kind"] == "image":
                focus = None
                if shot.get("motion") in ("zoom_in", "zoom_out"):
                    focus = cover_focus(shot.get("focus"), media["width"], media["height"], w, h)
                clip["motion"] = {"kind": shot.get("motion") or "still",
                                  "amp": float(shot.get("motion_amp") or plan["timing"]["motion_amp"]),
                                  "focus": focus, "ease": bool(shot.get("ease"))}
            main.append(clip)
        if shot.get("overlay"):
            png = pc_draw.title_png(str(shot["overlay"]), w, h, out / "overlays" / f"{shot['id']}.png",
                                    plan.get("subtitles"))
            end_rel = min(3.5, max(0.6, float(shot["duration"]) - 0.1))
            dur = round(end_rel - 0.1, 3)
            titles.append({"id": f"{shot['id']}_title", "file": str(png), "kind": "image",
                           "start": round(float(shot["start"]) + 0.1, 3), "duration": dur,
                           "source_in": 0.0, "speed": 1.0, "media": probe_media(png, cfg, cache),
                           "opacity": [[0.0, 0.0], [TITLE_FADE, 1.0],
                                       [round(dur - TITLE_FADE, 3), 1.0], [dur, 0.0]]})
        if shot.get("vo_file") and Path(shot["vo_file"]).exists():
            dur = _vo_length(shot, cfg)
            if dur > 0:
                start = float(shot["vo_start"])
                vo.append({"id": f"{shot['id']}_vo", "file": str(Path(shot["vo_file"]).resolve()),
                           "start": start, "duration": dur, "source_in": 0.0, "speed": 1.0,
                           "gain_db": 0.0, "media": probe_media(shot["vo_file"], cfg, cache)})
                vo_spans.append((start, start + dur))
        if shot.get("sfx"):
            f = Path(str(shot["sfx"])).expanduser()
            if f.exists():
                dur = round(min(ffprobe_duration(f, cfg), total - float(shot["start"])), 3)
                sfx.append({"id": f"{shot['id']}_sfx", "file": str(f.resolve()),
                            "start": float(shot["start"]), "duration": dur, "source_in": 0.0,
                            "speed": 1.0, "gain_db": float(shot.get("sfx_gain_db", -8.0)),
                            "media": probe_media(f, cfg, cache)})
            else:
                warn(f"shot {shot['id']}: sfx not found: {f}")
    tracks = [{"type": "video", "name": "Shots", "clips": main}]
    if titles:
        tracks.append({"type": "video", "name": "Titles", "clips": titles})
    if vo:
        tracks.append({"type": "audio", "name": "VO", "clips": vo})
    music = _music_clips(plan, total, vo_spans, cfg)
    if music:
        for clip in music:
            clip["media"] = probe_media(clip["file"], cfg, cache)
        tracks.append({"type": "audio", "name": "Music", "clips": music})
    if sfx:
        tracks.append({"type": "audio", "name": "SFX", "clips": sfx})
    srt = out / "subs.srt"
    pc_subs.build_srt(plan, srt)
    tl = {"name": name or f"promptcut_{plan.get('project', 'draft')}",
          "size": [w, h], "fps": fps, "duration": total, "tracks": tracks,
          "markers": [{"at": float(s["start"]), "name": s["id"], "note": (s.get("vo") or "")[:80]}
                      for s in shots],
          "subtitles": {"srt": str(srt)}}
    (out / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=2), encoding="utf-8")
    return tl
