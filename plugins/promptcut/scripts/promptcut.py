#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PromptCut CLI. Every subcommand prints a JSON result on stdout and
human-readable progress on stderr."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pc_capcut  # noqa: E402
import pc_dl  # noqa: E402
import pc_draw  # noqa: E402
import pc_edit  # noqa: E402
import pc_media  # noqa: E402
import pc_openrouter as orr  # noqa: E402
import pc_plan  # noqa: E402
import pc_render  # noqa: E402
import pc_stock  # noqa: E402
import pc_subs  # noqa: E402
from pc_common import (CONFIG_PATH, DEFAULT_CONFIG, api_key, die, have, info, load_config,
                       save_config, spend_total)  # noqa: E402

TEMPLATE = {
    "project": "demo",
    "aspect": "9:16",
    "voice": {"provider": "openrouter", "voice": "alloy", "speed": 1.0},
    "image": {"style": "cinematic photo, soft light, shallow depth of field"},
    "music": {"file": None, "gain_db": -21, "duck": True},
    "subtitles": {"enabled": True, "max_chars": 30, "uppercase": False},
    "shots": [
        {"vo": "First line: it gets voiced and subtitled.",
         "image_prompt": "wide shot of a foggy morning city", "motion": "zoom_in"},
        {"vo": "Second line: new picture, new transition.",
         "image_prompt": "close up of hands holding a paper map", "motion": "pan_right"},
    ],
}


def out_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _plan_pipeline(args, cfg):
    plan = pc_plan.load_plan(args.plan)
    wd = pc_plan.workdir(plan)
    if args.stage in ("media", "all"):
        pc_media.ensure_media(plan, wd, fake=args.fake, workers=args.workers, cfg=cfg,
                              force=args.force)
    else:
        built = wd / "plan.built.json"
        if built.exists():
            cached = json.loads(built.read_text(encoding="utf-8"))
            by_id = {s["id"]: s for s in cached.get("shots", [])}
            for shot in plan["shots"]:
                shot.update({k: v for k, v in by_id.get(shot["id"], {}).items()
                             if k in ("vo_file", "vo_duration", "image_file", "clip_file")})
    for shot in plan["shots"]:
        shot.setdefault("vo_duration", 0.0)
    pc_plan.compute_timeline(plan)
    pc_plan.save_built(plan, wd)
    return plan, wd


def cmd_doctor(args):
    cfg = load_config()
    checks = {
        "python": sys.version.split()[0],
        "ffmpeg": have(cfg.get("ffmpeg", "ffmpeg")),
        "ffprobe": have(cfg.get("ffprobe", "ffprobe")),
        "openrouter_key": bool(api_key(cfg)),
        "config_file": str(CONFIG_PATH) if CONFIG_PATH.exists() else None,
        "font": pc_media.font_file(),
        "image_model": cfg.get("image_model"),
        "image_edit_model": cfg.get("image_edit_model"),
        "chat_model": cfg.get("chat_model"),
        "tts": f"{cfg.get('tts_provider')} / {cfg.get('tts_model')}",
        "stock_keys": sorted(k for k, v in (cfg.get("stock_keys") or {}).items() if v),
        "spend_usd": round(spend_total(), 4),
    }
    try:
        import PIL  # noqa: F401,PLC0415
        checks["pillow"] = True
    except ImportError:
        checks["pillow"] = False
    import shutil as _sh
    try:
        import yt_dlp  # noqa: F401,PLC0415
        checks["yt_dlp"] = True
    except ImportError:
        checks["yt_dlp"] = bool(_sh.which("yt-dlp"))
    try:
        import pycapcut  # noqa: F401,PLC0415
        checks["pycapcut"] = True
        found = [str(p) for p in pc_capcut.default_drafts_dirs()]
        checks["capcut_drafts"] = cfg.get("capcut_drafts_dir") or (found[0] if found else None)
    except ImportError:
        checks["pycapcut"] = False
        checks["capcut_drafts"] = None
    try:
        import edge_tts  # noqa: F401,PLC0415
        checks["edge_tts"] = True
    except ImportError:
        checks["edge_tts"] = False
    problems = []
    if not checks["ffmpeg"]:
        problems.append("ffmpeg missing: run 'promptcut setup', or winget install Gyan.FFmpeg")
    if not checks["openrouter_key"]:
        problems.append("no OpenRouter key: promptcut config --set openrouter_api_key=sk-or-... "
                        "(image and voice generation off; --fake and editing still work)")
    if not checks["pycapcut"]:
        problems.append("pycapcut missing, no CapCut export: run 'promptcut setup'")
    if not checks["pillow"]:
        problems.append("pillow missing, no annotate/card: run 'promptcut setup'")
    if not checks["yt_dlp"]:
        problems.append("yt-dlp missing, no media-dl: run 'promptcut setup'")
    checks["problems"] = problems
    out_json(checks)


