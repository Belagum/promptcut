# -*- coding: utf-8 -*-
"""Stock search and download for images, video, music and sound effects.

No key needed: openverse, wikimedia, archive.
Free key needed: pexels, pixabay, unsplash (images, video),
freesound, jamendo (audio). Keys live in ~/.promptcut/config.json -> "stock_keys".
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pc_common import die, info, load_config, sha, warn

UA = "PromptCut/0.1 (+https://github.com/promptcut) python-urllib"
IMAGE_PROVIDERS = ("pexels", "unsplash", "pixabay", "openverse", "wikimedia")
VIDEO_PROVIDERS = ("pexels", "pixabay")
AUDIO_PROVIDERS = ("freesound", "jamendo", "archive", "openverse")


def _key(cfg: dict, name: str) -> str:
    keys = cfg.get("stock_keys") or {}
    return (os.environ.get(f"PROMPTCUT_{name.upper()}_KEY")
            or keys.get(name) or "").strip()


def _get(url: str, headers: dict | None = None, timeout: int = 40):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode('utf-8','replace')[:200]}")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(str(exc))


def _q(**kw) -> str:
    return urllib.parse.urlencode({k: v for k, v in kw.items() if v not in (None, "")})


def _pexels_images(q, n, cfg, orientation=None):
    key = _key(cfg, "pexels")
    if not key:
        return []
    data = _get(f"https://api.pexels.com/v1/search?{_q(query=q, per_page=n, orientation=orientation)}",
                {"Authorization": key})
    return [{"provider": "pexels", "url": p["src"]["original"], "title": p.get("alt") or q,
             "author": p.get("photographer"), "page": p.get("url"),
             "w": p.get("width"), "h": p.get("height"), "license": "Pexels License"}
            for p in data.get("photos", [])]


def _unsplash_images(q, n, cfg, orientation=None):
    key = _key(cfg, "unsplash")
    if not key:
        return []
    data = _get(f"https://api.unsplash.com/search/photos?{_q(query=q, per_page=n, orientation=orientation)}",
                {"Authorization": f"Client-ID {key}"})
    return [{"provider": "unsplash", "url": p["urls"]["raw"] + "&w=2400",
             "title": p.get("description") or p.get("alt_description") or q,
             "author": (p.get("user") or {}).get("name"), "page": (p.get("links") or {}).get("html"),
             "w": p.get("width"), "h": p.get("height"), "license": "Unsplash License"}
            for p in data.get("results", [])]


def _pixabay_images(q, n, cfg, orientation=None):
    key = _key(cfg, "pixabay")
    if not key:
        return []
    data = _get(f"https://pixabay.com/api/?{_q(key=key, q=q, per_page=max(3, n), image_type='photo', orientation=orientation or 'all')}")
    return [{"provider": "pixabay", "url": p.get("largeImageURL") or p.get("webformatURL"),
             "title": p.get("tags") or q, "author": p.get("user"), "page": p.get("pageURL"),
             "w": p.get("imageWidth"), "h": p.get("imageHeight"), "license": "Pixabay License"}
            for p in data.get("hits", [])]


def _openverse_images(q, n, cfg, orientation=None):
    data = _get(f"https://api.openverse.org/v1/images/?{_q(q=q, page_size=n, license_type='commercial')}")
    return [{"provider": "openverse", "url": p.get("url"), "title": p.get("title") or q,
             "author": p.get("creator"), "page": p.get("foreign_landing_url"),
             "w": p.get("width"), "h": p.get("height"), "license": p.get("license")}
            for p in data.get("results", [])]


def _wikimedia_images(q, n, cfg, orientation=None):
    url = ("https://commons.wikimedia.org/w/api.php?" + _q(
        action="query", format="json", generator="search", gsrnamespace=6,
        gsrsearch=f"filetype:bitmap {q}", gsrlimit=n, prop="imageinfo",
        iiprop="url|size|extmetadata", iiurlwidth=2400))
    data = _get(url)
    out = []
    for page in (data.get("query", {}).get("pages") or {}).values():
        ii = (page.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata") or {}
        out.append({"provider": "wikimedia", "url": ii.get("thumburl") or ii.get("url"),
                    "title": page.get("title", q), "page": ii.get("descriptionurl"),
                    "author": (meta.get("Artist") or {}).get("value", "")[:80],
                    "w": ii.get("width"), "h": ii.get("height"),
                    "license": (meta.get("LicenseShortName") or {}).get("value")})
    return out


def _pexels_videos(q, n, cfg, orientation=None):
    key = _key(cfg, "pexels")
    if not key:
        return []
    data = _get(f"https://api.pexels.com/videos/search?{_q(query=q, per_page=n, orientation=orientation)}",
                {"Authorization": key})
    out = []
    for v in data.get("videos", []):
        files = sorted([f for f in v.get("video_files", []) if f.get("width")],
                       key=lambda f: -f["width"])
        if not files:
            continue
        out.append({"provider": "pexels", "url": files[0]["link"], "title": q,
                    "author": (v.get("user") or {}).get("name"), "page": v.get("url"),
                    "w": files[0].get("width"), "h": files[0].get("height"),
                    "duration": v.get("duration"), "license": "Pexels License"})
    return out


def _pixabay_videos(q, n, cfg, orientation=None):
    key = _key(cfg, "pixabay")
    if not key:
        return []
    data = _get(f"https://pixabay.com/api/videos/?{_q(key=key, q=q, per_page=max(3, n))}")
    out = []
    for v in data.get("hits", []):
        streams = v.get("videos") or {}
        best = streams.get("large") or streams.get("medium") or {}
        if not best.get("url"):
            continue
        out.append({"provider": "pixabay", "url": best["url"], "title": v.get("tags") or q,
                    "author": v.get("user"), "page": v.get("pageURL"),
                    "w": best.get("width"), "h": best.get("height"),
                    "duration": v.get("duration"), "license": "Pixabay License"})
    return out


def _freesound_audio(q, n, cfg, **_):
    key = _key(cfg, "freesound")
    if not key:
        return []
    data = _get("https://freesound.org/apiv2/search/text/?" + _q(
        query=q, page_size=n, token=key, fields="name,previews,duration,license,url,username"))
    return [{"provider": "freesound", "url": (r.get("previews") or {}).get("preview-hq-mp3"),
             "title": r.get("name"), "author": r.get("username"), "page": r.get("url"),
             "duration": r.get("duration"), "license": r.get("license")}
            for r in data.get("results", []) if (r.get("previews") or {}).get("preview-hq-mp3")]


def _jamendo_audio(q, n, cfg, **_):
    key = _key(cfg, "jamendo")
    if not key:
        return []
    data = _get("https://api.jamendo.com/v3.0/tracks/?" + _q(
        client_id=key, format="json", limit=n, search=q, audioformat="mp32",
        include="musicinfo", boost="popularity_total"))
    return [{"provider": "jamendo", "url": r.get("audiodownload") or r.get("audio"),
             "title": f"{r.get('name')} — {r.get('artist_name')}", "author": r.get("artist_name"),
             "page": r.get("shareurl"), "duration": r.get("duration"),
             "license": r.get("license_ccurl") or "CC"}
            for r in data.get("results", []) if r.get("audio")]


def _archive_audio(q, n, cfg, **_):
    params = _q(q=f"title:({q}) AND mediatype:(audio)", rows=max(3, n), page=1, output="json")
    data = _get(f"https://archive.org/advancedsearch.php?{params}"
                "&fl[]=identifier&fl[]=title&fl[]=creator")
    out = []
    for doc in (data.get("response") or {}).get("docs") or []:
        ident = doc.get("identifier")
        if not ident:
            continue
        try:
            meta = _get(f"https://archive.org/metadata/{urllib.parse.quote(ident)}")
        except Exception:  # noqa: BLE001
            continue
        f = next((f for f in meta.get("files") or []
                  if str(f.get("name", "")).lower().endswith(".mp3")), None)
        if not f:
            continue
        try:
            raw = str(f.get("length") or "")
            mm, _, ss = raw.rpartition(":")
            dur = round(float(mm or 0) * 60 + float(ss), 2) if raw else None
        except ValueError:
            dur = None
        out.append({"provider": "archive",
                    "url": f"https://archive.org/download/{urllib.parse.quote(ident)}/"
                           f"{urllib.parse.quote(str(f['name']))}",
                    "title": doc.get("title") or ident, "author": doc.get("creator"),
                    "page": f"https://archive.org/details/{ident}",
                    "duration": dur, "license": "varies, see item page"})
        if len(out) >= n:
            break
    return out


def _openverse_audio(q, n, cfg, **_):
    data = _get(f"https://api.openverse.org/v1/audio/?{_q(q=q, page_size=n, license_type='commercial')}")
    return [{"provider": "openverse", "url": r.get("url"), "title": r.get("title") or q,
             "author": r.get("creator"), "page": r.get("foreign_landing_url"),
             "duration": (r.get("duration") or 0) / 1000 or None, "license": r.get("license")}
            for r in data.get("results", []) if r.get("url")]


REGISTRY = {
    "image": {"pexels": _pexels_images, "unsplash": _unsplash_images,
              "pixabay": _pixabay_images, "openverse": _openverse_images,
              "wikimedia": _wikimedia_images},
    "video": {"pexels": _pexels_videos, "pixabay": _pixabay_videos},
    "audio": {"freesound": _freesound_audio, "jamendo": _jamendo_audio,
              "archive": _archive_audio, "openverse": _openverse_audio},
}
ORDER = {"image": IMAGE_PROVIDERS, "video": VIDEO_PROVIDERS, "audio": AUDIO_PROVIDERS}


def search(query: str, kind: str = "image", n: int = 6, provider: str | None = None,
           cfg: dict | None = None, orientation: str | None = None) -> list:
    cfg = cfg or load_config()
    kind = kind if kind in REGISTRY else "image"
    providers = [provider] if provider else [p for p in ORDER[kind]
                                             if p in ("openverse", "wikimedia", "archive")
                                             or _key(cfg, p)]
    if not providers:
        die(f"no provider available for '{kind}'. Add a key: promptcut keys --set pexels=... "
            f"(free at pexels.com/api). openverse and wikimedia work without a key.")
    results = []
    for prov in providers:
        fn = REGISTRY[kind].get(prov)
        if not fn:
            warn(f"provider '{prov}' does not serve {kind}")
            continue
        try:
            found = fn(query, n, cfg, orientation=orientation) or []
            results.extend(found)
            info(f"{prov}: {len(found)} hits")
            if len(results) >= n:
                break
        except Exception as exc:  # noqa: BLE001
            warn(f"{prov} failed: {exc}")
    return [r for r in results if r.get("url")][:n]


def download(url: str, out_path: Path, timeout: int = 120) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        data = resp.read()
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
           "video/mp4": ".mp4", "audio/mpeg": ".mp3", "audio/wav": ".wav",
           "audio/ogg": ".ogg", "audio/x-wav": ".wav"}.get(ctype.split(";")[0].strip())
    if not ext:
        ext = Path(urllib.parse.urlparse(url).path).suffix or ".bin"
    if not out_path.suffix:
        out_path = out_path.with_suffix(ext)
    out_path.write_bytes(data)
    return out_path


def fetch_best(query: str, out_path: Path, kind: str = "image", cfg: dict | None = None,
               provider: str | None = None, orientation: str | None = None) -> dict:
    hits = search(query, kind=kind, n=5, provider=provider, cfg=cfg, orientation=orientation)
    if not hits:
        die(f"nothing found for '{query}' ({kind})")
    for hit in hits:
        try:
            hit["file"] = str(download(hit["url"], out_path))
            return hit
        except Exception as exc:  # noqa: BLE001
            warn(f"download failed ({hit['provider']}): {exc}")
    die(f"{len(hits)} hits but none of them downloaded")
