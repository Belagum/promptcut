# -*- coding: utf-8 -*-
"""ffmpeg assembly: still-image motion, transitions, audio buses, subtitles."""
from __future__ import annotations

import shutil
from pathlib import Path

import pc_subs
from pc_common import ffmpeg_bin, ffprobe_duration, info, load_config, run, warn

XFADE_ALIASES = {"cut": "fade", "dissolve": "dissolve", "fade": "fade"}


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


def _zoompan(shot: dict, plan: dict, frames: int) -> str:
    amp = float(plan["timing"]["motion_amp"])
    zmax = 1.0 + amp
    m = shot["motion"]
    prog = f"(on/{max(1, frames - 1)})"
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
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
    if out.exists() and not force and abs(ffprobe_duration(out, cfg) - length) < 0.08:
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


def assemble(plan: dict, wd: Path, out_path: Path, *, cfg: dict | None = None,
             burn_subs: bool = True, crf: int = 20, preset: str = "medium") -> Path:
    cfg = cfg or load_config()
    shots = plan["shots"]
    clips = [Path(s["clip_file"]) for s in shots]
    total = float(plan["total_duration"])
    ff = [ffmpeg_bin(cfg), "-y", "-v", "error", "-stats"]
    for clip in clips:
        ff += ["-i", str(clip)]
    inputs = []
    idx = len(clips)
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
    if len(clips) == 1:
        vlabel = "0:v"
    else:
        prev = "0:v"
        clock = 0.0
        for i in range(1, len(clips)):
            dur = float(shots[i - 1]["t_out"]) or 1.0 / plan["fps"]
            clock += float(shots[i - 1]["duration"])
            kind = shots[i - 1]["transition"]
            trans = XFADE_ALIASES.get(kind, kind)
            lbl = f"vx{i}"
            graph.append(f"[{prev}][{i}:v]xfade=transition={trans}:duration={dur:.4f}:"
                         f"offset={clock:.4f}[{lbl}]")
            prev = lbl
        vlabel = prev

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
    ff += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-r", str(plan["fps"]),
           "-movflags", "+faststart", "-t", f"{total:.3f}", str(out_path)]
    info(f"final render: {out_path.name} ({total:.1f}s, {len(clips)} shots)")
    run(ff, desc="final assembly", quiet=True)
    pc_subs.build_srt(plan, out_path.with_suffix(".srt"))
    return out_path


def render_all(plan: dict, wd: Path, out_path: Path, *, cfg: dict | None = None,
               burn_subs: bool = True, force: bool = False, crf: int = 20,
               preset: str = "medium") -> Path:
    cfg = cfg or load_config()
    finalize_timeline(plan)
    for shot in plan["shots"]:
        shot["clip_file"] = str(render_shot(shot, plan, wd, cfg, force=force))
    return assemble(plan, wd, out_path, cfg=cfg, burn_subs=burn_subs, crf=crf, preset=preset)