PIP_DEPS = (("pillow", "PIL"), ("yt-dlp", "yt_dlp"), ("edge-tts", "edge_tts"),
            ("pycapcut", "pycapcut"))


def _pip_install(pkg: str, upgrade: bool = False) -> tuple:
    import subprocess
    cmd = [sys.executable, "-m", "pip", "install", "--quiet"]
    if upgrade:
        cmd.append("--upgrade")
    try:
        proc = subprocess.run(cmd + [pkg], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=600)
        err = (proc.stdout or b"").decode("utf-8", "replace")
        if proc.returncode != 0 and ("Permission" in err or "Access is denied" in err):
            proc = subprocess.run(cmd + ["--user", pkg], stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=600)
            err = (proc.stdout or b"").decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return False, "pip timed out"
    if proc.returncode == 0:
        return True, ""
    tail = err.strip().splitlines()[-1][:200] if err.strip() else "pip failed"
    return False, tail


def _install_ffmpeg() -> str:
    import shutil
    import subprocess
    if sys.platform == "win32" and shutil.which("winget"):
        info("installing ffmpeg via winget, this can take a few minutes...")
        try:
            proc = subprocess.run(["winget", "install", "-e", "--id", "Gyan.FFmpeg",
                                   "--silent", "--accept-source-agreements",
                                   "--accept-package-agreements"],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=1200)
        except subprocess.TimeoutExpired:
            return "winget timed out - install manually: winget install Gyan.FFmpeg"
        if proc.returncode == 0:
            return "installed" if have("ffmpeg") else \
                "installed - open a new terminal so PATH picks it up"
        return (f"winget failed (exit {proc.returncode}) - "
                "install manually: winget install Gyan.FFmpeg")
    if sys.platform == "darwin" and shutil.which("brew"):
        info("installing ffmpeg via brew, this can take a few minutes...")
        try:
            proc = subprocess.run(["brew", "install", "ffmpeg"], stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=1800)
        except subprocess.TimeoutExpired:
            return "brew timed out - install manually: brew install ffmpeg"
        return "installed" if proc.returncode == 0 else \
            "brew failed - install manually: brew install ffmpeg"
    return ("missing - install manually: winget install Gyan.FFmpeg (Windows), "
            "brew install ffmpeg (macOS), sudo apt install ffmpeg (Linux)")


def cmd_setup(args):
    import importlib
    import shutil
    cfg = load_config()
    result = {"installed": [], "already": [], "failed": {}}
    for pkg, mod in PIP_DEPS:
        present = bool(shutil.which(pkg)) if pkg == "yt-dlp" else False
        if not present:
            try:
                importlib.import_module(mod)
                present = True
            except ImportError:
                present = False
        if present and not args.upgrade:
            result["already"].append(pkg)
            continue
        info(f"pip install {pkg}...")
        ok, err = _pip_install(pkg, args.upgrade and present)
        if ok:
            result["installed"].append(pkg)
        else:
            result["failed"][pkg] = err
    result["ffmpeg"] = "present" if have(cfg.get("ffmpeg", "ffmpeg")) else _install_ffmpeg()
    result["openrouter_key"] = bool(api_key(cfg))
    if not result["openrouter_key"]:
        result["hint"] = ("no OpenRouter key: promptcut config --set openrouter_api_key=sk-or-... "
                          "(get one at openrouter.ai/settings/keys)")
    out_json(result)


