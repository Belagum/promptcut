# -*- coding: utf-8 -*-
"""OpenRouter client on stdlib only: images, speech, transcription, chat."""
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


class OpenRouterError(RuntimeError):
    """Recoverable API failure (raised instead of exiting when soft=True)."""


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
            raw: bool = False, attempts: int = 4, soft: bool = False):
    key = api_key(cfg)
    if not key:
        die("no OpenRouter key. Set it: setx OPENROUTER_API_KEY sk-or-... "
            "or run /promptcut:setup")
    url = f"{BASE}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    last = ""

    def fail(msg):
        if soft:
            raise OpenRouterError(msg)
        die(msg)

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
            return fail(last)
        except (urllib.error.URLError, TimeoutError) as exc:
            last = f"network unreachable: {exc}"
            if i < attempts - 1:
                wait = BACKOFF[min(i, len(BACKOFF) - 1)]
                warn(f"{last} - retrying in {wait}s")
                time.sleep(wait)
                continue
            return fail(last)
    return fail(last or "request failed for an unknown reason")


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


MUSIC_ONLY_MARKERS = ("lyria", "music", "suno", "riffusion")


def list_tts_models(cfg: dict) -> dict:
    """Audio-output models that can speak (music generators filtered out)."""
    models = [m for m in list_models(cfg, "audio")
              if m.get("id") and not any(t in m["id"] for t in MUSIC_ONLY_MARKERS)]
    return {"models": models, "auto_pick": _pick_tts_id([m["id"] for m in models])}


def _pick_tts_id(ids: list) -> str | None:
    for marker in ("gpt-audio-mini", "gpt-audio", "-tts", "tts-"):
        for i in ids:
            if marker in i:
                return i
    return ids[0] if ids else None


def _synth_speech_endpoint(model, text, out_path, *, cfg, voice, speed, instructions) -> Path:
    payload = {"model": model, "input": text, "voice": voice, "response_format": "mp3"}
    if speed and abs(speed - 1.0) > 1e-3:
        payload["speed"] = float(speed)
    if instructions:
        payload["instructions"] = instructions
    raw, _ = _request("POST", "/audio/speech", cfg=cfg, payload=payload,
                      timeout=180, raw=True, soft=True)
    if not raw or len(raw) < 512:
        raise OpenRouterError(f"empty speech payload (model {model}, {len(raw or b'')} bytes)")
    out_path.write_bytes(raw)
    log_spend("tts", model, None, text[:120])
    return out_path


def _synth_chat_audio(model, text, out_path, *, cfg, voice, speed, instructions) -> Path:
    # chat-audio models only speak over a streaming request (pcm16 chunks)
    system = ("You are a text-to-speech engine. Read the user's text aloud exactly as "
              "written, verbatim and completely, in the language it is written in. "
              "Never add, skip, translate or comment on anything.")
    if instructions:
        system += f" Delivery style: {instructions}"
    payload = {
        "model": model,
        "modalities": ["text", "audio"],
        "audio": {"voice": voice, "format": "pcm16"},
        "stream": True,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": text}],
        "usage": {"include": True},
    }
    key = api_key(cfg)
    if not key:
        die("no OpenRouter key. Set it: setx OPENROUTER_API_KEY sk-or-... "
            "or run /promptcut:setup")
    req = urllib.request.Request(f"{BASE}/chat/completions",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers=_headers(cfg, key), method="POST")
    pcm, cost = bytearray(), None
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            for line_bytes in resp:
                line = line_bytes.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if (chunk.get("usage") or {}).get("cost") is not None:
                    cost = chunk["usage"]["cost"]
                delta = ((chunk.get("choices") or [{}])[0].get("delta")) or {}
                b64 = (delta.get("audio") or {}).get("data")
                if b64:
                    pcm.extend(base64.b64decode(b64))
    except urllib.error.HTTPError as exc:
        raise OpenRouterError(_explain(exc.code, exc.read().decode("utf-8", "replace")))
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OpenRouterError(f"network unreachable: {exc}")
    if len(pcm) < 4096:
        raise OpenRouterError(f"model {model} returned no audio ({len(pcm)} bytes)")
    from pc_common import ffmpeg_bin, run
    tmp_raw = out_path.with_suffix(".pcm")
    tmp_raw.write_bytes(pcm)
    cmd = [ffmpeg_bin(cfg), "-y", "-v", "error",
           "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", str(tmp_raw)]
    if speed and abs(speed - 1.0) > 1e-3:
        cmd += ["-filter:a", f"atempo={max(0.5, min(2.0, float(speed)))}"]
    cmd += ["-c:a", "libmp3lame", "-q:a", "2", str(out_path)]
    run(cmd, desc="pcm to mp3")
    tmp_raw.unlink(missing_ok=True)
    log_spend("tts", model, cost, text[:120])
    return out_path


