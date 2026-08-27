# PromptCut

A Claude Code / Cowork plugin that turns a prompt into a finished video — and a
toolbox for every smaller step on the way there.

You say "make me a 40-second vertical video about the Voyager probes, calm
narrator, subtitles". Claude writes the storyboard, generates the voiceover,
generates or finds a picture for every line, animates the stills, lays a music
bed under the narration, burns the subtitles and renders the mp4. If you'd
rather finish by hand, it writes a CapCut, Premiere Pro, DaVinci Resolve or
VEGAS Pro project instead, with every clip, motion keyframe, subtitle and effect
already on the timeline.

It is not a single pipeline you have to feed. It is ~30 small commands. "Cut the
pauses out of this recording", "make this 16:9 clip vertical", "put this music
under it at -21 dB with ducking", "voice this paragraph" — each is one command,
and Claude picks it.

## Install

1. Add the plugin in Claude Code — from a local clone:

   ```
   /plugin marketplace add C:\path\to\promptcut
   /plugin install promptcut@promptcut
   ```

   or straight from GitHub:

   ```
   /plugin marketplace add Belagum/promptcut
   ```

2. Run `/promptcut:setup`. It installs what it can on its own — pillow, yt-dlp,
   edge-tts, pycapcut via pip, and ffmpeg via winget/brew — then tells you what
   only you can do (keys).

3. Give it an OpenRouter key (needed for generated images, TTS and `ask`;
   everything else works without it). Get one at openrouter.ai/settings/keys,
   top up a few dollars, then either:

   ```
   python plugins/promptcut/scripts/promptcut.py config --set openrouter_api_key=sk-or-...
   ```

   (works immediately), or `setx OPENROUTER_API_KEY sk-or-...` and open a new
   terminal.

Python 3.10+ and ffmpeg are the only hard requirements. Everything else buys you
extra capabilities. If you'd rather install by hand:

```
pip install pycapcut edge-tts pillow yt-dlp
winget install Gyan.FFmpeg          # Windows; brew install ffmpeg on macOS
```

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
gpt-image, whatever your key can reach), edited or combined from your photos
(`image-edit`), or pulled from stock: Pexels, Unsplash, Pixabay with a free key;
Openverse, Wikimedia Commons and archive.org with no key at all. Music and sound
effects come from Freesound, Jamendo, archive.org or Openverse — and `media-dl`
(yt-dlp) searches the wider web and downloads any clip, or just the 2.5 seconds
of it you need.

**Editing.** Trim, join with crossfades, overlay logos and PiP, burn text and
subtitles, mix a ducked music bed, change speed with pitch kept, reframe to 9:16
with blurred bars, strip pauses out of a talking head, detect scene cuts, grab
thumbnails, normalise loudness to −16 LUFS.

**Callouts and cards.** `annotate` draws circles, arrows, boxes and labels on a
photo or on video — with timing and blinking. `kenburns --focus` pushes into an
exact point of a still, eased. `card` renders exact-text typography (image
models mangle text): per-letter numbering, colored substrings, morpheme
dividers — the "here's the proof on screen" shot.

**Eyes and ears.** Claude can't play media, so the toolbox gives it senses:
`frames` makes a timestamped contact sheet of any video, `waveform` draws the
waveform, spectrogram and loudness of any audio, and `ask` sends an image or an
mp3 to any multimodal OpenRouter model — "what does this track sound like,
where's the drop?" — before a cent lands on the timeline.

**CapCut.** Writes a real CapCut project: multiple video, audio, text, effect and
filter tracks, plus transitions (1137 of them), scene effects (1583), filters
(454), intro/outro animations, masks, keyframes on position/scale/rotation/alpha/
volume, styled text with animations, and imported SRT subtitles. Effect names are
searchable, so Claude looks them up instead of hallucinating them.

**Premiere Pro, DaVinci Resolve, VEGAS Pro.** The same storyboard as an editable
project: FCP7 XML for Premiere and Resolve, a generated C# script (plus xml) for
VEGAS. Stills keep their Ken Burns as scale/position keyframes (pan/crop in
VEGAS), voiceover, sfx and music sit on their own tracks with the ducking curve
as level keyframes, overlay titles become PNG cards, every shot gets a marker,
and the subtitles travel as an SRT the editor imports natively. A hand-written
`timeline.json` goes the same way for cuts that never had a plan, and the
`nle-export` skill doubles as the how-to Claude consults when you ask how to
import, relink or restyle in those editors.

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
  skills/nle-export/               Premiere / Resolve / VEGAS export and editor how-to
  commands/                        /promptcut:video, :shorts, :edit, :capcut, :premiere, :resolve, :vegas, :setup
  scripts/promptcut.py             CLI entry point
  scripts/pc_*.py                  plan, media, render, subs, stock, capcut, edit, timeline, xmeml, vegas, nle
  templates/                       starter storyboards
tests/                             unittest suite, VEGAS API stub, xmeml calibration kit
```

## Known limits

- CapCut renders its own exports; PromptCut writes the project, it doesn't press
  Export. Restart CapCut to see a new draft, and don't write to an open one.
- CapCut transitions eat time from both neighbouring clips, which drifts video
  against a separate voiceover track. `capcut-from-plan` leaves them off unless
  you pass `--transitions`.
- Premiere / Resolve / VEGAS projects reference media by absolute path inside
  `<plan>_build/`; move the folder and you relink. The sizing units of each
  editor are set per profile and still want one calibration pass on a real
  install (`tests/calibrate.py`); `--use-clips` sidesteps it by placing the
  rendered clips.
- Those editors get clips, motion, audio, titles, markers and subtitles;
  CapCut-only extras (masks, filters, effects, stickers) don't travel.
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
