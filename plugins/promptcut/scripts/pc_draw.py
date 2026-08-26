# -*- coding: utf-8 -*-
"""Pillow graphics: callout shapes over images/video and exact-text typography cards."""
from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path

from pc_common import die, ffmpeg_bin, load_config, run

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

BOLD_FONTS = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
)


def _pil():
    try:
        from PIL import Image, ImageColor, ImageDraw, ImageFont  # noqa: PLC0415
        return Image, ImageColor, ImageDraw, ImageFont
    except ImportError:
        die("Pillow is required for this command: pip install pillow")


def _font(size: float, path: str | None = None, bold: bool = True):
    _, _, _, ImageFont = _pil()
    import pc_media  # noqa: PLC0415
    cands = ([path] if path else []) + (list(BOLD_FONTS) if bold else [])
    ff = pc_media.font_file()
    if ff:
        cands.append(ff)
    for c in cands:
        if c and Path(c).exists():
            try:
                return ImageFont.truetype(c, int(size))
            except Exception:  # noqa: BLE001
                continue
    try:
        return ImageFont.load_default(int(size))
    except TypeError:
        return ImageFont.load_default()


def _rgba(color: str, alpha: int = 255):
    _, ImageColor, _, _ = _pil()
    r, g, b = ImageColor.getrgb(color)[:3]
    return (r, g, b, int(alpha))


def _px(value, ref: float) -> float:
    value = float(value)
    return value * ref if 0.0 <= value <= 1.0 else value


