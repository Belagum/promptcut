---
name: video-toolbox
description: Build and edit video from a prompt - storyboard, AI images or stock footage, TTS voiceover, Ken Burns motion with focus zoom, callout annotations, typography cards, music with ducking, subtitles, ffmpeg render, CapCut draft export, Premiere Pro / DaVinci Resolve / VEGAS Pro project export. Also finds and downloads photos, music and sfx, and can look at frames and listen to audio to verify results. Use for any request about making, cutting, voicing, subtitling, reframing or assembling video and audio files.
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
folder, installed editors (`nle`) and stock keys, plus a `problems` list. Fix only what the job needs:
a talking-head cut needs ffmpeg alone, image generation needs the key. If the
problems are missing packages or ffmpeg, run `setup` - it installs them itself;
only keys need the person.

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
   (`capcut-from-plan`) or an editor project (`nle-from-plan --target
   premiere|resolve|vegas`, see the nle-export skill) if they may want to tweak
   by hand.

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
     "video": null, "video_in": 0.0, "video_speed": 1.0,
     "motion": "zoom_in",
     "focus": [0.62, 0.41], "ease": true, "motion_amp": null,
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
- `focus`: `[x, y]` in 0..1 on the **source image** - zoom_in/zoom_out drive
  toward that point (coords are remapped to the crop automatically). `ease`
  smooths the motion in/out. `motion_amp` per shot: default 0.12 is subtle,
  1.0-1.5 is a dramatic push-in (final zoom = 1 + amp). A focus near the edge
  of a wide image in a tall frame pins to the frame edge - that's geometry.
- `transition`: any ffmpeg xfade name - `dissolve` `fade` `wipeleft` `slideup`
  `circleopen` `pixelize` `radial` `fadeblack` `zoomin` ... - or `cut`.
- `image`: a local file skips generation for that shot. `video`: use footage
  instead of a still - it is cropped to frame, sped up by `video_speed`, started
  at `video_in`, and looped if it is shorter than the shot. `subtitle`: text to
  show instead of `vo`, or `false` to show none. `overlay`: big title over the
  shot.
- Shot length is voice length + `lead` + `tail`, floored by `min_duration` /
  `min_shot`. Silent shots use `min_duration`.
- `voice.provider`: `openrouter` (paid, best), `edge` (free, needs
  `pip install edge-tts`, Russian voices like `ru-RU-DmitryNeural`), `fake`.
- **Write every number as words in `vo`** («сто двадцать девять», not «129») -
  TTS models misread digits, dates and codes. Digits are fine in `subtitle`,
  `overlay` and cards. Mark ambiguous Russian stress with U+0301 after the
  vowel («он стои́т за») - edge voices honor it.
- `sentence`: give several consecutive shots the same sentence id and put in
  each `vo` its word-slice («Он стоял не у молока.» → shots `у молока` /
  `и не у крупы`...). The whole sentence is voiced as ONE natural tts call, and
  the cuts land exactly on word boundaries (edge word marks; for openrouter the
  audio is whisper-aligned and verified verbatim, drifting takes are retried).
  Use this whenever the person wants a picture per word - never voice single
  words as separate shots, the pauses between them sound robotic. Member shots
  ignore `min_shot` (their length = their words), so keep 1-4 words per member.

## Commands

Setup and info

| command | what it does |
|---|---|
| `doctor` | environment, keys, CapCut folder, problems |
| `setup [--upgrade]` | auto-install missing pip deps and ffmpeg; `--upgrade` refreshes yt-dlp etc |
| `config --set key=value` | image_model, tts_model, tts_voice, edge_voice, capcut_drafts_dir, vegas_exe, ffmpeg |
| `keys --set pexels=... freesound=...` | stock provider keys |
| `models --kind image\|audio\|text` | live OpenRouter model list with prices |
| `spend` | what the APIs cost so far |
| `probe --file x.mp4` | duration, size, fps, codecs, audio presence |

Making media

| command | what it does |
|---|---|
| `tts --text "..." --out vo.mp3 [--provider edge --voice ... --speed 1.05]` | voiceover, returns duration |
| `image-gen --prompt "..." --out img.png [--aspect 9:16 --resolution 2K --seed 7]` | generate an image |
| `image-edit --prompt "..." --image a.jpg [--image b.jpg] --out o.png` | edit/combine photos with a prompt (paid, ~$0.03) |
| `image-find --query "..." --out img.jpg [--provider pexels --orientation portrait]` | stock photo; `--list` to only search |
| `video-find --query "..." --out b.mp4` | stock b-roll (needs pexels or pixabay key) |
| `audio-find --query "lofi calm" --out bed.mp3` | music and sfx (freesound, jamendo, archive, openverse) |
| `media-dl --search "vine boom sound effect"` | find clips/music/sfx on the web (yt-dlp) |
| `media-dl --url <url> --out boom.mp3 [--start 0 --end 2.5]` | download it, whole or a slice; `.mp3` out = audio only |
| `card --text "Ч\|ИП\|СЫ" --out c.png --letters --highlight ИП [--title ... --sub ... --transparent]` | exact-text typography card: `\|` = group divider, `--letters` numbers each letter (image models mangle text - use this for words, counts, formulas) |
| `annotate -i in.jpg\|in.mp4 --out o --spec shapes.json` | circles, arrows, boxes, labels; on video with `at`/`dur`/`blink` |
| `transcribe --file a.mp3 --srt out.srt [--granularity word]` | speech to text with timings |

