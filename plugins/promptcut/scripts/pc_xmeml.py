# -*- coding: utf-8 -*-
from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

import pc_timeline
from pc_common import warn

PROFILES = {
    "premiere": {"scale_basis": "native", "center_unit": "frame"},
    "resolve": {"scale_basis": "fit", "center_unit": "frame"},
    "vegas": {"scale_basis": "native", "center_unit": "frame"},
}
STILL_SECONDS = 3600
LEVEL_MAX = 3.98109


def _sub(parent, tag, text=None):
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = str(text)
    return el


def _bool(v) -> str:
    return "TRUE" if v else "FALSE"


def _rate(parent, fps):
    r = _sub(parent, "rate")
    _sub(r, "timebase", int(fps))
    _sub(r, "ntsc", "FALSE")
    return r


def _timecode(parent, fps):
    tc = _sub(parent, "timecode")
    _rate(tc, fps)
    _sub(tc, "string", "00:00:00:00")
    _sub(tc, "frame", 0)
    _sub(tc, "displayformat", "NDF")
    return tc


def pathurl(path) -> str:
    posix = Path(path).resolve().as_posix().lstrip("/")
    return "file://localhost/" + quote(posix, safe="/:")


def _video_chars(parent, fps, w, h, depth=False):
    sc = _sub(parent, "samplecharacteristics")
    _rate(sc, fps)
    _sub(sc, "width", int(w))
    _sub(sc, "height", int(h))
    _sub(sc, "anamorphic", "FALSE")
    _sub(sc, "pixelaspectratio", "square")
    _sub(sc, "fielddominance", "none")
    if depth:
        _sub(sc, "colordepth", 24)
    return sc


def _audio_chars(parent, rate=48000):
    sc = _sub(parent, "samplecharacteristics")
    _sub(sc, "depth", 16)
    _sub(sc, "samplerate", int(rate or 48000))
    return sc


def _param(effect, pid, name, value=None, keyframes=None, vmin=None, vmax=None):
    p = _sub(effect, "parameter")
    _sub(p, "parameterid", pid)
    _sub(p, "name", name)
    if vmin is not None:
        _sub(p, "valuemin", vmin)
    if vmax is not None:
        _sub(p, "valuemax", vmax)
    if keyframes:
        for when, val in keyframes:
            kf = _sub(p, "keyframe")
            _sub(kf, "when", int(when))
            _value(kf, val)
    else:
        _value(p, value)
    return p


def _value(parent, val):
    if isinstance(val, (tuple, list)):
        v = _sub(parent, "value")
        _sub(v, "horiz", _num(val[0]))
        _sub(v, "vert", _num(val[1]))
    else:
        _sub(parent, "value", _num(val))


def _num(v) -> str:
    if isinstance(v, str):
        return v
    s = f"{float(v):.6f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _effect(clipitem, name, effectid, category, etype, mediatype):
    f = _sub(clipitem, "filter")
    e = _sub(f, "effect")
    _sub(e, "name", name)
    _sub(e, "effectid", effectid)
    _sub(e, "effectcategory", category)
    _sub(e, "effecttype", etype)
    _sub(e, "mediatype", mediatype)
    return e


