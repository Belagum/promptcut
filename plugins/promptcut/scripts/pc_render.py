# -*- coding: utf-8 -*-
"""ffmpeg assembly: still-image motion, transitions, audio buses, subtitles."""
from __future__ import annotations

import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pc_subs
from pc_common import ffmpeg_bin, ffprobe_duration, info, load_config, run, sha, warn

XFADE_ALIASES = {"dissolve": "dissolve", "fade": "fade"}

_NVENC: bool | None = None


def _has_nvenc(cfg: dict) -> bool:
    """One tiny probe encode; consumer GPUs cap concurrent sessions, so NVENC
    is reserved for the single long final pass."""
    global _NVENC
    if _NVENC is None:
        try:
            r = subprocess.run(
                [ffmpeg_bin(cfg), "-v", "error", "-f", "lavfi", "-i",
                 "color=black:s=256x256:d=0.2", "-c:v", "h264_nvenc", "-f", "null", "-"],
                capture_output=True, timeout=30)
            _NVENC = r.returncode == 0
        except Exception:
            _NVENC = False
        if _NVENC:
            info("hardware encoder: h264_nvenc")
    return _NVENC


def _final_codec(cfg: dict, crf: int, preset: str) -> list:
    enc = (cfg.get("video_encoder") or "auto").lower()
    if enc != "cpu" and (enc == "nvenc" or _has_nvenc(cfg)):
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                "-cq", str(crf), "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]


def _jobs(cfg: dict) -> int:
    try:
        j = int(cfg.get("render_jobs") or 0)
    except (TypeError, ValueError):
        j = 0
    return j if j > 0 else min(8, max(2, (os.cpu_count() or 4) - 1))


def _ffpath(p) -> str:
    s = str(Path(p).resolve()).replace("\\", "/")
    return s.replace(":", "\\:").replace("'", "\\'")


def finalize_timeline(plan: dict) -> dict:
    """Clamp transition lengths so xfade fits inside both neighbouring clips."""
    shots = plan["shots"]
    for i, shot in enumerate(shots[:-1]):
        nxt = shots[i + 1]
        cap = 0.8 * min(shot["duration"], nxt["duration"])
        if shot["t_out"] > cap:
            shot["t_out"] = round(max(1.0 / plan["fps"], cap), 4)
    if shots:
        shots[-1]["t_out"] = 0.0
    return plan


def _parse_focus(focus, shot: dict):
    if not focus:
        return None
    if isinstance(focus, str):
        focus = focus.split(",")
    try:
        return float(focus[0]), float(focus[1])
    except (TypeError, ValueError, IndexError):
        warn(f"shot {shot.get('id')}: bad focus {focus!r}, expected [x,y] in 0..1")
        return None


def _adjust_focus(shot: dict, w: int, h: int, cfg: dict) -> None:
    """Map focus from source-image coords onto the crop-to-cover frame."""
    focus = _parse_focus(shot.get("focus"), shot)
    if not focus or shot.get("motion") not in ("zoom_in", "zoom_out"):
        return
    import pc_edit  # noqa: PLC0415
    import pc_timeline  # noqa: PLC0415
    meta = pc_edit.probe(shot["image_file"], cfg)
    sw, sh = meta.get("width"), meta.get("height")
    if not sw or not sh:
        return
    shot["_focus"] = pc_timeline.cover_focus(focus, sw, sh, w, h)