`annotate` shapes (coords 0..1 of frame, write the JSON to a file to dodge
shell quoting): `[{"type":"circle","x":.68,"y":.55,"r":.09,"color":"#FF2D2D","stroke":10},
{"type":"arrow","x1":.35,"y1":.30,"x2":.61,"y2":.49},
{"type":"text","x":.3,"y":.24,"text":"129 ₽","size":.07},
{"type":"box","x":.3,"y":.4,"w":.4,"h":.2,"at":1.0,"dur":2.0,"blink":0.4}]`.
`blink: 0.4` = 0.4s on / 0.4s off. On images, `at/dur/blink` are ignored.

Looking and listening (you cannot play media - these are your eyes and ears)

| command | what it does |
|---|---|
| `frames -i v.mp4 --out sheet.jpg [-n 12 --cols 4]` | contact sheet with timestamps - Read it to check a cut |
| `waveform -i a.mp3 --out wf.png` | waveform + spectrogram + peak/mean dB - Read it to see beats, silence, clipping |
| `ask --prompt "tempo, mood, where does the beat drop?" --file bed.mp3` | a multimodal model listens and answers (paid, cents) |
| `ask --prompt "bounding box of the price tag, JSON [x0,y0,x1,y1] 0..1" --file ph.jpg --json` | precise object coords for focus/annotate |

`ask` is for perception, not text - you write scripts and prompts yourself.
Attach png/jpg/webp/gif or mp3/wav (m4a/ogg auto-convert). For video, make a
contact sheet first. `--model` overrides `chat_model` (default gemini-2.5-flash).

Editing

| command | what it does |
|---|---|
| `cut -i in.mp4 --out o.mp4 --start 3 --end 12 [--copy]` | trim |
| `concat --files a.mp4 b.mp4 --out o.mp4 [--xfade dissolve --xfade-dur .5]` | join |
| `kenburns --image p.png --out c.mp4 --dur 4 --motion zoom_in --focus 0.62,0.41 --amp 1.4 --ease --size 1080x1920` | still to moving clip; `--focus` zooms into that point |
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
| `nle-from-plan --plan plan.json --target premiere\|resolve\|vegas\|all [--use-clips] [--run]` | Premiere / Resolve / VEGAS project from the storyboard, see the nle-export skill |
| `nle-build --spec timeline.json --target ...` | editor project from a hand-written timeline |

## Recipes

**Faceless short from a topic.** Write 6-10 shots, `aspect 9:16`,
`subtitles.max_chars 26-30`, `uppercase true` reads well; `audio-find` a bed at
`-23 dB`; `build --fake` first; then `build`.

**Narrated video from a script the person pasted.** Split their text into shots
at sentence boundaries, keep their wording exactly - it is their voice, do not
rewrite unless asked. One `image_prompt` per sentence.

**B-roll instead of stills.** `video-find --query "..." --out b1.mp4` per shot,
then set `"video": "b1.mp4"` on those shots. Mix stills and footage freely; the
timing model does not care which a shot uses.

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
they can retime and restyle in CapCut with the same media. For Premiere, Resolve
or VEGAS: `nle-from-plan --target ...` - same media, editable motion keyframes,
SRT subtitles; the result's `next_steps` tell how to import.

**Dramatic zoom + callout on a photo.** Read the photo yourself (or
`ask ... --json` for exact coords), `annotate` a circle/arrow onto the still,
`kenburns --focus x,y --amp 1.2 --ease` toward the same point, drop a one-shot
sfx at the reveal (`media-dl --search "vine boom sound effect"`, download,
`mix --sfx`). For a blinking callout, `annotate` the rendered clip with
`at/dur/blink` instead of the still.

**Proof cards for claims about words and numbers.** Whenever the voiceover
names a word, a letter count or a formula, put the exact thing on screen with
`card` - `--letters` numbers the letters, `--highlight` colors the key part,
`|` splits morphemes. Never image-gen text, especially Cyrillic. Make the card
the same aspect as the video, or `--transparent` and `overlay` it.

**Check your own result.** After a render: `frames` on the mp4 and Read the
sheet (cuts, subs, callout placement); `waveform` on the mix (music present,
ducking visible, no clipping); `ask --file` on a downloaded track before paying
it into the timeline. Fix and re-render before reporting done.

## Money and honesty

Generated images, `image-edit`, OpenRouter TTS and `ask` cost real money per
call (`ask` and `image-edit` are cents; images and TTS add up per shot). Say the
shot count before a large run, prefer `--fake` for structure checks, and report
`spend_usd` after. Never silently re-generate cached media. `card`, `annotate`,
`frames`, `waveform`, `media-dl` and stock search are free.

Do not claim a video is rendered before the command returns a path. If a command
fails, read the ffmpeg tail it printed - it names the bad filter or file.
