---
name: video-toolbox
description: Build and edit video from a prompt - storyboard, AI images or stock footage, TTS voiceover, Ken Burns motion, music with ducking, subtitles, ffmpeg render, CapCut draft export. Use for any request about making, cutting, voicing, subtitling, reframing or assembling video and audio files.
---

# PromptCut video toolbox

A CLI toolbox, not a fixed pipeline. The person says what they want; you pick the
commands. Every command prints JSON on stdout and progress on stderr.

Run everything as:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/promptcut.py" <command> [flags]
```

Use `python` on Windows, `python3` on macOS/Linux. Add `--help` to any command.
Reply to the person in their own language.

## Before the first job in a session

Run `doctor`. It reports ffmpeg, the OpenRouter key, pycapcut, the CapCut drafts
folder and stock keys, plus a `problems` list. Fix only what the job needs:
a talking-head cut needs ffmpeg alone, image generation needs the key.

## Two modes of work

**Single action** — "cut 3 seconds", "add subtitles", "make it vertical",
"drop the pauses", "put music under it". Call the one command that does it and
report the output path. Do not build a plan for this.

**Whole video from an idea or a script** — write a `plan.json` storyboard, then
`build`. This is the mode for "make me a video about X", faceless shorts,
narrated explainers, ad reads.

## Full video: the loop

1. Turn the idea into shots. One shot = one spoken sentence + one picture.
   8-14 words per shot for shorts, up to 25 for long form. Write the `vo` in the
   person's language; write `image_prompt` in **English** (image models are much
   better at it) and keep a consistent `image.style` across shots.
2. Write `plan.json` (schema below). `plan-new --out plan.json` gives a starter.
3. `build --plan plan.json --fake` — free dry run with stub images and beeped
   voice. It proves the timing, subtitle splits and length. Show the person the
   duration and the shot list, not the stub video, unless they ask.
4. `build --plan plan.json` for real. Media is cached by content hash, so
   re-running after a text edit only pays for what changed.
5. Report the mp4 path, the duration and `spend_usd`. Offer the CapCut draft
   (`capcut-from-plan`) if they may want to tweak by hand.

Iterating: edit `plan.json` and run `build` again. Add `--force` only to
deliberately re-pay for media. `--stage render` re-renders from cached media.

## plan.json

```json
{
  "project": "name-for-output-files",
  "aspect": "9:16",
  "fps": 30,
  "voice":  {"provider": "openrouter", "model": null, "voice": "alloy", "speed": 1.0,
             "instructions": "calm documentary narrator"},
  "image":  {"model": null, "resolution": "2K",
             "style": "cinematic photo, 35mm, soft rim light, muted palette"},
  "music":  {"file": "bed.mp3", "gain_db": -21, "duck": true, "fade": 2.0},
  "subtitles": {"enabled": true, "font": "Arial", "size": null, "max_chars": 30,
                "position": "bottom", "uppercase": false, "outline": 3,
                "color": "FFFFFF", "outline_color": "000000", "bold": true},
  "timing": {"lead": 0.15, "tail": 0.45, "transition": "dissolve",
             "transition_duration": 0.45, "motion_amp": 0.12, "min_shot": 2.0},
  "shots": [
    {"id": "s01",
     "vo": "Sentence that gets voiced and subtitled.",
     "image_prompt": "wide shot of a foggy harbour at dawn",
     "image": null,
     "motion": "zoom_in",
     "transition": "dissolve",
     "transition_duration": 0.5,
     "min_duration": null,
     "overlay": "TITLE ON TOP",
     "subtitle": null,
     "sfx": null,
     "seed": null}
  ]
}
```

- `aspect`: `9:16` `16:9` `1:1` `4:5` `4:3` `21:9`, or set `width`/`height`.
- `motion`: `zoom_in` `zoom_out` `pan_left` `pan_right` `pan_up` `pan_down`
  `still` `auto` (rotates through four looks).
- `transition`: any ffmpeg xfade name - `dissolve` `fade` `wipeleft` `slideup`
  `circleopen` `pixelize` `radial` `fadeblack` `zoomin` ... - or `cut`.
- `image`: a local file skips generation for that shot. `subtitle`: text to show
  instead of `vo`, or `false` to show none. `overlay`: big title over the shot.
- Shot length is voice length + `lead` + `tail`, floored by `min_duration` /
  `min_shot`. Silent shots use `min_duration`.
- `voice.provider`: `openrouter` (paid, best), `edge` (free, needs
  `pip install edge-tts`, Russian voices like `ru-RU-DmitryNeural`), `fake`.

## Commands

Setup and info

| command | what it does |
|---|---|
| `doctor` | environment, keys, CapCut folder, problems |
| `config --set key=value` | image_model, tts_model, tts_voice, edge_voice, capcut_drafts_dir, ffmpeg |
| `keys --set pexels=... freesound=...` | stock provider keys |
| `models --kind image\|audio\|text` | live OpenRouter model list with prices |
| `spend` | what the APIs cost so far |
| `probe --file x.mp4` | duration, size, fps, codecs, audio presence |

Making media

| command | what it does |
|---|---|
| `tts --text "..." --out vo.mp3 [--provider edge --voice ... --speed 1.05]` | voiceover, returns duration |
| `image-gen --prompt "..." --out img.png [--aspect 9:16 --resolution 2K --seed 7]` | generate an image |
| `image-find --query "..." --out img.jpg [--provider pexels --orientation portrait]` | stock photo; `--list` to only search |
| `video-find --query "..." --out b.mp4` | stock b-roll (needs pexels or pixabay key) |
| `audio-find --query "lofi calm" --out bed.mp3` | music and sfx (freesound, jamendo, openverse) |
| `transcribe --file a.mp3 --srt out.srt [--granularity word]` | speech to text with timings |

Editing

| command | what it does |
|---|---|
| `cut -i in.mp4 --out o.mp4 --start 3 --end 12 [--copy]` | trim |
| `concat --files a.mp4 b.mp4 --out o.mp4 [--xfade dissolve --xfade-dur .5]` | join |
| `kenburns --image p.png --out c.mp4 --dur 4 --motion pan_left --size 1080x1920` | still to moving clip |
| `overlay --base v.mp4 --over logo.png --out o.mp4 --at 1 --dur 4 --x 40 --y 40 --scale .3 --opacity .8 --fade .4` | logo, PiP, inserts |
| `text -i v.mp4 --out o.mp4 --text "..." --start 1 --dur 3 --position top` | burned label |
| `subs-burn --video v.mp4 --subs s.srt --out o.mp4 [--force-style "Fontsize=22"]` | burn subtitles |
| `subs-make --plan plan.json` | .srt and .ass from a plan |
| `mix --video v.mp4 --out o.mp4 --music bed.mp3 --music-db -21 [--no-duck] [--sfx '[{"file":"w.mp3","at":2.5}]']` | music bed, ducking, sfx, loudness |
| `speed -i v.mp4 --out o.mp4 --factor 1.25` | speed, pitch preserved |
| `reframe -i v.mp4 --out o.mp4 --aspect 9:16 --mode blur\|crop\|pad` | change aspect |
| `silence-cut -i v.mp4 --out o.mp4 [--noise-db -32 --min-silence .45 --pad .08]` | drop pauses in a talking head |
| `scenes -i v.mp4 [--threshold .35]` | scene cut timestamps |
| `thumb -i v.mp4 --out t.jpg --at 4` | grab a frame |
| `audio-extract` / `normalize` | rip audio to mp3 / loudness to -16 LUFS |

Assembly and handoff

| command | what it does |
|---|---|
| `plan-new --out plan.json --aspect 9:16` | starter storyboard |
| `plan-check --file plan.json` | validate before spending |
| `build --plan plan.json [--out o.mp4] [--fake] [--stage media\|render\|all] [--no-subs] [--force] [--crf 20] [--preset medium]` | media, timeline, render |
| `capcut-from-plan --plan plan.json [--use-clips] [--transitions] [--name X]` | open the same storyboard in CapCut |
| `capcut-build --spec spec.json` | arbitrary CapCut draft, see the capcut-draft skill |
| `capcut-effects --type transition --search glitch` | find effect names |
| `capcut-drafts` | where CapCut keeps drafts |

## Recipes

**Faceless short from a topic.** Write 6-10 shots, `aspect 9:16`,
`subtitles.max_chars 26-30`, `uppercase true` reads well; `audio-find` a bed at
`-23 dB`; `build --fake` first; then `build`.

**Narrated video from a script the person pasted.** Split their text into shots
at sentence boundaries, keep their wording exactly - it is their voice, do not
rewrite unless asked. One `image_prompt` per sentence.

**Stock instead of generated images.** Put `image-find` results into each shot's
`image` field, or set the whole plan to `image.model: null` and pre-fetch. Stock
is free with a Pexels key and looks less "AI".

**Talking head cleanup.** `silence-cut`, then `transcribe --srt`, then
`subs-burn`, then `mix --music ... --music-db -26`. Offer `reframe --mode blur`
for a vertical cut.

**Long video to shorts.** `transcribe --granularity word`, pick the strongest
30-60s stretches from the transcript, `cut` each, `reframe --aspect 9:16`,
`subs-burn`.

**Hand-off for manual polish.** `build` for the mp4, then `capcut-from-plan` so
they can retime and restyle in CapCut with the same media.

## Money and honesty

Generated images and OpenRouter TTS cost real money per shot. Say the shot count
before a large run, prefer `--fake` for structure checks, and report `spend_usd`
after. Never silently re-generate cached media.

Do not claim a video is rendered before the command returns a path. If a command
fails, read the ffmpeg tail it printed - it names the bad filter or file.