def cmd_config(args):
    cfg = load_config()
    if args.set:
        for pair in args.set:
            key, _, value = pair.partition("=")
            key = key.strip()
            if key not in DEFAULT_CONFIG and key != "stock_keys":
                die(f"unknown config key '{key}'. Available: {', '.join(sorted(DEFAULT_CONFIG))}")
            cfg[key] = value.strip()
        save_config(cfg)
    safe = dict(cfg)
    if safe.get("openrouter_api_key"):
        safe["openrouter_api_key"] = safe["openrouter_api_key"][:8] + "..."
    safe["stock_keys"] = sorted((cfg.get("stock_keys") or {}).keys())
    out_json({"config_path": str(CONFIG_PATH), "config": safe})


def cmd_keys(args):
    cfg = load_config()
    keys = dict(cfg.get("stock_keys") or {})
    for pair in args.set or []:
        name, _, value = pair.partition("=")
        keys[name.strip().lower()] = value.strip()
    cfg["stock_keys"] = keys
    save_config(cfg)
    out_json({"stock_keys": sorted(keys), "config_path": str(CONFIG_PATH)})


def cmd_models(args):
    cfg = load_config()
    out_json(orr.list_models(cfg, args.kind)[:args.limit])


def cmd_tts(args):
    cfg = load_config()
    text = args.text or Path(args.file).read_text(encoding="utf-8")
    out = Path(args.out)
    provider = (args.provider or cfg.get("tts_provider") or "openrouter").lower()
    if provider == "edge":
        path = pc_media.edge_tts(text, out, cfg, args.voice, args.speed)
    elif provider == "fake":
        path = pc_media.placeholder_voice(text, out, cfg, args.speed)
    else:
        path = orr.synth_speech(text, out, cfg=cfg, model=args.model, voice=args.voice,
                                speed=args.speed, instructions=args.instructions)
    from pc_common import ffprobe_duration
    out_json({"file": str(path), "duration": round(ffprobe_duration(path, cfg), 3),
              "provider": provider, "chars": len(text)})


def cmd_image_gen(args):
    cfg = load_config()
    path = orr.generate_image(args.prompt, Path(args.out), cfg=cfg, model=args.model,
                              aspect_ratio=args.aspect, resolution=args.resolution,
                              seed=args.seed)
    out_json({"file": str(path), "prompt": args.prompt, "aspect": args.aspect})


def cmd_find(args, kind):
    cfg = load_config()
    if args.list or not args.out:
        out_json(pc_stock.search(args.query, kind=kind, n=args.n, provider=args.provider,
                                 cfg=cfg, orientation=args.orientation))
        return
    hit = pc_stock.fetch_best(args.query, Path(args.out), kind=kind, cfg=cfg,
                              provider=args.provider, orientation=args.orientation)
    out_json(hit)


def cmd_ask(args):
    cfg = load_config()
    files, tmp = [], None
    for f in args.file or []:
        p = Path(f)
        if not p.exists():
            die(f"attachment not found: {p}")
        suf = p.suffix.lower()
        if suf in pc_plan.VIDEO_EXT:
            die("video attachments are not supported; make a contact sheet first: "
                "promptcut frames -i video.mp4 --out sheet.jpg")
        if suf in (".m4a", ".ogg", ".opus", ".aac", ".flac", ".wma"):
            import tempfile
            from pc_common import ffmpeg_bin, run
            tmp = tmp or Path(tempfile.mkdtemp())
            conv = tmp / (p.stem + ".mp3")
            run([ffmpeg_bin(cfg), "-y", "-v", "error", "-i", str(p), "-vn",
                 "-c:a", "libmp3lame", "-q:a", "3", str(conv)], desc="convert to mp3")
            p = conv
        files.append(p)
    result = orr.chat(args.prompt, cfg=cfg, model=args.model, system=args.system,
                      files=files, json_mode=args.json, max_tokens=args.max_tokens)
    if tmp:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    out_json(result)


def cmd_image_edit(args):
    cfg = load_config()
    path = orr.edit_image(args.prompt, args.image, Path(args.out), cfg=cfg, model=args.model)
    out_json({"file": str(path), "prompt": args.prompt})


