# -*- coding: utf-8 -*-
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
from pathlib import Path

import pc_vegas
import pc_xmeml
from pc_common import die, info, load_config

TARGETS = ("premiere", "resolve", "vegas")

STEPS = {
    "premiere": [
        "Premiere Pro: File > Import, pick the .premiere.xml - a sequence with all tracks appears",
        "Subtitles: File > Import the subs.srt, drag it onto the sequence above the video to get a caption track",
        "If media shows offline, right-click > Link Media and point at the plan_build folder",
    ],
    "resolve": [
        "DaVinci Resolve: File > Import > Timeline > Import AAF, EDL, XML..., pick the .resolve.xml",
        "In the import dialog keep 'Use sizing information' and 'Automatically import source clips' checked",
        "Subtitles: File > Import > Subtitle, pick subs.srt, then drag it onto the subtitle track",
    ],
    "vegas": [
        "VEGAS Pro: start with an empty project, Tools > Scripting > Run Script..., pick the .vegas.cs "
        "(or rerun with --run); it builds the timeline and saves the .veg next to it",
        "Subtitles: Insert > Subtitles From File..., pick subs.srt",
        "Fallback without scripting: File > Import > Final Cut Pro 7/DaVinci Resolve, pick the .vegas.xml",
    ],
}

NLE_GLOBS = {
    "premiere": ["C:/Program Files/Adobe/Adobe Premiere Pro */Adobe Premiere Pro.exe",
                 "/Applications/Adobe Premiere Pro */Adobe Premiere Pro *.app"],
    "resolve": ["C:/Program Files/Blackmagic Design/DaVinci Resolve/Resolve.exe",
                "/Applications/DaVinci Resolve/DaVinci Resolve.app", "/opt/resolve/bin/resolve"],
}
VEGAS_GLOBS = ["C:/Program Files/VEGAS/VEGAS Pro */vegas*.exe",
               "C:/Program Files/MAGIX/VEGAS Pro */vegas*.exe",
               "C:/Program Files/Sony/Vegas Pro */vegas*.exe",
               "C:/Program Files (x86)/Sony/Vegas Pro */vegas*.exe"]


def _newest(paths: list) -> str | None:
    return sorted(paths, key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", p)])[-1] \
        if paths else None


def find_vegas(cfg: dict | None = None) -> str | None:
    cfg = cfg or load_config()
    for cand in (os.environ.get("PROMPTCUT_VEGAS"), cfg.get("vegas_exe")):
        if cand and Path(str(cand)).expanduser().exists():
            return str(Path(str(cand)).expanduser())
    hits = [p for pat in VEGAS_GLOBS for p in glob.glob(pat)]
    main = [p for p in hits if re.fullmatch(r"vegas\d*\.exe", Path(p).name, re.I)]
    return _newest(main or hits)


def installed(cfg: dict | None = None) -> dict:
    found = {}
    for name, pats in NLE_GLOBS.items():
        found[name] = _newest([p for pat in pats for p in glob.glob(pat)])
    found["vegas"] = find_vegas(cfg)
    return found


def run_vegas(script, cfg: dict | None = None) -> str:
    exe = find_vegas(cfg)
    if not exe:
        die("VEGAS Pro not found. Set it: promptcut config --set vegas_exe=\"C:\\Program Files\\VEGAS\\VEGAS Pro 22.0\\vegas220.exe\"")
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([exe, "/SCRIPT", str(script)], creationflags=flags, close_fds=True)
    info(f"VEGAS started with {Path(script).name}")
    return exe


def export(tl: dict, target: str, out_dir, *, run: bool = False, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    if target != "all" and target not in TARGETS:
        die(f"unknown target '{target}'. Use one of: {', '.join(TARGETS)}, all")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"name": tl.get("name"), "out_dir": str(out_dir), "duration": tl.get("duration"),
              "subtitles": (tl.get("subtitles") or {}).get("srt"), "targets": {}}
    for t in (TARGETS if target == "all" else (target,)):
        r = pc_xmeml.write(tl, out_dir / f"{tl['name']}.{t}.xml", t)
        r = {"xml": r.pop("file"), **r}
        if t == "vegas":
            r.update(pc_vegas.write(tl, out_dir))
            if run:
                r["launched"] = run_vegas(r["script"], cfg)
        r["next_steps"] = STEPS[t]
        result["targets"][t] = r
    result["hint"] = ("stills carry editable motion keyframes; if a picture lands off-centre after "
                      "import, re-export with --use-clips to place the rendered clips instead")
    return result
