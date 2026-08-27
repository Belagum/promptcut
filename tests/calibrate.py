import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "promptcut" / "scripts"))

import pc_draw  # noqa: E402
import pc_nle  # noqa: E402
import pc_timeline  # noqa: E402
from pc_common import load_config  # noqa: E402

NOTES = """
Import the xml into the editor and compare with the labelled grid:
  A  0-3 s   1920 grid at native size: must fill the frame exactly, cells A1..D8 all visible
  B  3-6 s   3840 grid: must ALSO fill the frame exactly (cover scale). Zoomed 2x or letterboxed
             -> the profile's scale_basis is wrong for this editor
  C  6-10 s  zoom into the top-left quarter: the last frame shows exactly cells A1..B4.
             If the picture drifts elsewhere, read which cell sits at the frame centre and
             report it - that fixes center_unit
  D  10-14 s pan at 2x: starts on the left half (columns 1-4), ends on the right half (5-8)
"""


def grid(path: Path, w: int, h: int, cols: int = 8, rows: int = 4) -> Path:
    Image, _, ImageDraw, _ = pc_draw._pil()
    im = Image.new("RGB", (w, h), "#202020")
    d = ImageDraw.Draw(im)
    font = pc_draw._font(h / 14)
    cw, ch = w / cols, h / rows
    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * cw, r * ch
            fill = "#2a4d69" if (r + c) % 2 else "#4b3f72"
            d.rectangle([x0, y0, x0 + cw, y0 + ch], fill=fill, outline="#c0c0c0", width=max(2, w // 640))
            d.text((x0 + cw / 2, y0 + ch / 2), f"{chr(65 + r)}{c + 1}", font=font, fill="white", anchor="mm")
    d.ellipse([w / 2 - w / 60, h / 2 - w / 60, w / 2 + w / 60, h / 2 + w / 60], fill="#ff3b30")
    im.save(path)
    return path


def main():
    ap = argparse.ArgumentParser(description="xmeml sizing calibration kit for Premiere / Resolve / VEGAS")
    ap.add_argument("--out", default="calib")
    ap.add_argument("--target", default="all", choices=list(pc_nle.TARGETS) + ["all"])
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    hd = grid(out / "grid_1920.png", 1920, 1080)
    uhd = grid(out / "grid_3840.png", 3840, 2160)
    tl = {"name": "calib", "size": [1920, 1080], "fps": 30, "duration": 14.0, "markers": [],
          "tracks": [{"type": "video", "name": "Shots", "clips": [
              {"id": "A_native", "file": str(hd), "start": 0.0, "duration": 3.0},
              {"id": "B_cover", "file": str(uhd), "start": 3.0, "duration": 3.0},
              {"id": "C_zoom_topleft", "file": str(uhd), "start": 6.0, "duration": 4.0,
               "motion": {"kind": "zoom_in", "amp": 1.0, "focus": [0.25, 0.25]}},
              {"id": "D_pan_right", "file": str(uhd), "start": 10.0, "duration": 4.0,
               "motion": {"kind": "pan_right", "amp": 1.0}}]}]}
    for clip in tl["tracks"][0]["clips"]:
        clip.update(kind="image", source_in=0.0, speed=1.0)
    cfg = load_config()
    pc_timeline.hydrate(tl, cfg)
    result = pc_nle.export(tl, args.target, out, cfg=cfg)
    for name, r in result["targets"].items():
        print(name, r["xml"])
    print(NOTES)


if __name__ == "__main__":
    main()