def _load_spec(spec: str):
    s = spec.strip()
    if s.startswith("[") or s.startswith("{"):
        try:
            return json.loads(s)
        except json.JSONDecodeError as exc:
            die(f"--spec is not valid JSON ({exc})")
    p = Path(spec)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    die(f"--spec must be inline JSON or a path to a JSON file, got: {spec[:80]}")


def cmd_annotate(args):
    out_json(pc_draw.annotate(args.i, args.out, _load_spec(args.spec)))


def cmd_card(args):
    out_json(pc_draw.card(args.text, args.out, size=args.size, title=args.title,
                          sub=args.sub, letters=args.letters, highlights=args.highlight,
                          bg=args.bg, fg=args.fg, accent=args.accent,
                          transparent=args.transparent, font_path=args.font))


def cmd_frames(args):
    out_json(pc_edit.frames(args.i, args.out, args.n, args.cols, args.width))


def cmd_waveform(args):
    out_json(pc_edit.waveform(args.i, args.out, args.width, args.height))


def cmd_media_dl(args):
    if args.search:
        out_json(pc_dl.search(args.search, args.n))
        return
    if not (args.url and args.out):
        die("need --url and --out to download, or --search to look around")
    path = pc_dl.fetch(args.url, args.out, audio=args.audio, start=args.start,
                       end=args.end, fmt=args.format)
    from pc_common import ffprobe_duration
    out_json({"file": str(path), "duration": round(ffprobe_duration(path, load_config()), 3)})


def cmd_transcribe(args):
    cfg = load_config()
    data = orr.transcribe(Path(args.file), cfg=cfg, model=args.model, language=args.language,
                          granularity=args.granularity)
    result = {"text": data.get("text", "")[:4000],
              "segments": len(data.get("segments") or []),
              "words": len(data.get("words") or [])}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        result["json"] = args.json_out
    if args.srt:
        rows, n = [], 0
        from pc_common import fmt_ts
        for seg in data.get("segments") or []:
            n += 1
            rows.append(f"{n}\n{fmt_ts(float(seg.get('start', 0)), True)} --> "
                        f"{fmt_ts(float(seg.get('end', 0)), True)}\n{seg.get('text', '').strip()}\n")
        Path(args.srt).write_text("\n".join(rows), encoding="utf-8")
        result["srt"] = args.srt
    out_json(result)


def cmd_probe(args):
    out_json(pc_edit.probe(args.file))


def cmd_cut(args):
    out_json({"file": str(pc_edit.cut(args.i, args.out, args.start, args.end, args.dur,
                                      args.copy))})


def cmd_concat(args):
    out_json({"file": str(pc_edit.concat(args.files, args.out, args.xfade, args.xfade_dur,
                                         args.width, args.height, args.fps))})


def cmd_overlay(args):
    out_json({"file": str(pc_edit.overlay(args.base, args.over, args.out, args.at, args.dur,
                                          args.x, args.y, args.scale, args.opacity, args.fade))})


def cmd_text(args):
    out_json({"file": str(pc_edit.drawtext(args.i, args.out, args.text, args.start, args.dur,
                                           args.size, args.color, args.position,
                                           not args.no_box))})


def cmd_subs_burn(args):
    out_json({"file": str(pc_edit.burn_subs(args.video, args.subs, args.out,
                                            force_style=args.force_style))})


def cmd_subs_make(args):
    cfg = load_config()
    plan, wd = _plan_pipeline(args, cfg)
    srt = pc_subs.build_srt(plan, Path(args.out) if args.out.endswith(".srt") else wd / "subs.srt")
    ass = pc_subs.build_ass(plan, wd / "subs.ass")
    out_json({"srt": str(srt), "ass": str(ass), "cues": len(pc_subs.cues(plan))})


def cmd_mix(args):
    sfx = json.loads(args.sfx) if args.sfx else None
    out_json({"file": str(pc_edit.mix_audio(args.video, args.out, args.music, args.music_db,
                                            not args.no_duck, not args.no_normalize,
                                            args.voice, args.voice_db, sfx))})


