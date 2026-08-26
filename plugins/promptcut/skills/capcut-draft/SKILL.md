---
name: capcut-draft
description: Build a CapCut project (draft) programmatically - tracks, clips, transitions, animations, filters, masks, video and audio effects, keyframes, styled text and imported SRT subtitles. Use when the person wants the edit inside CapCut instead of a finished mp4, or wants to tweak an assembled video by hand.
---

# CapCut drafts

PromptCut writes a real CapCut project folder. The person opens CapCut, sees the
timeline with every clip, effect and subtitle in place, tweaks it, and exports
from CapCut. Nothing is rendered here.

Requirements: `pip install pycapcut`, CapCut desktop, and the drafts folder.
Run `capcut-drafts` to find it; if it cannot be found, ask the person for
CapCut → Settings → Draft location, then
`config --set capcut_drafts_dir="<path>"`.

CapCut must be **restarted** to notice a new draft. Do not write to a draft that
is open. Only unencrypted drafts can be read back; newer CapCut versions encrypt
them, which affects loading templates, not creating drafts.

## Two ways in

From an existing storyboard:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/promptcut.py" capcut-from-plan --plan plan.json
```

Stills + voiceover + music + sfx + SRT subtitles, one track each. `--use-clips`
puts the already rendered motion clips on the timeline instead of stills.
`--transitions` adds CapCut transitions - they eat time from both neighbours, so
the video drifts against the voiceover track; leave it off when sync matters.

Anything else - write a spec and build it:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/promptcut.py" capcut-build --spec spec.json
```

Add `--dump out/draft_content.json` to inspect the result without touching the
drafts folder.

## Spec schema

```json
{
  "name": "my_draft",
  "size": [1080, 1920],
  "fps": 30,
  "replace": true,
  "tracks": [
    {"type": "video", "name": "main", "index": 0, "mute": false, "segments": [
      {"file": "shot1.png",
       "start": 0, "duration": 4,
       "source_in": null, "source_duration": null,
       "speed": 1.0, "volume": 1.0,
       "clip": {"scale": 1.05, "scale_x": null, "scale_y": null,
                "x": 0, "y": 0, "rotation": 0, "alpha": 1,
                "flip_h": false, "flip_v": false},
       "animation_in": "zoom_in", "animation_in_dur": 0.8,
       "animation_out": "fade_out", "animation_group": null,
       "transition": "dissolve", "transition_dur": 0.5,
       "filter": "Peach_Fuzz", "filter_intensity": 60,
       "mask": {"type": "circle", "cx": 0, "cy": 0, "size": 0.8,
                "rotation": 0, "feather": 0.2, "invert": false,
                "rect_width": null, "round_corner": null},
       "effects": ["Beat_Shots", "char:Pop_Out"],
       "background": {"type": "blur", "blur": 0.0625},
       "keyframes": [{"prop": "scale_x", "at": 0, "value": 1.0},
                     {"prop": "scale_x", "at": 4, "value": 1.2}]}]},

    {"type": "audio", "name": "vo", "segments": [
      {"file": "vo.mp3", "start": 0.15, "duration": 3.2, "volume": 1.0,
       "speed": 1.0, "fade_in": 0.2, "fade_out": 0.4, "effect": null,
       "keyframes": [{"at": 0, "value": 1.0}, {"at": 3, "value": 0.4}]}]},

    {"type": "text", "name": "titles", "segments": [
      {"text": "BIG TITLE", "start": 0.2, "duration": 2.5,
       "font": "Anton", "size": 9, "color": "#FFFFFF", "bold": true,
       "align": 1, "alpha": 1, "letter_spacing": 0, "line_spacing": 0,
       "auto_wrap": true, "max_line_width": 0.82,
       "border": {"color": [0, 0, 0], "width": 45, "alpha": 1},
       "background": {"color": "#000000", "alpha": 0.5, "round": 0.2},
       "clip": {"y": -0.3},
       "anim_in": "typewriter", "anim_in_dur": 0.6,
       "anim_out": null, "loop_anim": null,
       "keyframes": [{"prop": "alpha", "at": 0, "value": 0}]}]},

    {"type": "sticker", "name": "st", "segments": [
      {"resource_id": "<capcut sticker id>", "start": 1, "duration": 2}]},

    {"type": "effect", "name": "fx", "segments": [
      {"effect": "Betamax", "start": 0, "duration": 2, "params": [60],
       "character": false}]},

    {"type": "filter", "name": "grade", "segments": [
      {"filter": "BW_2", "start": 0, "duration": 7, "intensity": 45}]}
  ],
  "srt": {"file": "subs.srt", "track": "subs", "offset": 0,
          "size": 7.5, "color": "FFFFFF", "bold": true, "align": 1}
}
```

Notes that bite:

- Segments on one track must not overlap. Sequential `start` + `duration` only;
  put simultaneous things on separate tracks.
- `duration` is clamped to the real length of the material, so a one-millisecond
  disagreement with ffprobe will not fail the build.
- Text `size` is CapCut's own unit, roughly 5-12; 7.5 is a normal subtitle.
  Colors take `#RRGGBB` or `[r,g,b]` floats.
- Keyframe `prop`: `position_x` `position_y` `rotation` `scale_x` `scale_y`
  `uniform_scale` `alpha` `saturation` `contrast` `brightness` `volume`.
  Audio keyframes take only `at` and `value` (volume).
- `effects` entries prefixed `char:` are character effects, not scene effects.

## Finding effect names

CapCut resource names are mostly Chinese even in the international build.
Search instead of guessing:

```
capcut-effects --type transition --search glitch
capcut-effects --type effect --search 抖动
capcut-effects --type filter --search BW
capcut-effects --type font --search Anton
```

Types and rough sizes: `transition` 1137, `effect` 1583 (scene),
`character` 254, `filter` 454, `intro` 251, `outro` 219, `group` 108,
`audio` 213, `text_intro` 182, `text_outro` 100, `text_loop` 81, `font` 348,
`mask` 6, `keyframe` 11.

Short English aliases work where they exist: transitions `dissolve` `fade`
`flash` `blur` `zoom` `spin` `glitch` `slide_left` `slide_right` `up` `down`;
intros `zoom_in` `zoom` `slide_up` `fade_in` `shake` `spin` `soft_zoom`;
outros `zoom_out` `fade_out` `slide_down`; masks `circle` `rect` `linear`
`mirror` `heart` `star`. Anything else: search, then paste the exact name. A
partial match is accepted and the resolved name is logged.

## Recipes

**Assembled video, manual polish.** `build` the mp4 for approval, then
`capcut-from-plan` so they can retime in CapCut with the same media.

**Subtitles only.** One video segment plus `srt`, and CapCut gets a fully
editable subtitle track - far better than burned-in text when they want to
restyle.

**Beat-cut montage.** Compute cut times (`scenes`, or beats from the music), lay
one video segment per interval, add `animation_in: "zoom_in"` on every other
segment and an `effect` on the drops.

**Vertical repost.** One segment, `clip.scale` ~1.3 with `background: blur`,
`size: [1080,1920]`, subtitles from SRT.
