---
name: nle-export
description: Hand a PromptCut storyboard or a hand-written timeline to Adobe Premiere Pro, DaVinci Resolve or VEGAS Pro as an editable project - clips with Ken Burns keyframes, voiceover, ducked music, sfx, titles, markers and SRT subtitles. Also the knowledge base for advising the person about those editors - importing, relinking media, subtitles, sizing problems - even when no command is run. Use when the person names Premiere, Resolve, VEGAS, FCP7 XML, "open it in my editor", or asks how the export works.
---

# Editor hand-off: Premiere Pro, DaVinci Resolve, VEGAS Pro

PromptCut renders the mp4 itself; this skill instead writes a project the person
finishes in their own editor. One command, three targets, one shared model:

```
plan.json ──build──▶ media + timing ──nle-from-plan──▶ export/timeline.json ──▶ .premiere.xml
                                                                             ├─▶ .resolve.xml
                                                                             └─▶ .vegas.cs + .vegas.xml
```

Everything lands in `<plan>_build/export/` (or `--out DIR`): the xml/cs files,
`timeline.json` (the neutral model, editable by hand), `subs.srt`, `overlays/*.png`
(title cards). Media is referenced by absolute path from `<plan>_build/img|audio`,
nothing is copied - keep that folder where it is or relink after moving.

## Commands

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/promptcut.py" nle-from-plan --plan plan.json --target premiere|resolve|vegas|all
    [--use-clips] [--no-transitions] [--name X] [--out DIR] [--run] [--timeline-only]
