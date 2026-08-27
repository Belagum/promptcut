# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pc_timeline
from pc_common import warn

RATE_MIN, RATE_MAX = 0.25, 4.0

HEAD = """using System;
using System.Collections.Generic;
using System.IO;
using ScriptPortal.Vegas;

public class EntryPoint
{
    Vegas vegas;
    Dictionary<string, Media> pool = new Dictionary<string, Media>();

    public void FromVegas(Vegas vegas)
    {
        this.vegas = vegas;
        Project p = vegas.Project;
        p.Video.Width = __W__;
        p.Video.Height = __H__;
        p.Video.FrameRate = __FPS__;
        p.Video.FieldOrder = VideoFieldOrder.ProgressiveScan;
        p.Video.PixelAspectRatio = 1.0;
"""

TAIL = """    }

    VideoTrack AddVideo(string name)
    {
        VideoTrack t = new VideoTrack(vegas.Project, vegas.Project.Tracks.Count, name);
        vegas.Project.Tracks.Add(t);
        return t;
    }

    AudioTrack AddAudio(string name)
    {
        AudioTrack t = new AudioTrack(vegas.Project, vegas.Project.Tracks.Count, name);
        vegas.Project.Tracks.Add(t);
        return t;
    }

    Media GetMedia(string path)
    {
        Media m;
        if (pool.TryGetValue(path, out m)) return m;
        m = vegas.Project.MediaPool.AddMedia(path);
        pool[path] = m;
        return m;
    }

    void Clip(VideoTrack track, string path, double start, double length, double offset,
              double rate, double fadeIn, double fadeOut, double[] pan)
    {
        Media m = GetMedia(path);
        VideoEvent ev = new VideoEvent(vegas.Project, Timecode.FromSeconds(start),
                                       Timecode.FromSeconds(length), Path.GetFileName(path));
        track.Events.Add(ev);
        Take take = new Take(m.GetVideoStreamByIndex(0));
        ev.Takes.Add(take);
        if (offset > 0) take.Offset = Timecode.FromSeconds(offset);
        if (rate != 1.0) ev.PlaybackRate = rate;
        if (fadeIn > 0) ev.FadeIn.Length = Timecode.FromSeconds(fadeIn);
        if (fadeOut > 0) ev.FadeOut.Length = Timecode.FromSeconds(fadeOut);
        PanCrop(ev, pan);
    }

    void PanCrop(VideoEvent ev, double[] k)
    {
        if (k == null || k.Length < 5) return;
        VideoMotionKeyframes kfs = ev.VideoMotion.Keyframes;
        for (int i = 0; i + 4 < k.Length; i += 5)
        {
            VideoMotionKeyframe kf;
            if (i == 0)
            {
                kf = kfs[0];
            }
            else
            {
                kf = new VideoMotionKeyframe(vegas.Project, Timecode.FromSeconds(k[i]));
                kfs.Add(kf);
            }
            float l = (float)k[i + 1], t = (float)k[i + 2], r = (float)k[i + 3], b = (float)k[i + 4];
            kf.Bounds = new VideoMotionBounds(new VideoMotionVertex(l, t), new VideoMotionVertex(r, t),
                                              new VideoMotionVertex(r, b), new VideoMotionVertex(l, b));
            kf.Type = VideoKeyframeType.Linear;
        }
    }

    void Sound(AudioTrack track, string path, double start, double length, double offset,
               double gainDb, double fadeIn, double fadeOut)
    {
        Media m = GetMedia(path);
        AudioEvent ev = new AudioEvent(vegas.Project, Timecode.FromSeconds(start),
                                       Timecode.FromSeconds(length), Path.GetFileName(path));
        track.Events.Add(ev);
        Take take = new Take(m.GetAudioStreamByIndex(0));
        ev.Takes.Add(take);
        if (offset > 0) take.Offset = Timecode.FromSeconds(offset);
        if (fadeIn > 0) ev.FadeIn.Length = Timecode.FromSeconds(fadeIn);
        if (fadeOut > 0) ev.FadeOut.Length = Timecode.FromSeconds(fadeOut);
        ev.FadeIn.Gain = (float)Math.Pow(10.0, gainDb / 20.0);
    }

    void Volume(AudioTrack track, double[] pts)
    {
        Envelope env = new Envelope(EnvelopeType.Volume);
        track.Envelopes.Add(env);
        for (int i = 0; i + 1 < pts.Length; i += 2)
        {
            double y = Math.Pow(10.0, pts[i + 1] / 20.0);
            if (i == 0 && pts[i] <= 0.0)
            {
                env.Points[0].Y = y;
                continue;
            }
            env.Points.Add(new EnvelopePoint(Timecode.FromSeconds(pts[i]), y));
        }
    }

    void Mark(double at, string name)
    {
        vegas.Project.Markers.Add(new Marker(Timecode.FromSeconds(at), name));
    }
}
"""


def _s(text) -> str:
    return '@"' + str(text).replace('"', '""') + '"'