def synth_speech(text: str, out_path: Path, *, cfg: dict, model: str | None = None,
                 voice: str | None = None, speed: float | None = None,
                 instructions: str | None = None) -> Path:
    model = model or cfg["tts_model"]
    voice = voice or cfg.get("tts_voice") or "alloy"
    out_path = out_path.with_suffix(".mp3")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def synth(m):
        # dedicated speech models go through /audio/speech, chat-audio
        # models (gpt-audio and friends) through /chat/completions
        fn = _synth_speech_endpoint if "tts" in m.lower() else _synth_chat_audio
        return fn(m, text, out_path, cfg=cfg, voice=voice, speed=speed,
                  instructions=instructions)

    try:
        return synth(model)
    except OpenRouterError as exc:
        gone = any(t in str(exc) for t in ("does not exist", "HTTP 404", "not a valid model"))
        if not gone:
            die(str(exc))
        fallback = _pick_tts_id([m["id"] for m in list_tts_models(cfg)["models"]])
        if not fallback or fallback == model:
            die(str(exc))
        warn(f"tts model {model} is gone from OpenRouter, switching to {fallback} "
             f"(persist it: promptcut config --set tts_model={fallback})")
        try:
            return synth(fallback)
        except OpenRouterError as exc2:
            die(str(exc2))


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


IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp", ".gif": "image/gif"}
AUDIO_FORMATS = {".mp3": "mp3", ".wav": "wav"}
MAX_ATTACH_MB = 24


def _file_part(path: Path) -> dict:
    suffix = path.suffix.lower()
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    if suffix in IMAGE_MIME:
        return {"type": "image_url",
                "image_url": {"url": f"data:{IMAGE_MIME[suffix]};base64,{data}"}}
    if suffix in AUDIO_FORMATS:
        return {"type": "input_audio",
                "input_audio": {"data": data, "format": AUDIO_FORMATS[suffix]}}
    die(f"unsupported attachment '{path.name}' (images: png/jpg/webp/gif, audio: mp3/wav)")


def chat(prompt: str, *, cfg: dict, model: str | None = None, system: str | None = None,
         files: list | None = None, json_mode: bool = False,
         max_tokens: int | None = None) -> dict:
    model = model or cfg.get("chat_model") or "google/gemini-2.5-flash"
    files = [Path(f) for f in files or []]
    total = sum(f.stat().st_size for f in files)
    if total > MAX_ATTACH_MB * 1048576:
        die(f"attachments too large ({total / 1048576:.1f} MB, limit {MAX_ATTACH_MB} MB)")
    if files:
        content = [_file_part(f) for f in files]
        content.append({"type": "text", "text": prompt})
    else:
        content = prompt
    messages = ([{"role": "system", "content": system}] if system else [])
    messages.append({"role": "user", "content": content})
    payload = {"model": model, "messages": messages, "usage": {"include": True}}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if max_tokens:
        payload["max_tokens"] = int(max_tokens)
    body, _ = _request("POST", "/chat/completions", cfg=cfg, payload=payload, timeout=300)
    msg = (body.get("choices") or [{}])[0].get("message") or {}
    text = msg.get("content") or ""
    if isinstance(text, list):
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    cost = (body.get("usage") or {}).get("cost")
    log_spend("chat", model, cost, prompt[:120])
    return {"text": text, "model": body.get("model") or model, "cost_usd": cost}


def edit_image(prompt: str, images: list, out_path: Path, *, cfg: dict,
               model: str | None = None) -> Path:
    model = model or cfg.get("image_edit_model") or "google/gemini-2.5-flash-image"
    content = []
    for img in images or []:
        img = Path(img)
        if img.suffix.lower() not in IMAGE_MIME:
            die(f"'{img.name}' is not an image (png/jpg/webp/gif)")
        content.append(_file_part(img))
    content.append({"type": "text", "text": prompt})
    payload = {"model": model, "messages": [{"role": "user", "content": content}],
               "modalities": ["image", "text"], "usage": {"include": True}}
    body, _ = _request("POST", "/chat/completions", cfg=cfg, payload=payload, timeout=300)
    msg = (body.get("choices") or [{}])[0].get("message") or {}
    url = None
    for item in msg.get("images") or []:
        u = (item.get("image_url") or {}).get("url") if isinstance(item, dict) else None
        if u:
            url = u
            break
    if not url and isinstance(msg.get("content"), list):
        for part in msg["content"]:
            if isinstance(part, dict) and part.get("type") == "image_url":
                url = (part.get("image_url") or {}).get("url")
                break
    if not url:
        die(f"model {model} returned no image: {str(msg)[:300]}")
    if url.startswith("data:"):
        header, _, b64 = url.partition(",")
        raw = base64.b64decode(b64)
        media = header.split(";")[0].split("/")[-1].replace("jpeg", "jpg")
    else:
        with urllib.request.urlopen(url, timeout=120) as r:
            raw = r.read()
        media = "png"
    out_path = out_path.with_suffix("." + (media if media in ("png", "jpg", "webp") else "png"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)
    log_spend("image-edit", model, (body.get("usage") or {}).get("cost"), prompt)
    return out_path


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
