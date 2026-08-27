import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "promptcut" / "scripts"))

import pc_plan  # noqa: E402
from pc_common import ffmpeg_bin, load_config  # noqa: E402

CFG = load_config()


def _ff(*args):
    subprocess.run([ffmpeg_bin(CFG), "-y", "-v", "error", *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_media(d: Path) -> dict:
    d.mkdir(parents=True, exist_ok=True)
    m = {"wide": d / "wide.png", "tall": d / "tall.jpg", "clip": d / "clip.mp4",
         "vo": d / "vo.wav", "music": d / "music.wav", "sfx": d / "sfx.wav"}
    _ff("-f", "lavfi", "-i", "color=c=gray:s=1600x900", "-frames:v", "1", str(m["wide"]))
    _ff("-f", "lavfi", "-i", "color=c=gray:s=900x1600", "-frames:v", "1", str(m["tall"]))
    _ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=30", "-t", "2", "-pix_fmt", "yuv420p",
        str(m["clip"]))
    _ff("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "1.5", str(m["vo"]))
    _ff("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "3", str(m["music"]))
    _ff("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "0.5", str(m["sfx"]))
    return {k: str(v) for k, v in m.items()}


def sample_plan(m: dict) -> dict:
    raw = {"project": "test", "aspect": "16:9", "fps": 30,
           "music": {"file": m["music"], "gain_db": -20, "duck": True, "fade": 1.0},
           "timing": {"transition": "dissolve", "transition_duration": 0.4},
           "shots": [
               {"id": "s1", "vo": "первый кадр", "image": m["wide"], "motion": "zoom_in",
                "focus": [0.8, 0.5], "ease": True, "overlay": "TITLE"},
               {"id": "s2", "vo": "второй", "image": m["tall"], "motion": "pan_right", "sentence": "g1"},
               {"id": "s3", "vo": "кадр", "image": m["tall"], "motion": "still", "sentence": "g1"},
               {"id": "s4", "vo": "", "video": m["clip"], "video_in": 0.5, "min_duration": 3.0,
                "sfx": m["sfx"], "transition": "cut"},
           ]}
    plan = pc_plan.normalize(raw)
    for s in plan["shots"]:
        s["image_file"] = s["image"]
        s["video_file"] = s["video"]
    plan["shots"][0].update(vo_file=m["vo"], vo_duration=1.5)
    plan["shots"][1].update(vo_file=m["vo"], vo_duration=1.0, _g_first=True, _g_last=False)
    plan["shots"][2].update(vo_file=None, vo_duration=0.5, _g_first=False, _g_last=True)
    plan["shots"][3].update(vo_file=None, vo_duration=0.0)
    pc_plan.compute_timeline(plan)
    return plan