def _draw_shape(d, s: dict, w: int, h: int) -> None:
    kind = (s.get("type") or "circle").lower()
    color = _rgba(s.get("color") or "#FF3B30", int(255 * float(s.get("opacity", 1.0))))
    lw = int(s.get("stroke") or max(4, round(min(w, h) * 0.008)))
    if kind in ("circle", "ellipse"):
        cx, cy = _px(s.get("x", 0.5), w), _px(s.get("y", 0.5), h)
        if "rx" in s or "ry" in s:
            rx = _px(s.get("rx", s.get("ry")), w)
            ry = _px(s.get("ry", s.get("rx")), h)
        else:
            rx = ry = _px(s.get("r", 0.08), min(w, h))
        d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], outline=color, width=lw)
    elif kind == "box":
        x1, y1 = _px(s.get("x1", s.get("x", 0.25)), w), _px(s.get("y1", s.get("y", 0.25)), h)
        if "x2" in s or "y2" in s:
            x2, y2 = _px(s.get("x2", x1), w), _px(s.get("y2", y1), h)
        else:
            x2, y2 = x1 + _px(s.get("w", 0.2), w), y1 + _px(s.get("h", 0.2), h)
        d.rectangle([x1, y1, x2, y2], outline=color, width=lw)
    elif kind in ("arrow", "line"):
        x1, y1 = _px(s.get("x1", 0.2), w), _px(s.get("y1", 0.2), h)
        x2, y2 = _px(s.get("x2", 0.5), w), _px(s.get("y2", 0.5), h)
        d.line([x1, y1, x2, y2], fill=color, width=lw)
        if kind == "arrow":
            ang = math.atan2(y2 - y1, x2 - x1)
            head = max(18.0, lw * 4.5)
            left = (x2 - head * math.cos(ang - 0.45), y2 - head * math.sin(ang - 0.45))
            right = (x2 - head * math.cos(ang + 0.45), y2 - head * math.sin(ang + 0.45))
            d.polygon([(x2, y2), left, right], fill=color)
    elif kind == "text":
        x, y = _px(s.get("x", 0.5), w), _px(s.get("y", 0.5), h)
        font = _font(_px(s.get("size", 0.05), h), s.get("font"))
        d.text((x, y), str(s.get("text") or ""), font=font, fill=color, anchor="mm",
               stroke_width=max(2, lw // 2), stroke_fill=_rgba(s.get("stroke_color") or "black"))
    else:
        die(f"unknown shape type '{kind}' (circle, box, arrow, line, text)")


def _overlay_png(shapes: list, w: int, h: int, path: Path) -> Path:
    Image, _, ImageDraw, _ = _pil()
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for s in shapes:
        _draw_shape(d, s, w, h)
    im.save(path)
    return path


def annotate(src, out, shapes, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    src, out = Path(src), Path(out)
    if isinstance(shapes, dict):
        shapes = [shapes]
    if not shapes:
        die("no shapes to draw")
    if src.suffix.lower() in IMAGE_EXT:
        Image, _, ImageDraw, _ = _pil()
        im = Image.open(src).convert("RGBA")
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        for s in shapes:
            _draw_shape(d, s, *im.size)
        im = Image.alpha_composite(im, ov)
        if out.suffix.lower() in (".jpg", ".jpeg"):
            im = im.convert("RGB")
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out)
        return {"file": str(out), "shapes": len(shapes)}

    import pc_edit  # noqa: PLC0415
    meta = pc_edit.probe(src, cfg)
    w, h = int(meta["width"]), int(meta["height"])
    groups: dict = {}
    for s in shapes:
        key = (float(s.get("at", 0.0)), s.get("dur"), float(s.get("blink") or 0.0))
        groups.setdefault(key, []).append(s)
    tmp = Path(tempfile.mkdtemp())
    cmd = [ffmpeg_bin(cfg), "-y", "-v", "error", "-i", str(src)]
    graph, prev = [], "0:v"
    for i, (key, group) in enumerate(sorted(groups.items(), key=lambda kv: kv[0][0]), start=1):
        at, dur, blink = key
        end = at + float(dur) if dur is not None else float(meta["duration"]) + 1.0
        cmd += ["-i", str(_overlay_png(group, w, h, tmp / f"ov{i}.png"))]
        enable = f"between(t,{at:.3f},{end:.3f})"
        if blink > 0:
            enable += f"*lt(mod(t-{at:.3f},{2 * blink:.3f}),{blink:.3f})"
        graph.append(f"[{prev}][{i}:v]overlay=0:0:enable='{enable}'[v{i}]")
        prev = f"v{i}"
    cmd += ["-filter_complex", ";".join(graph), "-map", f"[{prev}]"]
    if meta["has_audio"]:
        cmd += ["-map", "0:a", "-c:a", "copy"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(out)]
    run(cmd, desc="annotate")
    shutil.rmtree(tmp, ignore_errors=True)
    return {"file": str(out), "shapes": len(shapes), "layers": len(groups)}


def _wrap_lines(chars: list, font, gapw: float, divw: float, avail: float) -> list:
    lines, cur, cur_w = [], [], 0.0
    for item in chars:
        cw = max(font.getlength(item[0]), font.size * 0.22) + gapw + (divw if item[1] else 0)
        if item[0] == " " and cur and cur_w + cw > avail:
            lines.append(cur)
            cur, cur_w = [], 0.0
            continue
        cur.append(item)
        cur_w += cw
    if cur:
        lines.append(cur)
    return lines


def card(text: str, out, *, size: str = "1920x1080", title: str | None = None,
         sub: str | None = None, letters: bool = False, highlights: list | None = None,
         bg: str = "#10141F", fg: str = "#FFFFFF", accent: str = "#FFD23F",
         transparent: bool = False, font_path: str | None = None) -> dict:
    Image, _, ImageDraw, _ = _pil()
    w, _, h = size.partition("x")
    w, h = int(w), int(h)
    out = Path(out)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0) if transparent else _rgba(bg))
    d = ImageDraw.Draw(im)

    # "|" in text marks group dividers (morpheme splits); it is drawn, not counted
    groups = str(text).split("|")
    chars = []  # [char, divider_after, global_index]
    for gi, g in enumerate(groups):
        for c in g:
            chars.append([c, False, len(chars)])
        if gi < len(groups) - 1 and chars:
            chars[-1][1] = True
    if not chars:
        die("card text is empty")
    plain = "".join(c for c, _, _ in chars)

    hl: set = set()
    for needle in highlights or []:
        low, nl = plain.lower(), needle.lower()
        i = low.find(nl)
        while i >= 0:
            hl.update(range(i, i + len(needle)))
            i = low.find(nl, i + 1)

    avail = w * 0.84
    base = 200
    font = _font(base, font_path)

    def measure(f):
        gw = f.size * (0.20 if letters else 0.03)
        dw = f.size * 0.30
        tot = sum(max(f.getlength(c), f.size * 0.22) for c, _, _ in chars)
        tot += gw * (len(chars) - 1) + dw * sum(1 for _, dv, _ in chars if dv)
        return gw, dw, tot

    gapw, divw, total = measure(font)
    fsize = base * avail / max(total, 1.0)
    fsize = min(fsize, h * (0.30 if letters else 0.36))
    if not letters and fsize < h * 0.10 and " " in plain:
        fsize = min(h * 0.14, fsize * 2.2)
    font = _font(max(int(fsize), 14), font_path)
    gapw, divw, total = measure(font)
    lines = [chars] if letters or total <= avail else _wrap_lines(chars, font, gapw, divw, avail)

    ascent, descent = font.getmetrics()
    line_h = (ascent + descent) * 1.12
    num_font = _font(max(14, int(font.size * 0.22)), font_path) if letters else None
    num_h = (num_font.getmetrics()[0] + num_font.getmetrics()[1]) if num_font else 0
    block_h = len(lines) * line_h + (num_h + font.size * 0.10 if letters else 0)
    y = (h - block_h) / 2 + (h * 0.02 if title else 0) - (h * 0.02 if sub else 0)

    count = 0
    for line in lines:
        widths = [max(font.getlength(c), font.size * 0.22) for c, _, _ in line]
        line_w = sum(widths) + gapw * (len(line) - 1) + divw * sum(1 for _, dv, _ in line if dv)
        x = (w - line_w) / 2
        base_y = y + ascent
        for (c, dv, gi), cw in zip(line, widths):
            color = _rgba(accent) if gi in hl else _rgba(fg)
            d.text((x + cw / 2, base_y), c, font=font, fill=color, anchor="ms")
            if letters and c.isalnum():
                count += 1
                num_color = _rgba(accent) if gi in hl else _rgba(fg, 150)
                d.text((x + cw / 2, y + line_h + font.size * 0.02), str(count),
                       font=num_font, fill=num_color, anchor="ma")
            x += cw + gapw
            if dv:
                dx = x - gapw / 2 + divw / 2
                d.line([dx, base_y - ascent * 0.68, dx, base_y + descent * 0.15],
                       fill=_rgba(accent, 170), width=max(3, font.size // 26))
                x += divw
    if letters:
        count = count or sum(1 for c, _, _ in chars if c.isalnum())

    def fit(text_s, size, bold=True):
        f = _font(int(size), font_path, bold)
        tw = f.getlength(text_s)
        if tw > w * 0.9:
            f = _font(max(14, int(size * w * 0.9 / tw)), font_path, bold)
        return f

    if title:
        d.text((w / 2, h * 0.14), title, font=fit(title, h * 0.045),
               fill=_rgba(accent), anchor="mm")
    if sub:
        d.text((w / 2, h * 0.87), sub, font=fit(sub, h * 0.038, bold=False),
               fill=_rgba(fg, 185), anchor="mm")

    if out.suffix.lower() in (".jpg", ".jpeg"):
        im = im.convert("RGB")
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return {"file": str(out), "size": [w, h], "chars": len(plain),
            "numbered": count if letters else None}
