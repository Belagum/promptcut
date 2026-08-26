# -*- coding: utf-8 -*-
"""Granular ffmpeg operations: probe, cut, concat, overlay, text, audio mix,
speed, reframe, silence cut, scene detect, stills to motion clips."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from pc_common import die, ffmpeg_bin, ffprobe_bin, ffprobe_duration, info, load_config, run, warn


def _ff(cfg=None):
    return ffmpeg_bin(cfg or load_config())


def _fp(p) -> str:
    s = str(Path(p).resolve()).replace("\\", "/")
    return s.replace(":", "\\:").replace("'", "\\'")


def probe(path, cfg: dict | None = None) -> dict:
    out = run([ffprobe_bin(cfg or load_config()), "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", str(path)], desc="ffprobe")
    data = json.loads(out)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    fps = 0.0
    if v.get("r_frame_rate", "0/1") != "0/0":
        num, _, den = v.get("r_frame_rate", "0/1").partition("/")
        fps = round(float(num) / float(den or 1), 3)
    fmt = data.get("format", {})
    return {
        "path": str(path), "duration": round(float(fmt.get("duration") or 0), 3),
        "size_mb": round(int(fmt.get("size") or 0) / 1048576, 2),
        "width": v.get("width"), "height": v.get("height"), "fps": fps,
        "video_codec": v.get("codec_name"), "audio_codec": a.get("codec_name"),
        "has_audio": bool(a), "channels": a.get("channels"),
        "sample_rate": a.get("sample_rate"), "bitrate": fmt.get("bit_rate"),
        "rotation": (v.get("side_data_list") or [{}])[0].get("rotation"),
    }


def cut(src, out, start=0.0, end=None, dur=None, copy=False, cfg=None):
    cmd = [_ff(cfg), "-y", "-v", "error", "-ss", f"{float(start):.3f}"]
    if end is not None:
        dur = max(0.05, float(end) - float(start))
    if dur is not None:
        cmd += ["-t", f"{float(dur):.3f}"]
    cmd += ["-i", str(src)]
    cmd += (["-c", "copy"] if copy else
            ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k"])
    cmd += ["-movflags", "+faststart", str(out)]
    run(cmd, desc="cut")
    return Path(out)


def concat(files: list, out, xfade: str | None = None, xfade_dur: float = 0.5,
           width=None, height=None, fps=30, cfg=None):
    files = [str(f) for f in files]
    if len(files) == 1:
        shutil.copyfile(files[0], out)
        return Path(out)
    if not xfade:
        lst = Path(tempfile.mkdtemp()) / "list.txt"
        lst.write_text("".join(f"file '{Path(f).resolve().as_posix()}'\n" for f in files),
                       encoding="utf-8")
        run([_ff(cfg), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac",
             "-b:a", "192k", "-movflags", "+faststart", str(out)], desc="concat")
        shutil.rmtree(lst.parent, ignore_errors=True)
        return Path(out)

    meta = [probe(f, cfg) for f in files]
    w = width or meta[0]["width"]
    h = height or meta[0]["height"]
    cmd = [_ff(cfg), "-y", "-v", "error"]
    for f in files:
        cmd += ["-i", f]
    graph, prev, clock = [], "v0", 0.0
    for i, m in enumerate(meta):
        graph.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                     f"pad={w}:{h}:-1:-1,setsar=1,fps={fps},format=yuv420p[v{i}]")
    for i in range(1, len(files)):
        clock += max(0.1, meta[i - 1]["duration"] - xfade_dur) if i == 1 else \
                 max(0.1, meta[i - 1]["duration"] - xfade_dur)
        graph.append(f"[{prev}][v{i}]xfade=transition={xfade}:duration={xfade_dur}:"
                     f"offset={clock:.3f}[x{i}]")
        prev = f"x{i}"
    audio = [i for i, m in enumerate(meta) if m["has_audio"]]
    if audio:
        for i in audio:
            graph.append(f"[{i}:a]aresample=48000[a{i}]")
        graph.append("".join(f"[a{i}]" for i in audio) +
                     f"concat=n={len(audio)}:v=0:a=1[aout]")
    cmd += ["-filter_complex", ";".join(graph), "-map", f"[{prev}]"]
    cmd += (["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"] if audio else ["-an"])
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(out)]
    run(cmd, desc="concat with xfade")
    return Path(out)


def overlay(base, over, out, at=0.0, dur=None, x="(W-w)/2", y="(H-h)/2", scale=None,
            opacity=1.0, fade=0.0, cfg=None):
    base_meta = probe(base, cfg)
    dur = float(dur) if dur else max(0.5, base_meta["duration"] - float(at))
    pre = []
    if scale:
        pre.append(f"scale=iw*{float(scale)}:-1")
    if opacity < 1.0:
        pre.append(f"format=rgba,colorchannelmixer=aa={float(opacity):.3f}")
    if fade:
        pre.append(f"fade=t=in:st=0:d={fade}:alpha=1,"
                   f"fade=t=out:st={max(0.0, dur - fade):.3f}:d={fade}:alpha=1")
    chain = ("," + ",".join(pre)) if pre else ""
    is_img = Path(str(over)).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp")
    cmd = [_ff(cfg), "-y", "-v", "error", "-i", str(base)]
    cmd += (["-loop", "1", "-t", f"{dur:.3f}", "-i", str(over)] if is_img else ["-i", str(over)])
    graph = (f"[1:v]setpts=PTS-STARTPTS{chain}[ov];"
             f"[0:v][ov]overlay=x={x}:y={y}:enable='between(t,{float(at):.3f},"
             f"{float(at) + dur:.3f})':eof_action=pass[vout]")
    cmd += ["-filter_complex", graph, "-map", "[vout]"]
    cmd += (["-map", "0:a?", "-c:a", "copy"] if base_meta["has_audio"] else [])
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(out)]
    run(cmd, desc="overlay")
    return Path(out)


def drawtext(src, out, text, start=0.0, dur=3.0, size=None, color="white",
             position="bottom", box=True, font=None, cfg=None):
    import pc_media
    meta = probe(src, cfg)
    size = int(size or max(24, (meta["height"] or 1080) * 0.055))
    tf = Path(tempfile.mkdtemp()) / "t.txt"
    tf.write_text(text, encoding="utf-8")
    ypos = {"top": f"h*0.07", "center": "(h-text_h)/2", "bottom": "h*0.82"}.get(position, "h*0.82")
    ff = font or pc_media.font_file()
    parts = [f"drawtext=textfile='{_fp(tf)}'", f"fontsize={size}", f"fontcolor={color}",
             "x=(w-text_w)/2", f"y={ypos}", f"enable='between(t,{start},{start + dur})'"]
    parts.append(f"fontfile='{_fp(ff)}'" if ff else "font=Arial")
    if box:
        parts += ["box=1", "boxcolor=black@0.45", "boxborderw=18"]
    run([_ff(cfg), "-y", "-v", "error", "-i", str(src), "-vf", ":".join(parts),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy",
         "-movflags", "+faststart", str(out)], desc="drawtext")
    shutil.rmtree(tf.parent, ignore_errors=True)
    return Path(out)


def burn_subs(video, subs, out, cfg=None, force_style: str | None = None):
    subs = Path(subs)
    if subs.suffix.lower() == ".ass":
        vf = f"ass=filename='{_fp(subs)}'"
    else:
        vf = f"subtitles=filename='{_fp(subs)}'"
        if force_style:
            vf += f":force_style='{force_style}'"
    run([_ff(cfg), "-y", "-v", "error", "-i", str(video), "-vf", vf,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy",
         "-movflags", "+faststart", str(out)], desc="burn subs")
    return Path(out)


def mix_audio(video, out, music=None, music_db=-21.0, duck=True, normalize=True,
              voice=None, voice_db=0.0, sfx=None, cfg=None):
    """sfx: [{"file":..., "at": sec, "gain_db": -8}]"""
    meta = probe(video, cfg)
    total = meta["duration"]
    cmd = [_ff(cfg), "-y", "-v", "error", "-i", str(video)]
    idx, labels, graph = 1, [], []
    vo_label = None
    if voice:
        cmd += ["-i", str(voice)]
        graph.append(f"[{idx}:a]aresample=48000,volume={voice_db}dB[vo]")
        vo_label, idx = "vo", idx + 1
    elif meta["has_audio"]:
        graph.append("[0:a]aresample=48000[vo]")
        vo_label = "vo"
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        graph.append(f"[{idx}:a]aresample=48000,atrim=0:{total:.3f},asetpts=N/SR/TB,"
                     f"volume={music_db}dB,afade=t=in:st=0:d=1.2,"
                     f"afade=t=out:st={max(0.0, total - 2.0):.3f}:d=2[mus0]")
        idx += 1
        if vo_label and duck:
            graph.append(f"[{vo_label}]asplit=2[voa][vob]")
            graph.append("[mus0][vob]sidechaincompress=threshold=0.055:ratio=9:"
                         "attack=15:release=420[mus]")
            labels = ["voa", "mus"]
        else:
            graph.append("[mus0]anull[mus]")
            labels = ([vo_label] if vo_label else []) + ["mus"]
    elif vo_label:
        labels = [vo_label]
    for item in sfx or []:
        cmd += ["-i", str(item["file"])]
        delay = int(round(float(item.get("at", 0)) * 1000))
        graph.append(f"[{idx}:a]aresample=48000,volume={item.get('gain_db', -8)}dB,"
                     f"adelay={delay}|{delay}[s{idx}]")
        labels.append(f"s{idx}")
        idx += 1
    if not labels:
        die("nothing to mix: no source audio, no music, no voice")
    if len(labels) > 1:
        graph.append("".join(f"[{l}]" for l in labels) +
                     f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0[mx]")
        last = "mx"
    else:
        graph.append(f"[{labels[0]}]anull[mx]")
        last = "mx"
    tail = f"[{last}]apad,atrim=0:{total:.3f}"
    tail += ",loudnorm=I=-16:TP=-1.5:LRA=11" if normalize else ""
    graph.append(tail + "[aout]")
    cmd += ["-filter_complex", ";".join(graph), "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-movflags", "+faststart", str(out)]
    run(cmd, desc="mix audio")
    return Path(out)


def speed(src, out, factor=1.0, keep_pitch=True, cfg=None):
    factor = float(factor)
    if abs(factor - 1.0) < 1e-3:
        shutil.copyfile(src, out)
        return Path(out)
    meta = probe(src, cfg)
    graph = [f"[0:v]setpts={1 / factor:.6f}*PTS[v]"]
    maps = ["-map", "[v]"]
    if meta["has_audio"]:
        if keep_pitch:
            chain, left = [], factor
            while left > 2.0:
                chain.append("atempo=2.0")
                left /= 2.0
            while left < 0.5:
                chain.append("atempo=0.5")
                left /= 0.5
            chain.append(f"atempo={left:.6f}")
            graph.append(f"[0:a]{','.join(chain)}[a]")
        else:
            graph.append(f"[0:a]asetrate=48000*{factor:.6f},aresample=48000[a]")
        maps += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    run([_ff(cfg), "-y", "-v", "error", "-i", str(src), "-filter_complex", ";".join(graph),
         *maps, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-movflags", "+faststart", str(out)], desc="speed")
    return Path(out)


def reframe(src, out, aspect="9:16", mode="blur", cfg=None):
    from pc_plan import ASPECTS
    meta = probe(src, cfg)
    w, h = ASPECTS.get(aspect, (1080, 1920))
    if mode == "crop":
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1")
    elif mode == "pad":
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
              f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")
    else:
        vf = (f"split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,"
              f"crop={w}:{h},gblur=sigma=28[bg];"
              f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
    key = "-filter_complex" if mode == "blur" else "-vf"
    cmd = [_ff(cfg), "-y", "-v", "error", "-i", str(src), key, vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
    cmd += (["-c:a", "copy"] if meta["has_audio"] else ["-an"])
    cmd += ["-movflags", "+faststart", str(out)]
    run(cmd, desc="reframe")
    return Path(out)


def detect_silence(src, noise_db=-32.0, min_sil=0.45, cfg=None) -> list:
    out = run([_ff(cfg), "-hide_banner", "-i", str(src), "-af",
               f"silencedetect=noise={noise_db}dB:d={min_sil}", "-f", "null", "-"],
              desc="silencedetect")
    starts = [float(m) for m in re.findall(r"silence_start:\s*(-?[\d.]+)", out)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([\d.]+)", out)]
    pairs = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        pairs.append((max(0.0, s), e))
    return pairs


def silence_cut(src, out, noise_db=-32.0, min_sil=0.45, pad=0.08, max_segments=400, cfg=None):
    meta = probe(src, cfg)
    total = meta["duration"]
    keep, cursor = [], 0.0
    for s, e in detect_silence(src, noise_db, min_sil, cfg):
        s2 = min(total, s + pad)
        if s2 - cursor > 0.12:
            keep.append((cursor, s2))
        cursor = max(cursor, (e if e is not None else total) - pad)
    if total - cursor > 0.12:
        keep.append((cursor, total))
    if not keep:
        die("nothing left after silence cut - loosen --noise-db or --min-silence")
    if len(keep) > max_segments:
        keep.sort(key=lambda r: r[0] - r[1])
        keep = sorted(keep[:max_segments], key=lambda r: r[0])
        warn(f"too many segments, kept the {max_segments} longest")
    graph, n = [], len(keep)
    for i, (a, b) in enumerate(keep):
        graph.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        if meta["has_audio"]:
            graph.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
    pairs = "".join(f"[v{i}][a{i}]" if meta["has_audio"] else f"[v{i}]" for i in range(n))
    graph.append(f"{pairs}concat=n={n}:v=1:a={1 if meta['has_audio'] else 0}"
                 f"[vout]{'[aout]' if meta['has_audio'] else ''}")
    cmd = [_ff(cfg), "-y", "-v", "error", "-i", str(src), "-filter_complex", ";".join(graph),
           "-map", "[vout]"]
    cmd += (["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"] if meta["has_audio"] else ["-an"])
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(out)]
    run(cmd, desc="silence cut")
    kept = sum(b - a for a, b in keep)
    info(f"kept {kept:.1f}s of {total:.1f}s in {n} segments "
         f"(-{100 * (1 - kept / max(total, 0.01)):.0f}%)")
    return {"file": str(out), "segments": n, "kept": round(kept, 2), "total": round(total, 2)}


def scenes(src, threshold=0.35, cfg=None) -> list:
    out = run([_ff(cfg), "-hide_banner", "-i", str(src), "-filter:v",
               f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
              desc="scene detect")
    return [round(float(t), 3) for t in re.findall(r"pts_time:([\d.]+)", out)]


def thumb(src, out, at=1.0, cfg=None):
    run([_ff(cfg), "-y", "-v", "error", "-ss", f"{float(at):.3f}", "-i", str(src),
         "-frames:v", "1", "-q:v", "2", str(out)], desc="thumbnail")
    return Path(out)


def extract_audio(src, out, cfg=None):
    run([_ff(cfg), "-y", "-v", "error", "-i", str(src), "-vn", "-c:a", "libmp3lame",
         "-q:a", "2", str(out)], desc="extract audio")
    return Path(out)


def normalize_audio(src, out, target=-16.0, cfg=None):
    has_video = bool(probe(src, cfg)["width"])
    cmd = [_ff(cfg), "-y", "-v", "error", "-i", str(src), "-af",
           f"loudnorm=I={target}:TP=-1.5:LRA=11"]
    cmd += (["-c:v", "copy"] if has_video else ["-vn"])
    cmd += ["-c:a", "aac" if has_video else "libmp3lame", "-b:a", "192k", str(out)]
    run(cmd, desc="loudnorm")
    return Path(out)


def still_to_clip(image, out, dur=4.0, motion="zoom_in", width=1080, height=1920, fps=30,
                  amp=0.12, cfg=None):
    import pc_render
    plan = {"width": int(width), "height": int(height), "fps": int(fps),
            "timing": {"motion_amp": amp}}
    shot = {"id": Path(out).stem, "image_file": str(image), "motion": motion,
            "duration": float(dur), "t_out": 0.0}
    wd = Path(out).parent
    clip = pc_render.render_shot(shot, plan, wd, cfg or load_config(), force=True)
    if Path(clip) != Path(out):
        shutil.move(str(clip), str(out))
    return Path(out)
