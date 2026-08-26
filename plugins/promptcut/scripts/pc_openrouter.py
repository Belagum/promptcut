# -*- coding: utf-8 -*-
"""OpenRouter client on stdlib only: images, speech, transcription."""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pc_common import api_key, die, info, load_config, log_spend, warn

BASE = "https://openrouter.ai/api/v1"
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524}
BACKOFF = (3, 8, 20)


def _headers(cfg: dict, key: str, json_body: bool = True) -> dict:
    h = {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": cfg.get("http_referer", ""),
        "X-Title": cfg.get("app_title", "PromptCut"),
    }
    if json_body:
        h["Content-Type"] = "application/json"
    return {k: v for k, v in h.items() if v}


def _explain(status: int, body: str) -> str:
    hints = {
        401: "OpenRouter key missing or invalid (check OPENROUTER_API_KEY)",
        402: "no OpenRouter credit left, or the key hit its limit",
        403: "model not available for this key (check privacy and provider settings)",
        404: "no such model, check the model slug",
        429: "rate limited",
    }
    hint = hints.get(status, "")
    body = body.strip()
    try:
        parsed = json.loads(body)
        body = parsed.get("error", {}).get("message") or body
    except Exception:
        pass
    return f"HTTP {status}{(' - ' + hint) if hint else ''}: {body[:400]}"


def _request(method: str, path: str, *, cfg: dict, payload=None, timeout=180,
            raw: bool = False, attempts: int = 4):
    key = api_key(cfg)
    if not key:
        die("no OpenRouter key. Set it: setx OPENROUTER_API_KEY sk-or-... "
            "or run /promptcut:setup")
    url = f"{BASE}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    last = ""
    for i in range(attempts):
        req = urllib.request.Request(url, data=data, method=method,
                                     headers=_headers(cfg, key, json_body=data is not None))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                gen_id = resp.headers.get("X-Generation-Id", "")
                if raw:
                    return body, gen_id
                return json.loads(body.decode("utf-8")), gen_id
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            last = _explain(exc.code, body)
            if exc.code in RETRY_STATUS and i < attempts - 1:
                wait = BACKOFF[min(i, len(BACKOFF) - 1)]
                warn(f"{last} - retrying in {wait}s")
                time.sleep(wait)
                continue
            die(last)
        except (urllib.error.URLError, TimeoutError) as exc:
            last = f"network unreachable: {exc}"
            if i < attempts - 1:
                wait = BACKOFF[min(i, len(BACKOFF) - 1)]
                warn(f"{last} - retrying in {wait}s")
                time.sleep(wait)
                continue
            die(last)
    die(last or "request failed for an unknown reason")


def generate_image(prompt: str, out_path: Path, *, cfg: dict, model: str | None = None,
                   aspect_ratio: str = "16:9", resolution: str | None = None,
                   output_format: str | None = None, seed=None) -> Path:
    model = model or cfg["image_model"]
    payload = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution or cfg.get("image_resolution") or "2K",
        "output_format": output_format or cfg.get("image_format") or "png",
        "n": 1,
    }
    if seed is not None:
        payload["seed"] = int(seed)
    body, _ = _request("POST", "/images", cfg=cfg, payload=payload, timeout=240)
    items = body.get("data") or []
    if not items:
        die(f"model {model} returned no image: {str(body)[:300]}")
    item = items[0]
    b64 = item.get("b64_json") or item.get("base64") or item.get("image")
    if not b64 and item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=120) as r:
            raw = r.read()
    elif b64:
        if isinstance(b64, str) and b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        raw = base64.b64decode(b64)
    else:
        die(f"no image payload in response: {str(item)[:300]}")
    media = (item.get("media_type") or "image/png").split("/")[-1].replace("jpeg", "jpg")
    out_path = out_path.with_suffix("." + media if media in ("png", "jpg", "webp") else ".png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)
    cost = (body.get("usage") or {}).get("cost")
    log_spend("image", model, cost, prompt)
    return out_path


def synth_speech(text: str, out_path: Path, *, cfg: dict, model: str | None = None,
                 voice: str | None = None, speed: float | None = None,
                 instructions: str | None = None) -> Path:
    model = model or cfg["tts_model"]
    payload = {
        "model": model,
        "input": text,
        "voice": voice or cfg.get("tts_voice") or "alloy",
        "response_format": "mp3",
    }
    if speed and abs(speed - 1.0) > 1e-3:
        payload["speed"] = float(speed)
    if instructions:
        payload["instructions"] = instructions
    raw, gen_id = _request("POST", "/audio/speech", cfg=cfg, payload=payload,
                           timeout=180, raw=True)
    if not raw or len(raw) < 512:
        die(f"empty speech payload (model {model}, {len(raw or b'')} bytes)")
    out_path = out_path.with_suffix(".mp3")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)
    log_spend("tts", model, None, text[:120])
    return out_path


def transcribe(audio_path: Path, *, cfg: dict, model: str | None = None,
               language: str | None = None, granularity: str = "word") -> dict:
    model = model or cfg.get("transcribe_model") or "openai/whisper-1"
    payload = {
        "model": model,
        "input_audio": {
            "data": base64.b64encode(Path(audio_path).read_bytes()).decode("ascii"),
            "format": Path(audio_path).suffix.lstrip(".").lower() or "mp3",
        },
        "response_format": "verbose_json",
        "timestamp_granularities": [granularity],
    }
    if language:
        payload["language"] = language
    body, _ = _request("POST", "/audio/transcriptions", cfg=cfg, payload=payload, timeout=240)
    log_spend("transcribe", model, (body.get("usage") or {}).get("cost"), str(audio_path))
    return body


def list_models(cfg: dict, modality: str = "image") -> list:
    body, _ = _request("GET", f"/models?output_modalities={urllib.parse.quote(modality)}",
                       cfg=cfg, timeout=60)
    out = []
    for m in body.get("data") or []:
        pricing = m.get("pricing") or {}
        out.append({
            "id": m.get("id"),
            "name": m.get("name"),
            "price_image": pricing.get("image") or pricing.get("output_image"),
            "price_out": pricing.get("completion") or pricing.get("output"),
            "params": m.get("supported_parameters") or [],
        })
    return out
