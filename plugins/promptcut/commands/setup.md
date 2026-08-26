---
description: Check and set up PromptCut - ffmpeg, OpenRouter key, stock keys, CapCut folder
---

Run `doctor` from the `video-toolbox` skill and walk the person through only the
problems it reports. Extra context: $ARGUMENTS

- ffmpeg missing on Windows: `winget install Gyan.FFmpeg`, then a new terminal.
- OpenRouter key: openrouter.ai/keys, then `setx OPENROUTER_API_KEY sk-or-...`
  and a new terminal, or `config --set openrouter_api_key=sk-or-...`.
- Free voice instead of paid TTS: `pip install edge-tts`, then
  `config --set tts_provider=edge` and pick a voice, e.g. `ru-RU-DmitryNeural`.
- Stock images and music: free keys from pexels.com/api, pixabay.com/api/docs,
  freesound.org/apiv2/apply, devportal.jamendo.com, then
  `keys --set pexels=... freesound=...`. Openverse and Wikimedia need no key.
- CapCut export: `pip install pycapcut`, then `capcut-drafts`; if the folder is
  not found, ask for CapCut → Settings → Draft location.

Finish with a one-line summary of what works now and what is still missing.