def _zoompan(shot: dict, plan: dict, frames: int) -> str:
    amp = float(shot.get("motion_amp") or plan["timing"]["motion_amp"])
    zmax = 1.0 + amp
    m = shot["motion"]
    p = f"(on/{max(1, frames - 1)})"
    prog = f"({p}*{p}*(3-2*{p}))" if shot.get("ease") else p
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    focus = _parse_focus(shot.get("_focus") or shot.get("focus"), shot)
    if focus and m in ("zoom_in", "zoom_out"):
        fx, fy = focus
        cx = f"clip(iw*{fx:.4f}-iw/(2*zoom),0,iw-iw/zoom)"
        cy = f"clip(ih*{fy:.4f}-ih/(2*zoom),0,ih-ih/zoom)"
    if m == "zoom_in":
        z, x, y = f"1+{amp}*{prog}", cx, cy
    elif m == "zoom_out":
        z, x, y = f"{zmax}-{amp}*{prog}", cx, cy
    elif m == "pan_right":
        z, x, y = f"{zmax}", f"(iw-iw/zoom)*{prog}", cy
    elif m == "pan_left":
        z, x, y = f"{zmax}", f"(iw-iw/zoom)*(1-{prog})", cy
    elif m == "pan_down":
        z, x, y = f"{zmax}", cx, f"(ih-ih/zoom)*{prog}"
    elif m == "pan_up":
        z, x, y = f"{zmax}", cx, f"(ih-ih/zoom)*(1-{prog})"
    else:
        z, x, y = "1", cx, cy
    return (f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={plan['width']}x{plan['height']}"
            f":fps={plan['fps']}")