def cmd_speed(args):
    out_json({"file": str(pc_edit.speed(args.i, args.out, args.factor, not args.no_keep_pitch))})


def cmd_reframe(args):
    out_json({"file": str(pc_edit.reframe(args.i, args.out, args.aspect, args.mode))})


def cmd_silence_cut(args):
    out_json(pc_edit.silence_cut(args.i, args.out, args.noise_db, args.min_silence, args.pad))


def cmd_scenes(args):
    out_json({"cuts": pc_edit.scenes(args.i, args.threshold)})


def cmd_thumb(args):
    out_json({"file": str(pc_edit.thumb(args.i, args.out, args.at))})


def cmd_audio_extract(args):
    out_json({"file": str(pc_edit.extract_audio(args.i, args.out))})


def cmd_normalize(args):
    out_json({"file": str(pc_edit.normalize_audio(args.i, args.out, args.target))})


def cmd_kenburns(args):
    w, _, h = args.size.partition("x")
    focus = [float(v) for v in args.focus.split(",")] if args.focus else None
    out_json({"file": str(pc_edit.still_to_clip(args.image, args.out, args.dur, args.motion,
                                                int(w), int(h), args.fps, args.amp,
                                                focus=focus, ease=args.ease))})


def cmd_plan_new(args):
    data = dict(TEMPLATE)
    data["aspect"] = args.aspect
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    out_json({"file": args.out, "shots": len(data["shots"]),
              "hint": "edit shots: vo, image_prompt, motion, transition, min_duration"})


def cmd_plan_check(args):
    plan = pc_plan.load_plan(args.file)
    out_json({"ok": True, "shots": len(plan["shots"]), "aspect": plan["aspect"],
              "size": [plan["width"], plan["height"]], "fps": plan["fps"]})


def cmd_build(args):
    cfg = load_config()
    plan, wd = _plan_pipeline(args, cfg)
    result = {"plan": str(wd / "plan.built.json"), "duration": plan["total_duration"],
              "shots": len(plan["shots"])}
    if args.stage in ("render", "all"):
        out = Path(args.out or (Path(plan["_path"]).parent / f"{plan['project']}.mp4"))
        pc_render.render_all(plan, wd, out, cfg=cfg, burn_subs=not args.no_subs,
                             force=args.force, crf=args.crf, preset=args.preset)
        pc_plan.save_built(plan, wd)
        result.update({"video": str(out), "srt": str(out.with_suffix(".srt")),
                       "spend_usd": round(spend_total(), 4)})
    out_json(result)


def cmd_capcut_effects(args):
    out_json({"type": args.type, "query": args.search,
              "matches": pc_capcut.search_effects(args.type, args.search or "", args.limit)})


def cmd_capcut_build(args):
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    out_json(pc_capcut.build_spec(spec, drafts=args.drafts_dir, dump_to=args.dump))


def cmd_capcut_from_plan(args):
    cfg = load_config()
    plan, wd = _plan_pipeline(args, cfg)
    spec = pc_capcut.spec_from_plan(plan, wd, use_clips=args.use_clips, name=args.name,
                                    transitions=args.transitions)
    if args.spec_only:
        out_json({"spec": str(wd / "capcut.spec.json"), "tracks": len(spec["tracks"])})
        return
    out_json(pc_capcut.build_spec(spec, cfg=cfg, drafts=args.drafts_dir, dump_to=args.dump))


def cmd_capcut_drafts(args):
    cfg = load_config()
    d = pc_capcut.drafts_dir(cfg, args.drafts_dir)
    drafts = []
    try:
        import pycapcut  # noqa: PLC0415
        drafts = pycapcut.DraftFolder(str(d)).list_drafts()
    except ImportError:
        pass
    out_json({"drafts_dir": str(d), "drafts": drafts,
              "candidates": [str(p) for p in pc_capcut.default_drafts_dirs()]})


def cmd_spend(args):
    from pc_common import SPEND_LOG
    rows = []
    if SPEND_LOG.exists():
        for line in SPEND_LOG.read_text(encoding="utf-8").splitlines()[-args.tail:]:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    out_json({"total_usd": round(spend_total(), 4), "last": rows})