def _f(v) -> str:
    s = f"{float(v):.4f}".rstrip("0").rstrip(".")
    return s if "." in s else s + ".0"


def _arr(values) -> str:
    if not values:
        return "null"
    return "new double[] { " + ", ".join(_f(v) for v in values) + " }"


def _pan(clip: dict, size) -> list:
    m = clip["media"]
    if not m.get("width") or not m.get("height"):
        return []
    span = pc_timeline.motion_span(clip)
    path = pc_timeline.motion_path(clip.get("motion"), span)
    if not clip.get("motion"):
        path = path[:1]
    out = []
    for t, z, u, v in path:
        left, top, ww, wh = pc_timeline.window_rect(clip, size, z, u, v)
        out += [t, left, top, left + ww, top + wh]
    full = [0.0, 0.0, 0.0, float(m["width"]), float(m["height"])]
    if len(out) == 5 and all(abs(a - b) < 0.01 for a, b in zip(out, full)):
        return []
    return out


def _fades(clip: dict) -> tuple:
    pts = clip.get("opacity") or []
    if not pts:
        return 0.0, 0.0
    dur = float(clip["duration"])
    full = [t for t, a in pts if float(a) >= 0.999]
    if not full:
        return 0.0, 0.0
    return round(float(full[0]), 3), round(max(0.0, dur - float(full[-1])), 3)


def _video_lines(track: dict, var: str, size) -> list:
    lines = []
    clips = sorted(track.get("clips") or [], key=lambda c: float(c["start"]))
    for i, clip in enumerate(clips):
        length = float(clip["duration"])
        tr = clip.get("transition")
        if tr and i + 1 < len(clips):
            length += float(tr.get("duration") or 0.0)
        rate = float(clip.get("speed") or 1.0)
        if not RATE_MIN <= rate <= RATE_MAX:
            warn(f"{clip.get('id')}: VEGAS playback rate is limited to {RATE_MIN}..{RATE_MAX}, got {rate}")
            rate = min(RATE_MAX, max(RATE_MIN, rate))
        fade_in, fade_out = _fades(clip)
        lines.append(f"        Clip({var}, {_s(clip['file'])}, {_f(clip['start'])}, {_f(length)}, "
                     f"{_f(clip.get('source_in') or 0.0)}, {_f(rate)}, {_f(fade_in)}, {_f(fade_out)}, "
                     f"{_arr(_pan(clip, size))});")
    return lines


def _audio_lines(track: dict, var: str) -> list:
    lines, env = [], []
    for clip in sorted(track.get("clips") or [], key=lambda c: float(c["start"])):
        lines.append(f"        Sound({var}, {_s(clip['file'])}, {_f(clip['start'])}, {_f(clip['duration'])}, "
                     f"{_f(clip.get('source_in') or 0.0)}, {_f(clip.get('gain_db') or 0.0)}, "
                     f"{_f(clip.get('fade_in') or 0.0)}, {_f(clip.get('fade_out') or 0.0)});")
        for t, db in clip.get("levels") or []:
            at = round(float(clip["start"]) + float(t), 3)
            if env and at <= env[-2]:
                continue
            env += [at, float(db)]
    if env:
        lines.append(f"        Volume({var}, {_arr(env)});")
    return lines


def write(tl: dict, out_dir) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = tl.get("name") or "promptcut"
    script = out_dir / f"{name}.vegas.cs"
    project = out_dir / f"{name}.veg"
    size = (int(tl["size"][0]), int(tl["size"][1]))
    body, counts = [], {"clips": 0, "tracks": 0}
    video = [t for t in tl["tracks"] if t.get("type") == "video" and t.get("clips")]
    audio = [t for t in tl["tracks"] if t.get("type") == "audio" and t.get("clips")]
    for i, track in enumerate(reversed(video)):
        var = f"v{i + 1}"
        body.append(f"        VideoTrack {var} = AddVideo({_s(track.get('name') or var)});")
        lines = _video_lines(track, var, size)
        body += lines
        counts["clips"] += len(lines)
        counts["tracks"] += 1
    for i, track in enumerate(audio):
        var = f"a{i + 1}"
        body.append(f"        AudioTrack {var} = AddAudio({_s(track.get('name') or var)});")
        lines = _audio_lines(track, var)
        body += lines
        counts["clips"] += len(track["clips"])
        counts["tracks"] += 1
    for mk in tl.get("markers") or []:
        body.append(f"        Mark({_f(mk.get('at') or 0.0)}, {_s(mk.get('name') or '')});")
    body.append(f"        vegas.SaveProject({_s(project)});")
    head = (HEAD.replace("__W__", str(size[0])).replace("__H__", str(size[1]))
            .replace("__FPS__", _f(tl["fps"])))
    script.write_text(head + "\n".join(body) + "\n" + TAIL, encoding="utf-8-sig")
    return {"script": str(script), "project": str(project), **counts}