def render_shot(shot: dict, plan: dict, wd: Path, cfg: dict, force: bool = False) -> Path:
    out = wd / "clips" / f"{shot['id']}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    length = round(float(shot["duration"]) + float(shot["t_out"]), 3)
    src = shot.get("video_file") or shot.get("image_file")
    stat = Path(src).stat() if src and Path(src).exists() else None
    key = sha("clip1", shot.get("motion"), shot.get("focus"), shot.get("ease"),
              shot.get("motion_amp"), plan["timing"].get("motion_amp"),
              shot.get("video_in"), shot.get("video_speed"), src,
              stat.st_size if stat else 0, int(stat.st_mtime) if stat else 0,
              length, plan["width"], plan["height"], plan["fps"])
    tag = out.with_suffix(".key")
    if out.exists() and not force and tag.exists() and tag.read_text() == key:
        info(f"clip {shot['id']} already rendered")
        return out
    w, h, fps = plan["width"], plan["height"], plan["fps"]
    frames = max(2, int(round(length * fps)))
    ff = [ffmpeg_bin(cfg), "-y", "-v", "error"]
    if shot.get("video_file"):
        speed = float(shot.get("video_speed") or 1.0)
        src_len = ffprobe_duration(shot["video_file"], cfg)
        start = float(shot.get("video_in") or 0.0)
        if src_len - start < length * speed:
            ff += ["-stream_loop", "-1"]
        ff += ["-ss", f"{start:.3f}", "-i", str(shot["video_file"])]
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
              f"setsar=1,setpts=PTS/{speed:.6f},fps={fps},trim=duration={length},"
              f"format=yuv420p")
    elif shot.get("image_file"):
        big_w, big_h = w * 2, h * 2
        _adjust_focus(shot, w, h, cfg)
        ff += ["-loop", "1", "-framerate", str(fps), "-t", f"{length}", "-i", str(shot["image_file"])]
        vf = (f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase,"
              f"crop={big_w}:{big_h},setsar=1,{_zoompan(shot, plan, frames)},"
              f"trim=duration={length},format=yuv420p")
    else:
        ff += ["-f", "lavfi", "-t", f"{length}", "-i",
               f"color=c=black:s={w}x{h}:r={fps}"]
        vf = f"format=yuv420p,setsar=1"
    ff += ["-vf", vf, "-frames:v", str(frames), "-an",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    run(ff, desc=f"render shot {shot['id']}")
    tag.write_text(key)
    return out


def _audio_graph(plan: dict, inputs: list, total: float) -> tuple:
    parts, vo_labels, sfx_labels = [], [], []
    for kind, idx, meta in inputs:
        if kind == "vo":
            delay = int(round(float(meta["vo_start"]) * 1000))
            lbl = f"vo{idx}"
            parts.append(f"[{idx}:a]aresample=48000,aformat=sample_fmts=fltp:"
                         f"channel_layouts=stereo,adelay={delay}|{delay}[{lbl}]")
            vo_labels.append(lbl)
        elif kind == "sfx":
            delay = int(round(float(meta["at"]) * 1000))
            gain = float(meta.get("gain_db", -8.0))
            lbl = f"sfx{idx}"
            parts.append(f"[{idx}:a]aresample=48000,aformat=sample_fmts=fltp:"
                         f"channel_layouts=stereo,volume={gain}dB,adelay={delay}|{delay}[{lbl}]")
            sfx_labels.append(lbl)

    bus = None
    if vo_labels:
        if len(vo_labels) == 1:
            parts.append(f"[{vo_labels[0]}]anull[vobus]")
        else:
            parts.append("".join(f"[{l}]" for l in vo_labels) +
                         f"amix=inputs={len(vo_labels)}:normalize=0:dropout_transition=0[vobus]")
        bus = "vobus"

    music = next((i for i in inputs if i[0] == "music"), None)
    if music:
        _, midx, meta = music
        gain = float(meta.get("gain_db", -21.0))
        fade = float(meta.get("fade", 2.0))
        parts.append(f"[{midx}:a]aresample=48000,aformat=sample_fmts=fltp:"
                     f"channel_layouts=stereo,atrim=0:{total:.3f},asetpts=N/SR/TB,"
                     f"volume={gain}dB,afade=t=in:st=0:d=1.2,"
                     f"afade=t=out:st={max(0.0, total - fade):.3f}:d={fade}[mus0]")
        if bus and meta.get("duck", True):
            parts.append(f"[{bus}]asplit=2[{bus}a][{bus}b]")
            parts.append(f"[mus0][{bus}b]sidechaincompress=threshold=0.055:ratio=9:"
                         f"attack=15:release=420:makeup=1[mus]")
            bus_main = f"{bus}a"
        else:
            parts.append("[mus0]anull[mus]")
            bus_main = bus
        if bus_main:
            parts.append(f"[{bus_main}][mus]amix=inputs=2:normalize=0:dropout_transition=0[mix0]")
        else:
            parts.append("[mus]anull[mix0]")
        bus = "mix0"

    if sfx_labels:
        src = f"[{bus}]" if bus else ""
        count = len(sfx_labels) + (1 if bus else 0)
        parts.append(src + "".join(f"[{l}]" for l in sfx_labels) +
                     f"amix=inputs={count}:normalize=0:dropout_transition=0[mix1]")
        bus = "mix1"

    if not bus:
        return parts, None
    parts.append(f"[{bus}]apad,atrim=0:{total:.3f},"
                 f"loudnorm=I=-16:TP=-1.5:LRA=11,aformat=sample_fmts=fltp:"
                 f"sample_rates=48000:channel_layouts=stereo[aout]")
    return parts, "aout"


def _seg_encode(cfg: dict, fps: int) -> list:
    return ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart"]


def _build_segments(plan: dict, wd: Path, cfg: dict) -> list:
    """Cut clip bodies and render tiny per-boundary transition pieces.

    A chain of 80+ xfades in one filter graph deadlocks ffmpeg silently
    (video stream ends early, audio keeps going), so the timeline becomes a
    flat list of short segments joined by the concat demuxer instead."""
    shots = plan["shots"]
    fps = plan["fps"]
    segdir = wd / "segments"
    shutil.rmtree(segdir, ignore_errors=True)
    segdir.mkdir(parents=True, exist_ok=True)

    def soft(i: int) -> float:
        # boundary after shot i is a real transition, not a hard cut
        if i >= len(shots) - 1:
            return 0.0
        kind = shots[i].get("transition") or "cut"
        d = float(shots[i]["t_out"])
        return d if kind != "cut" and d >= 2.0 / fps else 0.0

    jobs = []
    order = []
    for i, shot in enumerate(shots):
        head = soft(i - 1) if i > 0 else 0.0
        body_len = round(float(shot["duration"]) - head, 3)
        body = segdir / f"b{i:03d}.mp4"
        jobs.append([ffmpeg_bin(cfg), "-y", "-v", "error",
                     "-ss", f"{head:.3f}", "-i", shot["clip_file"],
                     "-t", f"{body_len:.3f}"] + _seg_encode(cfg, fps) + [str(body)])
        order.append(body)
        d = soft(i)
        if d > 0:
            kind = shots[i].get("transition") or "dissolve"
            trans = XFADE_ALIASES.get(kind, kind)
            tr = segdir / f"t{i:03d}.mp4"
            jobs.append([ffmpeg_bin(cfg), "-y", "-v", "error",
                         "-ss", f"{float(shot['duration']):.3f}", "-t", f"{d:.3f}",
                         "-i", shot["clip_file"],
                         "-t", f"{d:.3f}", "-i", shots[i + 1]["clip_file"],
                         "-filter_complex",
                         f"[0:v]fps={fps},settb=AVTB[a];[1:v]fps={fps},settb=AVTB[b];"
                         f"[a][b]xfade=transition={trans}:duration={d:.3f}:offset=0[v]",
                         "-map", "[v]"] + _seg_encode(cfg, fps) + [str(tr)])
            order.append(tr)

    with ThreadPoolExecutor(max_workers=_jobs(cfg)) as pool:
        list(pool.map(lambda c: run(c, desc=Path(c[-1]).stem), jobs))
    return order


def assemble(plan: dict, wd: Path, out_path: Path, *, cfg: dict | None = None,
             burn_subs: bool = True, crf: int = 20, preset: str = "medium") -> Path:
    cfg = cfg or load_config()
    shots = plan["shots"]
    total = float(plan["total_duration"])

    segments = _build_segments(plan, wd, cfg)
    lst = wd / "segments" / "list.txt"
    lst.write_text("".join(f"file '{Path(s).resolve().as_posix()}'\n" for s in segments),
                   encoding="utf-8")

    ff = [ffmpeg_bin(cfg), "-y", "-v", "error", "-stats",
          "-f", "concat", "-safe", "0", "-i", str(lst)]
    inputs = []
    idx = 1
    for shot in shots:
        if shot.get("vo_file"):
            ff += ["-i", str(shot["vo_file"])]
            inputs.append(("vo", idx, shot))
            idx += 1
    music = (plan.get("music") or {}).get("file")
    if music:
        ff += ["-stream_loop", "-1", "-i", str(Path(str(music)).expanduser())]
        inputs.append(("music", idx, plan["music"]))
        idx += 1
    for shot in shots:
        if shot.get("sfx"):
            ff += ["-i", str(Path(str(shot["sfx"])).expanduser())]
            inputs.append(("sfx", idx, {"at": shot["start"],
                                        "gain_db": shot.get("sfx_gain_db", -8.0)}))
            idx += 1

    graph = []
    vlabel = "0:v"
    if burn_subs and plan["subtitles"].get("enabled", True):
        ass = pc_subs.build_ass(plan, wd / "subs.ass")
        graph.append(f"[{vlabel}]ass=filename='{_ffpath(ass)}'[vout]")
        vlabel = "vout"

    aparts, alabel = _audio_graph(plan, inputs, total)
    graph += aparts
    if graph:
        ff += ["-filter_complex", ";".join(graph)]
    ff += ["-map", f"[{vlabel}]" if not vlabel.endswith(":v") else vlabel]
    if alabel:
        ff += ["-map", f"[{alabel}]", "-c:a", "aac", "-b:a", "192k"]
    else:
        ff += ["-an"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ff += _final_codec(cfg, crf, preset)
    ff += ["-pix_fmt", "yuv420p", "-r", str(plan["fps"]),
           "-movflags", "+faststart", "-t", f"{total:.3f}", str(out_path)]
    info(f"final render: {out_path.name} ({total:.1f}s, {len(shots)} shots, "
         f"{len(segments)} segments)")
    run(ff, desc="final assembly", quiet=True)
    pc_subs.build_srt(plan, out_path.with_suffix(".srt"))
    return out_path


def render_all(plan: dict, wd: Path, out_path: Path, *, cfg: dict | None = None,
               burn_subs: bool = True, force: bool = False, crf: int = 20,
               preset: str = "medium") -> Path:
    cfg = cfg or load_config()
    finalize_timeline(plan)
    with ThreadPoolExecutor(max_workers=_jobs(cfg)) as pool:
        files = pool.map(lambda s: str(render_shot(s, plan, wd, cfg, force=force)),
                         plan["shots"])
        for shot, f in zip(plan["shots"], files):
            shot["clip_file"] = f
    return assemble(plan, wd, out_path, cfg=cfg, burn_subs=burn_subs, crf=crf, preset=preset)
