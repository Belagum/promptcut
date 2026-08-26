# -*- coding: utf-8 -*-
"""Media generation for a storyboard: speech and images, cached, with a stub mode."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pc_openrouter as orr
from pc_common import (cache_dir, die, ffmpeg_bin, ffprobe_duration, info, run, sha, warn)
from pc_plan import VIDEO_EXT

CHARS_PER_SEC = 14.5  # rough ru/en speaking rate, only used to fake stub durations


def font_file() -> str | None:
    env = os.environ.get("PROMPTCUT_FONT")
    if env and Path(env).exists():
        return env
    cands = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    for c in cands:
        if Path(c).exists():
            return c
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", "sans"], stdout=subprocess.PIPE,
                             timeout=10).stdout.decode().strip()
        if out and Path(out).exists():
            return out
    except Exception:
        pass
    return None


def _wrap(text: str, width: int = 34, max_lines: int = 6) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines[:max_lines])


def placeholder_image(text: str, out: Path, w: int, h: int, cfg: dict, label: str = "") -> Path:
    seed = int(sha(text or label)[:6], 16)
    c1 = f"0x{(seed & 0x3F3F3F) | 0x101820:06x}"
    c2 = f"0x{((seed >> 6) & 0x7F7F7F) | 0x203040:06x}"
    out = out.with_suffix(".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    body = _wrap(text or label or "shot", max(20, int(w / 42)))
    tmp = Path(tempfile.mkdtemp()) / "t.txt"
    tmp.write_text(body, encoding="utf-8")
    ff = font_file()
    draw = (f"drawtext=textfile='{tmp.as_posix()}':fontcolor=white@0.92:"
            f"fontsize={max(20, int(h / 18))}:x=(w-text_w)/2:y=(h-text_h)/2:"
            f"line_spacing={int(h/60)}:box=0")
    draw += f":fontfile='{Path(ff).as_posix()}'" if ff else ":font=Arial"
    tag = (f"drawtext=text='{label}':fontcolor=white@0.55:fontsize={max(16,int(h/28))}"
           f":x={int(w*0.03)}:y={int(h*0.03)}")
    tag += f":fontfile='{Path(ff).as_posix()}'" if ff else ":font=Arial"
    vf = (f"gradients=s={w}x{h}:c0={c1}:c1={c2}:type=radial:n=1,"
          f"format=rgb24,{draw},{tag}")
    run([ffmpeg_bin(cfg), "-y", "-v", "error", "-f", "lavfi", "-i",
         f"gradients=s={w}x{h}:c0={c1}:c1={c2}:type=radial", "-frames:v", "1",
         "-vf", f"format=rgb24,{draw},{tag}", str(out)],
        desc="stub image")
    shutil.rmtree(tmp.parent, ignore_errors=True)
    return out


def placeholder_voice(text: str, out: Path, cfg: dict, speed: float = 1.0) -> Path:
    dur = max(1.0, min(40.0, len(text) / (CHARS_PER_SEC * max(0.5, speed)) + 0.35))
    out = out.with_suffix(".mp3")
    out.parent.mkdir(parents=True, exist_ok=True)
    run([ffmpeg_bin(cfg), "-y", "-v", "error", "-f", "lavfi",
         "-i", f"sine=frequency=210:duration={dur:.3f}:sample_rate=44100",
         "-af", "volume=0.06,tremolo=f=5.5:d=0.7", "-ac", "2", "-b:a", "128k", str(out)],
        desc="stub voice")
    return out


def _norm_words(text: str) -> list:
    """Tokens for transcript comparison: lowercase, no yo/stress; digit tokens
    (transcripts write «129» for spoken numbers) worded via num2words."""
    import re
    text = (text or "").lower().replace("ё", "е").replace("́", "")
    out = []
    for tok in re.findall(r"[a-zа-яіїєґ]+|[0-9]+", text):
        if tok.isdigit() and len(tok) <= 6:
            try:
                from num2words import num2words
                out.extend(re.findall(r"[а-я]+", num2words(int(tok), lang="ru")
                                      .replace("ё", "е")))
            except ImportError:
                out.append(tok)
        else:
            out.append(tok)
    return out


def edge_tts_marks(text: str, out: Path, cfg: dict, voice: str | None = None,
                   speed: float = 1.0) -> tuple:
    """In-process edge synthesis that also captures per-word time boundaries."""
    import asyncio
    voice = voice or cfg.get("edge_voice") or "ru-RU-DmitryNeural"
    out = out.with_suffix(".mp3")
    out.parent.mkdir(parents=True, exist_ok=True)
    rate = int(round((speed - 1.0) * 100))
    kw = {"rate": f"{rate:+d}%"} if rate else {}

    async def go():
        import edge_tts
        comm = edge_tts.Communicate(text, voice, **kw)
        marks, buf = [], bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                t0 = chunk["offset"] / 1e7
                marks.append({"w": chunk["text"], "t0": round(t0, 3),
                              "t1": round(t0 + chunk["duration"] / 1e7, 3)})
        return bytes(buf), marks

    last = ""
    for pause in (0, 2, 5, 12):
        if pause:
            time.sleep(pause)
        try:
            data, marks = asyncio.run(go())
            if len(data) >= 512:
                out.write_bytes(data)
                return out, marks
            last = f"empty audio ({len(data)} bytes)"
        except ModuleNotFoundError:
            die("edge-tts is not installed: pip install edge-tts")
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        warn(f"edge-tts retry: {last[:200]}")
    die(f"edge-tts failed: {last[:400]}")


def openrouter_tts_marks(text: str, out: Path, cfg: dict, *, voice: str | None,
                         model: str | None, speed: float = 1.0,
                         instructions: str | None = None) -> tuple:
    """Chat-audio voices can drift from the script, so transcribe the result,
    demand a verbatim match, and keep word timestamps for sentence cutting."""
    import difflib
    want = _norm_words(text)
    best = None
    tries = []
    for attempt in range(3):
        tmp = out.with_name(f"{out.stem}.try{attempt}.mp3")
        tries.append(tmp)
        orr.synth_speech(text, tmp, cfg=cfg, model=model, voice=voice,
                         speed=speed, instructions=instructions)
        tr = orr.transcribe(tmp, cfg=cfg, language="ru", granularity="word")
        words = [{"w": str(w.get("word", "")).strip(),
                  "t0": round(float(w.get("start", 0.0)), 3),
                  "t1": round(float(w.get("end", 0.0)), 3)}
                 for w in (tr.get("words") or [])]
        got = _norm_words(" ".join(w["w"] for w in words))
        ratio = difflib.SequenceMatcher(None, want, got).ratio()
        if best is None or ratio > best[0]:
            best = (ratio, tmp, words)
        if ratio >= 0.9:
            break
        warn(f"tts verbatim match {ratio:.2f} on attempt {attempt + 1}, retrying")
    ratio, path, words = best
    if ratio < 0.7:
        # whisper garbles spelled-out letters and rare glyphs, so as a second
        # opinion check that the take's length is speech-plausible for the text
        # (the failure mode we guard against is the model narrating extra text)
        from pc_common import ffprobe_duration, load_config
        dur = ffprobe_duration(path, load_config())
        expected = max(1.0, len(text) / CHARS_PER_SEC)
        if ratio >= 0.45 and 0.55 * expected <= dur <= 1.8 * expected:
            warn(f"voice accepted by duration sanity (match {ratio:.2f}, "
                 f"{dur:.1f}s vs ~{expected:.1f}s): {text[:60]}")
        else:
            die(f"voice model keeps drifting from the script (match {ratio:.2f}): {text[:90]}")
    elif ratio < 0.9:
        warn(f"voice accepted with verbatim match {ratio:.2f}: {text[:60]}")
    if path != out:
        shutil.copyfile(path, out)
    for t in tries:
        if t != out:
            t.unlink(missing_ok=True)
    return out, words


def edge_tts(text: str, out: Path, cfg: dict, voice: str | None = None,
             speed: float = 1.0) -> Path:
    voice = voice or cfg.get("edge_voice") or "ru-RU-DmitryNeural"
    out = out.with_suffix(".mp3")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp()) / "in.txt"
    tmp.write_text(text, encoding="utf-8")
    rate = int(round((speed - 1.0) * 100))
    cmd = [sys.executable, "-m", "edge_tts", "--voice", voice, "--file", str(tmp),
           "--write-media", str(out)]
    if rate:
        cmd += [f"--rate={rate:+d}%"]
    msg = ""
    # the endpoint throttles concurrent requests (NoAudioReceived), retry with backoff
    for attempt, pause in enumerate((0, 2, 5, 12)):
        if pause:
            time.sleep(pause)
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if proc.returncode == 0 and out.exists() and out.stat().st_size >= 512:
            shutil.rmtree(tmp.parent, ignore_errors=True)
            return out
        msg = (proc.stdout or b"").decode("utf-8", "replace")[-400:]
        if "No module named" in msg:
            break
        warn(f"edge-tts attempt {attempt + 1} failed, retrying")
    shutil.rmtree(tmp.parent, ignore_errors=True)
    if "No module named" in msg:
        die("edge-tts is not installed: pip install edge-tts")
    die(f"edge-tts failed:\n{msg}")


def _member_spans(members: list, marks: list, total: float) -> list:
    """Split [0, total] into per-member spans using word marks; each member's
    span starts where its first word is spoken. Falls back to proportional."""
    import difflib
    counts = [len(_norm_words(m.get("vo") or "")) for m in members]
    firsts = []
    acc = 0
    for c in counts:
        firsts.append(acc)
        acc += c

    bounds = None
    if marks and acc:
        plan_tokens = []
        for m in members:
            plan_tokens.extend(_norm_words(m.get("vo") or ""))
        mark_tokens, mark_idx = [], []
        for i, mk in enumerate(marks):
            for tok in _norm_words(mk.get("w") or ""):
                mark_tokens.append(tok)
                mark_idx.append(i)
        p2m = {}
        sm = difflib.SequenceMatcher(None, plan_tokens, mark_tokens)
        for op, a0, a1, b0, b1 in sm.get_opcodes():
            if op == "equal":
                for k in range(a1 - a0):
                    p2m[a0 + k] = mark_idx[b0 + k]
        if len(p2m) >= max(2, acc // 2):
            bounds = [0.0]
            for f in firsts[1:]:
                j = next((p2m[i] for i in range(f, acc) if i in p2m), None)
                # cut slightly BEFORE the word lands: transcript timestamps run
                # late and a picture arriving with the word reads as lag
                t = float(marks[j]["t0"]) - 0.15 if j is not None else None
                prev = bounds[-1]
                bounds.append(min(total, max(prev, t)) if t is not None else prev)
            # unresolved bounds collapsed onto prev; spread them evenly forward
            for i in range(1, len(bounds)):
                if bounds[i] <= bounds[i - 1]:
                    nxt = next((bounds[j] for j in range(i + 1, len(bounds))
                                if bounds[j] > bounds[i - 1]), total)
                    bounds[i] = bounds[i - 1] + (nxt - bounds[i - 1]) * 0.5

    if bounds is None:
        chars = [max(1, len((m.get("vo") or "").strip())) for m in members]
        csum = sum(chars)
        bounds, run = [0.0], 0.0
        for c in chars[:-1]:
            run += total * c / csum
            bounds.append(round(run, 3))

    spans = []
    for i in range(len(members)):
        t0 = bounds[i]
        t1 = bounds[i + 1] if i + 1 < len(members) else total
        spans.append((round(t0, 3), round(max(t1, t0 + 0.2), 3)))
    return spans


def _voice_conf(plan: dict, cfg: dict) -> dict:
    v = dict(plan.get("voice") or {})
    v["provider"] = (v.get("provider") or cfg.get("tts_provider") or "openrouter").lower()
    v["model"] = v.get("model") or cfg.get("tts_model")
    v["voice"] = v.get("voice") or (cfg.get("edge_voice") if v["provider"] == "edge"
                                    else cfg.get("tts_voice"))
    v["speed"] = float(v.get("speed") or 1.0)
    return v


def _image_prompt(plan: dict, shot: dict) -> str:
    style = (plan.get("image") or {}).get("style") or ""
    prompt = shot["image_prompt"]
    return f"{prompt}. {style}".strip().strip(".") if style else prompt


def ensure_media(plan: dict, wd: Path, *, fake: bool = False, workers: int = 4,
                 cfg: dict | None = None, force: bool = False) -> dict:
    from pc_common import load_config
    cfg = cfg or load_config()
    voice = _voice_conf(plan, cfg)
    img_conf = plan.get("image") or {}
    img_model = img_conf.get("model") or cfg.get("image_model")
    img_res = img_conf.get("resolution") or cfg.get("image_resolution") or "2K"
    aspect = plan["aspect"]
    tts_cache = cache_dir() / "tts"
    img_cache = cache_dir() / "img"
    (wd / "audio").mkdir(parents=True, exist_ok=True)
    (wd / "img").mkdir(parents=True, exist_ok=True)
    jobs = []

    # consecutive shots sharing a "sentence" id speak as ONE tts call; each
    # member's vo is its word slice, video cuts land on word boundaries
    groups: dict = {}
    for shot in plan["shots"]:
        gid = shot.get("sentence")
        if gid:
            groups.setdefault(gid, []).append(shot)

    seen = set()
    for shot in plan["shots"]:
        gid = shot.get("sentence")
        if gid:
            if gid not in seen:
                seen.add(gid)
                jobs.append(("vo_group", groups[gid]))
        else:
            jobs.append(("vo", shot))
        jobs.append(("img", shot))

    def do(job):
        kind, shot = job
        try:
            if kind == "vo_group":
                members = shot
                gid = members[0]["sentence"]
                full = " ".join((m.get("vo") or "").strip() for m in members).strip()
                if not full:
                    for m in members:
                        m["vo_file"], m["vo_duration"] = None, 0.0
                    return
                key = sha("tts3", full, voice["provider"], voice["model"],
                          voice["voice"], voice["speed"], "fake" if fake else "real")
                cached = tts_cache / f"{key}.mp3"
                marks_file = tts_cache / f"{key}.marks.json"

                def synth_group():
                    marks_file.unlink(missing_ok=True)
                    if fake or voice["provider"] == "none":
                        placeholder_voice(full, cached, cfg, voice["speed"])
                        marks = []
                    elif voice["provider"] == "edge":
                        _, marks = edge_tts_marks(full, cached, cfg,
                                                  voice["voice"], voice["speed"])
                    else:
                        _, marks = openrouter_tts_marks(
                            full, cached, cfg, voice=voice["voice"], model=voice["model"],
                            speed=voice["speed"], instructions=voice.get("instructions"))
                    marks_file.write_text(json.dumps(marks, ensure_ascii=False),
                                          encoding="utf-8")
                    info(f"voice [{gid}] done ({len(members)} shots)")

                if force or not cached.exists() or not marks_file.exists():
                    synth_group()
                else:
                    info(f"voice [{gid}] cached")
                dst = wd / "audio" / f"g_{gid}.mp3"
                shutil.copyfile(cached, dst)
                try:
                    total = ffprobe_duration(dst, cfg)
                except SystemExit:
                    warn(f"voice [{gid}]: cached file is corrupt, regenerating")
                    cached.unlink(missing_ok=True)
                    synth_group()
                    shutil.copyfile(cached, dst)
                    total = ffprobe_duration(dst, cfg)
                marks = json.loads(marks_file.read_text(encoding="utf-8"))
                spans = _member_spans(members, marks, round(total, 3))
                for m, (t0, t1) in zip(members, spans):
                    m["vo_duration"] = round(t1 - t0, 3)
                    m["vo_file"] = None
                    m["_g_first"] = m is members[0]
                    m["_g_last"] = m is members[-1]
                members[0]["vo_file"] = str(dst)
                return
            if kind == "vo":
                if not shot["vo"]:
                    shot["vo_file"] = None
                    shot["vo_duration"] = 0.0
                    return
                key = sha("tts", shot["vo"], voice["provider"], voice["model"],
                          voice["voice"], voice["speed"], "fake" if fake else "real")
                cached = tts_cache / f"{key}.mp3"
                ok_tag = tts_cache / f"{key}.ok.json"

                def synth():
                    # the ok-sidecar is written only after a take passes checks,
                    # so an interrupted or drifted take can never be reused
                    ok_tag.unlink(missing_ok=True)
                    if fake or voice["provider"] == "none":
                        placeholder_voice(shot["vo"], cached, cfg, voice["speed"])
                    elif voice["provider"] == "edge":
                        edge_tts(shot["vo"], cached, cfg, voice["voice"], voice["speed"])
                    else:
                        # chat-audio drifts on bare text: always verify verbatim
                        openrouter_tts_marks(shot["vo"], cached, cfg,
                                             voice=voice["voice"], model=voice["model"],
                                             speed=voice["speed"],
                                             instructions=voice.get("instructions"))
                    ok_tag.write_text(json.dumps({"v": 1, "chars": len(shot["vo"])}),
                                      encoding="utf-8")
                    info(f"voice {shot['id']} done")

                if force or not cached.exists() or not ok_tag.exists():
                    synth()
                else:
                    info(f"voice {shot['id']} cached")
                dst = wd / "audio" / f"{shot['id']}.mp3"
                shutil.copyfile(cached, dst)
                try:
                    dur = ffprobe_duration(dst, cfg)
                except SystemExit:
                    # a partial file from an interrupted run poisoned the cache
                    warn(f"voice {shot['id']}: cached file is corrupt, regenerating")
                    cached.unlink(missing_ok=True)
                    synth()
                    shutil.copyfile(cached, dst)
                    dur = ffprobe_duration(dst, cfg)
                shot["vo_file"] = str(dst)
                shot["vo_duration"] = round(dur, 3)
            else:
                source = shot.get("video") or (
                    shot.get("image")
                    if Path(str(shot.get("image") or "")).suffix.lower() in VIDEO_EXT else None)
                if source:
                    src = Path(str(source)).expanduser()
                    dst = wd / "img" / f"{shot['id']}{src.suffix.lower()}"
                    shutil.copy2(src, dst)
                    shot["video_file"] = str(dst)
                    shot["image_file"] = None
                    return
                if shot.get("image"):
                    src = Path(str(shot["image"])).expanduser()
                    dst = wd / "img" / f"{shot['id']}{src.suffix.lower() or '.png'}"
                    shutil.copy2(src, dst)
                    shot["image_file"] = str(dst)
                    return
                if not shot["image_prompt"]:
                    shot["image_file"] = None
                    return
                prompt = _image_prompt(plan, shot)
                key = sha("img2", prompt, img_model, img_res, aspect, shot.get("seed"),
                          "fake" if fake else "real")
                hit = next(iter(sorted(img_cache.glob(f"{key}.*"))), None)
                if force or not hit:
                    if fake:
                        hit = placeholder_image(prompt, img_cache / key, plan["width"],
                                                plan["height"], cfg, label=shot["id"])
                    else:
                        hit = orr.generate_image(prompt, img_cache / key, cfg=cfg,
                                                 model=img_model, aspect_ratio=aspect,
                                                 resolution=img_res, seed=shot.get("seed"))
                    info(f"image {shot['id']} done")
                else:
                    info(f"image {shot['id']} cached")
                dst = wd / "img" / f"{shot['id']}{hit.suffix}"
                shutil.copy2(hit, dst)
                shot["image_file"] = str(dst)
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            die(f"shot {shot['id']} ({kind}): {exc}")

    if workers > 1 and not fake:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(do, jobs))
    else:
        for job in jobs:
            do(job)

    for shot in plan["shots"]:
        if not (shot.get("image_file") or shot.get("video_file")):
            warn(f"shot {shot['id']} has no image, falling back to black")
    return plan
