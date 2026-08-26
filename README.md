# PromptCut

A Claude Code / Cowork plugin that turns a prompt into a finished video — and a
toolbox for every smaller step on the way there.

You say "make me a 40-second vertical video about the Voyager probes, calm
narrator, subtitles". Claude writes the storyboard, generates the voiceover,
generates or finds a picture for every line, animates the stills, lays a music
bed under the narration, burns the subtitles and renders the mp4. If you'd
rather finish by hand, it writes a CapCut project instead, with every clip,
subtitle and effect already on the timeline.

It is not a single pipeline you have to feed. It is ~30 small commands. "Cut the
pauses out of this recording", "make this 16:9 clip vertical", "put this music
under it at -21 dB with ducking", "voice this paragraph" — each is one command,
and Claude picks it.

## Install

```
/plugin marketplace add fedorlobanov/promptcut
/plugin install promptcut@promptcut
```

Then, in Claude, run `/promptcut:setup`. It checks what's missing and tells you
how to fix it. The short version:

```
winget install Gyan.FFmpeg          # Windows; brew install ffmpeg on macOS
setx OPENROUTER_API_KEY sk-or-...   # for generated images and TTS
pip install pycapcut edge-tts       # optional: CapCut export, free voices
```

Python 3.10+ and ffmpeg are the only hard requirements. Everything else buys you
extra capabilities.

## What it does

**Video from a prompt.** A `plan.json` storyboard drives the whole build:
per-shot voiceover, image prompt, Ken Burns motion, transition, sfx, overlay
titles. `--fake` does a free dry run with stub media so you can check pacing and
subtitle splits before spending a cent. Media is cached by content hash, so
fixing one line doesn't re-pay for the other nine.

**Voice.** OpenRouter TTS (`/api/v1/audio/speech`), or free Microsoft Edge voices
via `edge-tts` — including good Russian ones. Shot length follows the real audio
length, so the picture never cuts mid-sentence.

**Pictures.** Generated through OpenRouter (`/api/v1/images` — Seedream,
gpt-image, whatever your key can reach), or pulled from stock: Pexels, Unsplash,
Pixabay with a free key; Openverse and Wikimedia Commons with no key at all.
Music and sound effects come from Freesound, Jamendo or Openverse.

**Editing.** Trim, join with crossfades, overlay logos and PiP, burn text and
subtitles, mix a ducked music bed, change speed with pitch kept, reframe to 9:16
with blurred bars, strip pauses out of a talking head, detect scene cuts, grab
thumbnails, normalise loudness to −16 LUFS.

**CapCut.** Writes a real CapCut project: multiple video, audio, text, effect and
filter tracks, plus transitions (1137 of them), scene effects (1583), filters
(454), intro/outro animations, masks, keyframes on position/scale/rotation/alpha/
volume, styled text with animations, and imported SRT subtitles. Effect names are
searchable, so Claude looks them up instead of hallucinating them.

**Subtitles.** Split at sentence and clause boundaries, balanced across two
lines, timed to the actual voice audio. Burned as ASS with an outline, and
written as a `.srt` next to the video.

## Two examples

```
/promptcut:video 40 seconds on the Voyager probes, calm narrator, vertical
```

Claude drafts the narration, shows it to you, then builds `voyager.mp4` plus
`voyager.srt` and reports what it cost.

```
/promptcut:edit strip the pauses from lecture.mp4, add subtitles, quiet music under it
```

`silence-cut`, `transcribe --srt`, `subs-burn`, `mix --music-db -26`. Four
commands, one answer.

## How it's split

Claude does the judgement: what the shots are, what each picture should be, how
long a line should breathe, which command fits the request. Python does the
deterministic part: API calls, ffmpeg filter graphs, timing arithmetic, the
CapCut draft format. Every command prints JSON on stdout and progress on stderr,
so Claude can chain them without guessing.

The timing model is the part worth knowing about: each shot's length is the real
voiceover duration plus `lead` and `tail`, and clips are rendered
`duration + transition` long so an `xfade` consumes the overlap without ever
drifting the audio against the picture. Ten crossfades in, the narration is still
exactly where the subtitles say it is.

## Costs

Generated images and OpenRouter TTS are billed per call by OpenRouter. Every call
is logged to `~/.promptcut/spend.jsonl`; `promptcut spend` totals it, and
`build` reports the run's spend. Stock images, Edge voices and all of the editing
commands are free.

## Repo layout

```
.claude-plugin/marketplace.json    marketplace entry
plugins/promptcut/
  .claude-plugin/plugin.json       plugin manifest
  skills/video-toolbox/            how Claude drives the toolbox
  skills/capcut-draft/             CapCut draft spec and effect lookup
  commands/                        /promptcut:video, :shorts, :edit, :capcut, :setup
  scripts/promptcut.py             CLI entry point
  scripts/pc_*.py                  plan, media, render, subs, stock, capcut, edit
  templates/                       starter storyboards
```

## Known limits

- CapCut renders its own exports; PromptCut writes the project, it doesn't press
  Export. Restart CapCut to see a new draft, and don't write to an open one.
- CapCut transitions eat time from both neighbouring clips, which drifts video
  against a separate voiceover track. `capcut-from-plan` leaves them off unless
  you pass `--transitions`.
- Reframing crops to centre. There's no face tracking.
- Stock search needs internet; behind a strict egress allowlist the providers
  will simply fail to answer.

## Standalone use

The CLI works without Claude:

```
python plugins/promptcut/scripts/promptcut.py plan-new --out plan.json --aspect 9:16
python plugins/promptcut/scripts/promptcut.py build --plan plan.json --fake
```

MIT licensed. [Русская версия README](README.ru.md).