def build_parser():
    p = argparse.ArgumentParser(prog="promptcut", description="PromptCut video toolbox")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_text):
        sp = sub.add_parser(name, help=help_text)
        sp.set_defaults(func=fn)
        return sp

    add("doctor", cmd_doctor, "check environment, keys, CapCut folder")
    sp = add("setup", cmd_setup, "install missing optional deps: pip packages and ffmpeg")
    sp.add_argument("--upgrade", action="store_true",
                    help="also upgrade already-installed packages (yt-dlp ages fast)")
    sp = add("config", cmd_config, "show or change config")
    sp.add_argument("--set", nargs="*", metavar="KEY=VALUE")
    sp = add("keys", cmd_keys, "store stock provider keys")
    sp.add_argument("--set", nargs="*", metavar="PROVIDER=KEY")
    sp = add("models", cmd_models, "list OpenRouter models by output modality")
    sp.add_argument("--kind", default="image", choices=["image", "audio", "text"])
    sp.add_argument("--limit", type=int, default=40)

    sp = add("tts", cmd_tts, "text to speech")
    sp.add_argument("--text")
    sp.add_argument("--file")
    sp.add_argument("--out", required=True)
    sp.add_argument("--provider", choices=["openrouter", "edge", "fake"])
    sp.add_argument("--model")
    sp.add_argument("--voice")
    sp.add_argument("--speed", type=float, default=1.0)
    sp.add_argument("--instructions")

    sp = add("image-gen", cmd_image_gen, "generate an image")
    sp.add_argument("--prompt", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--aspect", default="16:9")
    sp.add_argument("--model")
    sp.add_argument("--resolution")
    sp.add_argument("--seed", type=int)

    for name, kind, help_text in (("image-find", "image", "search stock images"),
                                  ("video-find", "video", "search stock video"),
                                  ("audio-find", "audio", "search music and sfx")):
        sp = add(name, lambda a, k=kind: cmd_find(a, k), help_text)
        sp.add_argument("--query", required=True)
        sp.add_argument("--out")
        sp.add_argument("--provider")
        sp.add_argument("--orientation", choices=["landscape", "portrait", "square"])
        sp.add_argument("-n", type=int, default=6)
        sp.add_argument("--list", action="store_true", help="only print results")

    sp = add("ask", cmd_ask, "ask any OpenRouter model; attach images or audio (listen to files)")
    sp.add_argument("--prompt", required=True)
    sp.add_argument("--file", action="append",
                    help="attachment: png/jpg/webp/gif image or mp3/wav/m4a/ogg audio")
    sp.add_argument("--model")
    sp.add_argument("--system")
    sp.add_argument("--json", action="store_true", help="force a JSON object answer")
    sp.add_argument("--max-tokens", type=int)

    sp = add("image-edit", cmd_image_edit, "edit or combine images with a prompt")
    sp.add_argument("--prompt", required=True)
    sp.add_argument("--image", action="append", required=True, help="input image, repeatable")
    sp.add_argument("--out", required=True)
    sp.add_argument("--model")

    sp = add("annotate", cmd_annotate, "draw circles, arrows, boxes, labels on image or video")
    sp.add_argument("-i", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--spec", required=True, help="JSON list of shapes, or a path to it")

    sp = add("card", cmd_card, "typography card: exact text, letter numbers, highlights")
    sp.add_argument("--text", required=True, help="use | for group dividers: 'Ч|ИП|СЫ'")
    sp.add_argument("--out", required=True)
    sp.add_argument("--size", default="1920x1080")
    sp.add_argument("--title")
    sp.add_argument("--sub")
    sp.add_argument("--letters", action="store_true", help="number every letter")
    sp.add_argument("--highlight", action="append", help="substring to color, repeatable")
    sp.add_argument("--bg", default="#10141F")
    sp.add_argument("--fg", default="#FFFFFF")
    sp.add_argument("--accent", default="#FFD23F")
    sp.add_argument("--transparent", action="store_true", help="RGBA card for overlaying")
    sp.add_argument("--font")

    sp = add("frames", cmd_frames, "contact sheet of frames, to look at a video")
    sp.add_argument("-i", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("-n", type=int, default=12)
    sp.add_argument("--cols", type=int)
    sp.add_argument("--width", type=int, default=480)

    sp = add("waveform", cmd_waveform, "waveform + spectrogram image, to look at audio")
    sp.add_argument("-i", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--width", type=int, default=1200)
    sp.add_argument("--height", type=int, default=520)

    sp = add("media-dl", cmd_media_dl, "search or download web media via yt-dlp")
    sp.add_argument("--url")
    sp.add_argument("--out")
    sp.add_argument("--search", help="search instead of downloading")
    sp.add_argument("-n", type=int, default=5)
    sp.add_argument("--audio", action="store_true", help="audio only (or use .mp3 out)")
    sp.add_argument("--start", type=float)
    sp.add_argument("--end", type=float)
    sp.add_argument("--format", help="raw yt-dlp -f selector")

    sp = add("transcribe", cmd_transcribe, "speech to text with timings")
    sp.add_argument("--file", required=True)
    sp.add_argument("--srt")
    sp.add_argument("--json-out")
    sp.add_argument("--model")
    sp.add_argument("--language")
    sp.add_argument("--granularity", default="segment", choices=["segment", "word"])

    sp = add("probe", cmd_probe, "media info")
    sp.add_argument("--file", required=True)

    sp = add("cut", cmd_cut, "trim a fragment")
    sp.add_argument("-i", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--start", type=float, default=0.0)
    sp.add_argument("--end", type=float)
    sp.add_argument("--dur", type=float)
    sp.add_argument("--copy", action="store_true")

    sp = add("concat", cmd_concat, "join clips, optional crossfade")
    sp.add_argument("--files", nargs="+", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--xfade")
    sp.add_argument("--xfade-dur", type=float, default=0.5)
    sp.add_argument("--width", type=int)
    sp.add_argument("--height", type=int)
    sp.add_argument("--fps", type=int, default=30)

    sp = add("overlay", cmd_overlay, "put image or video on top")
    sp.add_argument("--base", required=True)
    sp.add_argument("--over", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--at", type=float, default=0.0)
    sp.add_argument("--dur", type=float)
    sp.add_argument("--x", default="(W-w)/2")
    sp.add_argument("--y", default="(H-h)/2")
    sp.add_argument("--scale", type=float)
    sp.add_argument("--opacity", type=float, default=1.0)
    sp.add_argument("--fade", type=float, default=0.0)

    sp = add("text", cmd_text, "burn a text label")
    sp.add_argument("-i", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--text", required=True)
    sp.add_argument("--start", type=float, default=0.0)
    sp.add_argument("--dur", type=float, default=3.0)
    sp.add_argument("--size", type=int)
    sp.add_argument("--color", default="white")
    sp.add_argument("--position", default="bottom", choices=["top", "center", "bottom"])
    sp.add_argument("--no-box", action="store_true")

    sp = add("subs-burn", cmd_subs_burn, "burn srt or ass into video")
    sp.add_argument("--video", required=True)
    sp.add_argument("--subs", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--force-style")

    sp = add("subs-make", cmd_subs_make, "build srt and ass from a plan")
    sp.add_argument("--plan", required=True)
    sp.add_argument("--out", default="subs.srt")
    sp.set_defaults(stage="none", fake=False, workers=1, force=False)

    sp = add("mix", cmd_mix, "music bed, ducking, sfx, loudness")
    sp.add_argument("--video", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--music")
    sp.add_argument("--music-db", type=float, default=-21.0)
    sp.add_argument("--voice")
    sp.add_argument("--voice-db", type=float, default=0.0)
    sp.add_argument("--sfx", help='JSON: [{"file":"x.mp3","at":2.5,"gain_db":-8}]')
    sp.add_argument("--no-duck", action="store_true")
    sp.add_argument("--no-normalize", action="store_true")

    sp = add("speed", cmd_speed, "change playback speed")
    sp.add_argument("-i", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--factor", type=float, required=True)
    sp.add_argument("--no-keep-pitch", action="store_true")

    sp = add("reframe", cmd_reframe, "change aspect: crop, blur bars, pad")
    sp.add_argument("-i", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--aspect", default="9:16")
    sp.add_argument("--mode", default="blur", choices=["blur", "crop", "pad"])

    sp = add("silence-cut", cmd_silence_cut, "remove pauses from talking head")
    sp.add_argument("-i", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--noise-db", type=float, default=-32.0)
    sp.add_argument("--min-silence", type=float, default=0.45)
    sp.add_argument("--pad", type=float, default=0.08)

    sp = add("scenes", cmd_scenes, "detect scene cuts")
    sp.add_argument("-i", required=True)
    sp.add_argument("--threshold", type=float, default=0.35)

    sp = add("thumb", cmd_thumb, "grab a frame")
    sp.add_argument("-i", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--at", type=float, default=1.0)

    sp = add("audio-extract", cmd_audio_extract, "rip audio to mp3")
    sp.add_argument("-i", required=True)
    sp.add_argument("--out", required=True)

    sp = add("normalize", cmd_normalize, "loudness normalize")
    sp.add_argument("-i", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--target", type=float, default=-16.0)

    sp = add("kenburns", cmd_kenburns, "still image to moving clip")
    sp.add_argument("--image", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--dur", type=float, default=4.0)
    sp.add_argument("--motion", default="zoom_in",
                    choices=["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up",
                             "pan_down", "still"])
    sp.add_argument("--size", default="1080x1920")
    sp.add_argument("--fps", type=int, default=30)
    sp.add_argument("--amp", type=float, default=0.12,
                    help="zoom depth: 0.12 subtle, 1.5 = push in to 2.5x")
    sp.add_argument("--focus", help="zoom target on the source image, e.g. 0.62,0.41")
    sp.add_argument("--ease", action="store_true", help="smooth in/out instead of linear")

    sp = add("plan-new", cmd_plan_new, "write a starter plan.json")
    sp.add_argument("--out", default="plan.json")
    sp.add_argument("--aspect", default="9:16", choices=list(pc_plan.ASPECTS))

    sp = add("plan-check", cmd_plan_check, "validate a plan")
    sp.add_argument("--file", required=True)

    sp = add("build", cmd_build, "full build: media, timeline, render")
    sp.add_argument("--plan", required=True)
    sp.add_argument("--out")
    sp.add_argument("--stage", default="all", choices=["media", "render", "all"])
    sp.add_argument("--fake", action="store_true", help="stub images and voice, no API spend")
    sp.add_argument("--no-subs", action="store_true")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--workers", type=int, default=4)
    sp.add_argument("--crf", type=int, default=20)
    sp.add_argument("--preset", default="medium")

    sp = add("capcut-effects", cmd_capcut_effects, "search CapCut effect names")
    sp.add_argument("--type", required=True, choices=list(pc_capcut.KINDS))
    sp.add_argument("--search")
    sp.add_argument("--limit", type=int, default=60)

    sp = add("capcut-build", cmd_capcut_build, "build a CapCut draft from a spec")
    sp.add_argument("--spec", required=True)
    sp.add_argument("--drafts-dir")
    sp.add_argument("--dump", help="write draft_content.json here instead of the drafts folder")

    sp = add("capcut-from-plan", cmd_capcut_from_plan, "CapCut draft from a video plan")
    sp.add_argument("--plan", required=True)
    sp.add_argument("--name")
    sp.add_argument("--use-clips", action="store_true", help="use rendered clips, not stills")
    sp.add_argument("--drafts-dir")
    sp.add_argument("--dump")
    sp.add_argument("--spec-only", action="store_true")
    sp.add_argument("--transitions", action="store_true",
                    help="add CapCut transitions (shifts video slightly against the vo track)")
    sp.set_defaults(stage="none", fake=False, workers=1, force=False)

    sp = add("capcut-drafts", cmd_capcut_drafts, "locate the CapCut drafts folder")
    sp.add_argument("--drafts-dir")

    sp = add("spend", cmd_spend, "how much was spent on APIs")
    sp.add_argument("--tail", type=int, default=20)
    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