class _Writer:
    def __init__(self, tl: dict, profile: dict):
        self.tl = tl
        self.profile = profile
        self.fps = int(tl["fps"])
        self.w, self.h = int(tl["size"][0]), int(tl["size"][1])
        self.files = {}
        self.clip_ids = 0
        self.counts = {"clips": 0, "transitions": 0, "tracks": 0}

    def f(self, t) -> int:
        return pc_timeline.frames(t, self.fps)

    def next_clip_id(self) -> str:
        self.clip_ids += 1
        return f"clipitem-{self.clip_ids}"

    def file_frames(self, clip: dict) -> int:
        m = clip["media"]
        if clip.get("kind") == "image" or not m.get("duration"):
            return STILL_SECONDS * self.fps
        return max(1, self.f(m["duration"]))

    def file_el(self, parent, clip: dict, want_video: bool):
        path = clip["file"]
        if path in self.files:
            el = _sub(parent, "file")
            el.set("id", self.files[path])
            return el
        fid = f"file-{len(self.files) + 1}"
        self.files[path] = fid
        el = _sub(parent, "file")
        el.set("id", fid)
        _sub(el, "name", Path(path).name)
        _sub(el, "pathurl", pathurl(path))
        _rate(el, self.fps)
        _sub(el, "duration", self.file_frames(clip))
        _timecode(el, self.fps)
        media = _sub(el, "media")
        m = clip["media"]
        if want_video and m.get("width") and m.get("height"):
            v = _sub(media, "video")
            _video_chars(v, self.fps, m["width"], m["height"])
        if m.get("has_audio") or (not want_video and m.get("channels")):
            a = _sub(media, "audio")
            _audio_chars(a, m.get("sample_rate") or 48000)
            _sub(a, "channelcount", max(1, int(m.get("channels") or 1)))
        return el

    def motion_keyframes(self, clip: dict, src_in: int) -> tuple:
        sw, sh = clip["media"]["width"], clip["media"]["height"]
        basis = min(self.w / sw, self.h / sh) if self.profile["scale_basis"] == "fit" else 1.0
        ux = self.w if self.profile["center_unit"] == "frame" else self.w / 2
        uy = self.h if self.profile["center_unit"] == "frame" else self.h / 2
        scale, center = [], []
        speed = float(clip.get("speed") or 1.0)
        for t, z, u, v in pc_timeline.motion_path(clip.get("motion"), pc_timeline.motion_span(clip)):
            left, top, ww, wh = pc_timeline.window_rect(clip, (self.w, self.h), z, u, v)
            s = self.w / ww
            dx = (sw / 2 - (left + ww / 2)) * s
            dy = (sh / 2 - (top + wh / 2)) * s
            when = src_in + self.f(t * speed)
            scale.append((when, round(100 * s / basis, 4)))
            center.append((when, (round(dx / ux, 6), round(dy / uy, 6))))
        return scale, center

    def add_motion(self, item, clip: dict, src_in: int):
        if not clip["media"].get("width") or not clip["media"].get("height"):
            return
        scale, center = self.motion_keyframes(clip, src_in)
        identity = (all(abs(s - 100) < 0.01 for _, s in scale)
                    and all(abs(c[0]) < 1e-5 and abs(c[1]) < 1e-5 for _, c in center))
        if identity:
            return
        e = _effect(item, "Basic Motion", "basic", "motion", "motion", "video")
        if len({s for _, s in scale}) == 1:
            _param(e, "scale", "Scale", scale[0][1], vmin=0, vmax=1000)
        else:
            _param(e, "scale", "Scale", keyframes=scale, vmin=0, vmax=1000)
        _param(e, "rotation", "Rotation", 0, vmin=-8640, vmax=8640)
        if len({c for _, c in center}) == 1:
            _param(e, "center", "Center", center[0][1])
        else:
            _param(e, "center", "Center", keyframes=center)
        _param(e, "centerOffset", "Anchor Point", (0, 0))

    def add_opacity(self, item, clip: dict, src_in: int):
        pts = clip.get("opacity")
        if not pts:
            return
        speed = float(clip.get("speed") or 1.0)
        kfs = [(src_in + self.f(t * speed), round(100 * float(a), 3)) for t, a in pts]
        e = _effect(item, "Opacity", "opacity", "motion", "motion", "video")
        _param(e, "opacity", "opacity", keyframes=kfs, vmin=0, vmax=100)

    def add_speed(self, item, speed: float):
        e = _effect(item, "Time Remap", "timeremap", "motion", "motion", "video")
        _param(e, "variablespeed", "variablespeed", 0, vmin=0, vmax=1)
        _param(e, "speed", "speed", round(speed * 100, 3), vmin=-100000, vmax=100000)
        _param(e, "reverse", "reverse", "FALSE")
        _param(e, "frameblending", "frameblending", "FALSE")

    def add_levels(self, item, clip: dict, src_in: int, length: float):
        gain = float(clip.get("gain_db") or 0.0)
        fade_in = float(clip.get("fade_in") or 0.0)
        fade_out = float(clip.get("fade_out") or 0.0)
        levels = clip.get("levels") or []
        e = _effect(item, "Audio Levels", "audiolevels", "audiolevels", "audiolevels", "audio")
        if not fade_in and not fade_out and not levels:
            _param(e, "level", "Level", round(min(LEVEL_MAX, pc_timeline.db_to_gain(gain)), 6),
                   vmin=0, vmax=LEVEL_MAX)
            return
        times = {0.0, length}
        if fade_in:
            times.add(min(length, fade_in))
        if fade_out:
            times.add(max(0.0, length - fade_out))
        times.update(min(length, max(0.0, float(t))) for t, _ in levels)
        kfs = []
        for t in sorted(times):
            fade = 1.0
            if fade_in:
                fade = min(fade, t / fade_in)
            if fade_out:
                fade = min(fade, (length - t) / fade_out)
            lin = pc_timeline.db_to_gain(gain + pc_timeline.level_at(levels, t)) * max(0.0, fade)
            kfs.append((src_in + self.f(t), round(min(LEVEL_MAX, lin), 6)))
        _param(e, "level", "Level", keyframes=kfs, vmin=0, vmax=LEVEL_MAX)

    def video_track(self, parent, track: dict, transitions: bool):
        tr_el = _sub(parent, "track")
        clips = sorted(track.get("clips") or [], key=lambda c: float(c["start"]))
        n = len(clips)
        bounds = []
        for i, clip in enumerate(clips):
            fs = self.f(clip["start"])
            fe = self.f(float(clip["start"]) + float(clip["duration"]))
            if i + 1 < n:
                nxt = self.f(clips[i + 1]["start"])
                if abs(nxt - fe) <= 1:
                    fe = nxt
            bounds.append([fs, max(fs + 1, fe)])
        pending = None
        for i, clip in enumerate(clips):
            fs, fe = bounds[i]
            tr = clip.get("transition") if transitions else None
            contiguous = i + 1 < n and bounds[i + 1][0] == fe
            d = self.f(tr["duration"]) if tr and contiguous else 0
            speed = float(clip.get("speed") or 1.0)
            src_in = self.f(float(clip.get("source_in") or 0.0) * speed) if speed != 1.0 \
                else self.f(clip.get("source_in") or 0.0)
            src_len = self.f((fe - fs) / self.fps * speed) + (self.f(d / self.fps * speed) if d else 0)
            limit = self.file_frames(clip)
            if src_in + src_len > limit:
                if clip.get("kind") == "video":
                    warn(f"{clip.get('id') or Path(clip['file']).name}: footage is shorter than the "
                         f"shot, the clip ends early in the editor")
                src_len = max(1, limit - src_in)
            item = _sub(tr_el, "clipitem")
            item.set("id", self.next_clip_id())
            _sub(item, "name", Path(clip["file"]).name)
            _sub(item, "enabled", "TRUE")
            _sub(item, "duration", limit)
            _rate(item, self.fps)
            _sub(item, "start", -1 if pending else fs)
            _sub(item, "end", -1 if d else fe)
            _sub(item, "in", src_in)
            _sub(item, "out", src_in + src_len)
            _sub(item, "alphatype", "straight" if track.get("name") == "Titles" else "none")
            _sub(item, "pixelaspectratio", "square")
            _sub(item, "anamorphic", "FALSE")
            if clip.get("kind") == "image":
                _sub(item, "stillframe", "TRUE")
            self.file_el(item, clip, True)
            self.add_motion(item, clip, src_in)
            self.add_opacity(item, clip, src_in)
            if speed != 1.0:
                self.add_speed(item, speed)
            self.counts["clips"] += 1
            pending = None
            if d:
                t_el = _sub(tr_el, "transitionitem")
                _sub(t_el, "start", fe)
                _sub(t_el, "end", fe + d)
                _sub(t_el, "alignment", "start")
                _rate(t_el, self.fps)
                eff = _sub(t_el, "effect")
                _sub(eff, "name", "Cross Dissolve")
                _sub(eff, "effectid", "Cross Dissolve")
                _sub(eff, "effectcategory", "Dissolve")
                _sub(eff, "effecttype", "transition")
                _sub(eff, "mediatype", "video")
                _sub(eff, "wipecode", 0)
                _sub(eff, "wipeaccuracy", 100)
                _sub(eff, "startratio", 0)
                _sub(eff, "endratio", 1)
                _sub(eff, "reverse", "FALSE")
                self.counts["transitions"] += 1
                pending = True
        _sub(tr_el, "enabled", "TRUE")
        _sub(tr_el, "locked", "FALSE")
        self.counts["tracks"] += 1

    def audio_tracks(self, parent, track: dict, first_index: int) -> int:
        clips = sorted(track.get("clips") or [], key=lambda c: float(c["start"]))
        stereo = any(int(c["media"].get("channels") or 1) >= 2 for c in clips)
        els = [_sub(parent, "track") for _ in range(2 if stereo else 1)]
        for ci, clip in enumerate(clips):
            chans = min(len(els), max(1, int(clip["media"].get("channels") or 1)))
            fs = self.f(clip["start"])
            fe = max(fs + 1, self.f(float(clip["start"]) + float(clip["duration"])))
            src_in = self.f(clip.get("source_in") or 0.0)
            limit = self.file_frames(clip)
            src_len = min(fe - fs, max(1, limit - src_in))
            ids = [self.next_clip_id() for _ in range(chans)]
            for ch in range(chans):
                item = _sub(els[ch], "clipitem")
                item.set("id", ids[ch])
                _sub(item, "name", Path(clip["file"]).name)
                _sub(item, "enabled", "TRUE")
                _sub(item, "duration", limit)
                _rate(item, self.fps)
                _sub(item, "start", fs)
                _sub(item, "end", fs + src_len)
                _sub(item, "in", src_in)
                _sub(item, "out", src_in + src_len)
                self.file_el(item, clip, False)
                st = _sub(item, "sourcetrack")
                _sub(st, "mediatype", "audio")
                _sub(st, "trackindex", ch + 1)
                if chans > 1:
                    for other in range(chans):
                        link = _sub(item, "link")
                        _sub(link, "linkclipref", ids[other])
                        _sub(link, "mediatype", "audio")
                        _sub(link, "trackindex", first_index + other)
                        _sub(link, "clipindex", ci + 1)
                        _sub(link, "groupindex", 1)
                self.add_levels(item, clip, src_in, src_len / self.fps)
            self.counts["clips"] += 1
        for i, el in enumerate(els):
            _sub(el, "enabled", "TRUE")
            _sub(el, "locked", "FALSE")
            _sub(el, "outputchannelindex", i + 1)
            self.counts["tracks"] += 1
        return len(els)

    def build(self, transitions: bool = True):
        tl = self.tl
        root = ET.Element("xmeml")
        root.set("version", "5")
        seq = _sub(root, "sequence")
        seq.set("id", "sequence-1")
        _sub(seq, "uuid", str(uuid.uuid4()))
        _sub(seq, "name", tl.get("name") or "promptcut")
        _sub(seq, "duration", self.f(tl["duration"]))
        _rate(seq, self.fps)
        _sub(seq, "in", -1)
        _sub(seq, "out", -1)
        _timecode(seq, self.fps)
        media = _sub(seq, "media")
        video = _sub(media, "video")
        fmt = _sub(video, "format")
        _video_chars(fmt, self.fps, self.w, self.h, depth=True)
        for track in tl["tracks"]:
            if track.get("type") == "video":
                self.video_track(video, track, transitions)
        audio = _sub(media, "audio")
        _sub(audio, "numOutputChannels", 2)
        afmt = _sub(audio, "format")
        _audio_chars(afmt, 48000)
        outs = _sub(audio, "outputs")
        for ch in (1, 2):
            g = _sub(outs, "group")
            _sub(g, "index", ch)
            _sub(g, "numchannels", 1)
            _sub(g, "downmix", 0)
            _sub(_sub(g, "channel"), "index", ch)
        index = 1
        for track in tl["tracks"]:
            if track.get("type") == "audio" and track.get("clips"):
                index += self.audio_tracks(audio, track, index)
        for mk in tl.get("markers") or []:
            m = _sub(seq, "marker")
            _sub(m, "comment", mk.get("note") or "")
            _sub(m, "name", mk.get("name") or "")
            _sub(m, "in", self.f(mk.get("at") or 0.0))
            _sub(m, "out", -1)
        return root


def write(tl: dict, path, profile: str = "premiere", *, transitions: bool = True) -> dict:
    if profile not in PROFILES:
        raise ValueError(f"unknown xmeml profile '{profile}'")
    writer = _Writer(tl, PROFILES[profile])
    root = writer.build(transitions)
    ET.indent(root, space="\t")
    body = ET.tostring(root, encoding="unicode")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body + "\n",
                   encoding="utf-8")
    return {"file": str(out), "profile": profile, **writer.counts}
