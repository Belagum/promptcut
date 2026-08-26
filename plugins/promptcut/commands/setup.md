---
description: Set up PromptCut - installs deps (pip, ffmpeg), checks keys, CapCut folder
---

Using the `video-toolbox` skill: run `setup` first - it pip-installs the missing
optional packages (pillow, yt-dlp, edge-tts, pycapcut) and ffmpeg via
winget/brew on its own. Then run `doctor` and walk the person through only what
is still red. Extra context: $ARGUMENTS

What setup cannot do by itself:

- OpenRouter key: openrouter.ai/settings/keys, then
  `config --set openrouter_api_key=sk-or-...` (works immediately), or
  `setx OPENROUTER_API_KEY sk-or-...` + a new terminal.
- Free voice instead of paid TTS: `config --set tts_provider=edge` and pick a
  voice, e.g. `ru-RU-DmitryNeural`.
- Stock images and music: free keys from pexels.com/api, pixabay.com/api/docs,
  freesound.org/apiv2/apply, devportal.jamendo.com, then
  `keys --set pexels=... freesound=...`. Openverse, Wikimedia and archive.org
  need no key.
- CapCut export: `capcut-drafts`; if the folder is not found, ask for
  CapCut → Settings → Draft location.
- If ffmpeg was just installed by winget, a new terminal may be needed for PATH.
- If YouTube demands a login in `media-dl`:
  `config --set ytdlp_cookies=firefox` (or chrome/edge, or a cookies.txt path).

Finish with a one-line summary of what works now and what is still missing.