python "${CLAUDE_PLUGIN_ROOT}/scripts/promptcut.py" nle-build --spec timeline.json --target ... [--out DIR] [--run]
```

- `nle-from-plan` needs the media from a previous `build` (the real one or
  `--fake`); it never generates media itself. Without a build it reports gaps.
- `--use-clips` places the rendered per-shot clips (`clips/*.mp4`, motion baked in)
  instead of stills with keyframes. Exact same look as the mp4, nothing to
  calibrate, but the motion is no longer editable. Requires a finished `build`.
- `--no-transitions` gives hard cuts. Default: the plan's transitions become
  Cross Dissolves (any xfade name maps to a dissolve).
- `--run` (VEGAS only) starts VEGAS Pro with the generated script; the project
  builds itself and is saved as `<name>.veg` next to the script.
- `--target all` writes every editor's files at once - cheap, do it when unsure
  which editor the person will open.
- `doctor` lists installed editors under `nle`. `config --set vegas_exe=...` when
  VEGAS is not auto-detected for `--run`.

The JSON result carries `next_steps` per target: read them to the person in their
language instead of inventing menu paths.

## What is carried

| element | Premiere / Resolve (xml) | VEGAS (script) |
|---|---|---|
| stills, footage, rendered clips, in/out, speed | yes (speed via Time Remap) | yes (Playback Rate 0.25-4x) |
| Ken Burns: zoom, pan, focus, ease | Motion scale + position keyframes | Pan/Crop keyframes |
| transitions | Cross Dissolve, start-aligned on the cut | overlapping events -> automatic crossfade |
| voiceover, sfx | own tracks, exact placement | own tracks |
| music, gain, fades, ducking | Audio Levels keyframes (-12 dB under speech) | event gain + volume envelope |
| `overlay` titles | PNG with alpha on the Titles track, 0.2 s fades | PNG events with fades |
| subtitles | `subs.srt` next to the project, imported by the editor | same, Insert > Subtitles From File |
| markers per shot | sequence markers with the shot id and first words | project markers |
| masks, filters, effects, stickers, text animations | no (CapCut only) | no |

Titles are rasterised on purpose: FCP7 XML text generators do not survive import
into Premiere or Resolve as editable text, and VEGAS's text generator takes RTF
through OFX - a PNG is what actually opens everywhere. Subtitles stay as SRT
because every editor's own caption tool beats burned text when the person wants
to restyle.

## Importing, step by step

**Premiere Pro.** File > Import, choose `<name>.premiere.xml`. A bin with the
media and a sequence appear; open the sequence. Stills carry Motion keyframes
(Effect Controls > Motion), music has Audio Levels keyframes. Subtitles:
File > Import `subs.srt`, drag it from the Project panel onto the sequence above
V2 - Premiere turns it into a caption track (Text panel to restyle; Graphics >
Upgrade to Source Graphic is not needed). Offline media: select the clips, right
click > Link Media, point at `plan_build/img` and `plan_build/audio`; "Relink
others automatically" finds the rest. Premiere imports stereo files as two linked
mono channels here; that is how FCP7 XML describes audio, the sound is unchanged.

**DaVinci Resolve.** Open or create a project, File > Import > Timeline > Import
AAF, EDL, XML..., choose `<name>.resolve.xml`. In the Load XML dialog keep
"Automatically set project settings", "Automatically import source clips into
media pool" and **"Use sizing information"** checked - the last one is what
brings the zoom/position keyframes across. Subtitles: File > Import > Subtitle,
pick `subs.srt`, then drag it from the media pool onto the timeline; Resolve
creates a subtitle track (Inspector > Subtitle to restyle). Missing media: right
click the clip > Relink Selected Clips, or Media Pool > Relink. Resolve's Zoom 1.0
means "fit to frame", so the xml written for Resolve expresses scale relative to
fit - never feed the `.premiere.xml` to Resolve or vice versa.

**VEGAS Pro.** Start VEGAS with an empty project (File > New), Tools > Scripting >
Run Script..., choose `<name>.vegas.cs`. VEGAS compiles it on the fly (C#, no
extra references), builds tracks, events, pan/crop keyframes, the music envelope
and markers, then saves `<name>.veg` next to the script - reopen that later
instead of rerunning the script. `--run` does the same from the command line
(`vegas.exe /SCRIPT file.cs`). If a security prompt asks whether to run the
script, the source is plain text, the person can read it. Subtitles: Insert >
Subtitles From File..., choose `subs.srt` (VEGAS 16 and newer; it becomes one
text event per cue). Transitions rely on Options > Automatic Crossfades being on
(default). Without scripting, File > Import > Final Cut Pro 7/DaVinci Resolve
with `<name>.vegas.xml` gives cuts and audio but loses pan/crop and ducking.

## timeline.json - the hand-written route

Anything not born from a plan - a montage cut with `/promptcut:edit`, a repost
with a new bed, a beat-synced slideshow - is a timeline written directly:

```json
{
  "name": "montage", "size": [1080, 1920], "fps": 30,
  "tracks": [
    {"type": "video", "name": "Shots", "clips": [
      {"id": "a", "file": "photo.jpg", "start": 0, "duration": 4,
       "motion": {"kind": "zoom_in", "amp": 0.2, "focus": [0.6, 0.4], "ease": true},
       "transition": {"type": "dissolve", "duration": 0.5}},
      {"id": "b", "file": "broll.mp4", "start": 4, "duration": 3, "source_in": 12.5, "speed": 1.5}]},
    {"type": "video", "name": "Titles", "clips": [
      {"file": "title.png", "start": 0.3, "duration": 2.5,
       "opacity": [[0, 0], [0.2, 1], [2.3, 1], [2.5, 0]]}]},
    {"type": "audio", "name": "VO", "clips": [
      {"file": "vo.mp3", "start": 0.2, "duration": 6.5}]},
    {"type": "audio", "name": "Music", "clips": [
      {"file": "bed.mp3", "start": 0, "duration": 7, "gain_db": -21, "fade_in": 1.2, "fade_out": 2,
       "levels": [[0, 0], [0.2, -12], [6.7, -12], [7, 0]]}]}
  ],
  "markers": [{"at": 0, "name": "a", "note": "opening"}],
  "subtitles": {"srt": "subs.srt"}
}
```

Rules: seconds everywhere, dB for `gain_db` and `levels` (relative to the clip
start), `opacity` 0..1, `motion.focus` in 0..1 of the source image. Clips on one
track must not overlap; a clip's `transition` overlaps the *next* clip by
`duration` (the outgoing clip needs that much extra material - stills always
have it, footage only if it is long enough). `kind`, `media` (size, duration,
channels) are probed with ffprobe, do not write them. `motion.kind`: `zoom_in`
`zoom_out` `pan_left` `pan_right` `pan_up` `pan_down` `still`; final zoom is
`1 + amp`. Any picture or footage is cover-cropped to the frame, like the
renderer does; a `Titles` track PNG of frame size is placed 1:1.

`card --transparent` and `annotate` make good `Titles` clips; `subs-make --plan`
or `transcribe --srt` make the `subs.srt`.

## How it works, for explaining it

*FCP7 XML (`xmeml` v5)* is the 2009 Final Cut Pro interchange format that
Premiere, Resolve and VEGAS still read. Times are integer frames at the sequence
rate; a `clipitem` has `start`/`end` on the timeline and `in`/`out` in the
source; a still is a one-hour "file" so any `out` fits. A transition sits between
two clipitems, whose touching `end`/`start` are written as `-1` (FCP's
convention), and the outgoing clip's `out` is extended by the transition length -
exactly the way the renderer overlaps clips, so the voice never drifts. Ken
Burns becomes Basic Motion keyframes: scale in percent (Premiere: of native
pixels; Resolve: of the fitted image) and center as a fraction of the frame;
each keyframe `when` is a source frame between `in` and `out`. Music is an Audio
Levels filter with linear gain keyframes (1.0 = 0 dB); the ducking curve drops
12 dB 0.15 s before speech and recovers 0.4 s after. Stereo sources are two
linked clipitems on paired tracks, mono is one.

*The VEGAS script* is straight-line C# calling a few helpers: it sets the
project size and frame rate, adds tracks top-down (Titles above Shots, then VO,
Music, SFX), creates one event per clip with a take, offset and playback rate,
turns Ken Burns into Pan/Crop keyframes (bounds rectangle in source pixels, the
same window the renderer's zoompan uses), applies event gain, a Volume envelope
for ducking, markers, and saves the `.veg`.

*The motion math* is shared by ffmpeg, CapCut and every exporter: the source is
cover-cropped to the frame, a window of `1/zoom` of that crop slides toward the
focus (clamped so it never leaves the picture), pans travel edge to edge at the
final zoom, `ease` samples six smoothstep points instead of two.

## Troubleshooting

- **Media offline after import** - the project points at `plan_build/...`
  absolute paths. Relink (Premiere: Link Media; Resolve: Relink Selected Clips;
  VEGAS: right click > Replace) or re-export after moving the folder.
- **A still is the wrong size or off-centre** in Premiere or Resolve - the
  sizing profile for that editor needs calibration on the person's version. Ask
  for a screenshot, or run `python tests/calibrate.py --out calib --target X`
  and have them import `calib.X.xml`: it shows a labelled grid whose visible cells
  tell exactly how scale and position were interpreted. Until fixed, `--use-clips`
  is the safe route.
- **Footage plays black at the end** - the renderer loops short footage, editors
  do not; the clip is trimmed to the file and the export warns about it. Pick
  longer b-roll or `--use-clips`.
- **Speed above 4x or below 0.25x** - VEGAS clamps it; Premiere/Resolve take any.
- **Subtitles overlap or flash** - `subs.srt` cues never overlap (each ends at
  the next start); if the editor merges them, check its caption import frame rate.
- **VEGAS says the script failed to compile** - the script is C# 5 and needs no
  references; read the error line, it names the API member. Report it with the
  VEGAS version so the template can be fixed.
- **Nothing happens on `--run`** - `doctor` shows `nle.vegas`; if null, set
  `config --set vegas_exe="C:\Program Files\VEGAS\VEGAS Pro 22.0\vegas220.exe"`.
- **Resolve free vs Studio** - both import the xml and the srt; only external
  scripting is Studio-only, which is why there is no auto-import for Resolve.

## Recipes

**Assembled video, hand polish in their editor.** `build` for approval, then
`nle-from-plan --target <their editor>`; read `next_steps` back to them; mention
`--use-clips` if they care about pixel-exact motion more than editability.

**Unknown editor.** `--target all`, hand over the folder.

**Repost or montage without a plan.** Write `timeline.json` (stock clips,
`card` PNGs, `transcribe --srt`), `nle-build --spec timeline.json --target ...`.

**Same storyboard everywhere.** `capcut-from-plan` for CapCut, `nle-from-plan
--target all` for the rest; all four read the same `plan_build` media.

**Just a question.** "How do I get this into Resolve?", "will the zoom be
editable?", "why is the music quieter under the voice?" - answer from this file,
no command needed.
