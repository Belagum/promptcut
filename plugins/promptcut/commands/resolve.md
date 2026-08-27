---
description: Hand the video to DaVinci Resolve - editable timeline with zoom/position keyframes, voiceover, music, titles, SRT subtitles
---

Use the `nle-export` skill with target `resolve`. Request: $ARGUMENTS

With an existing `plan.json` run `nle-from-plan --plan plan.json --target resolve`
(`--use-clips` after a real `build` when the exact rendered look matters more than
editable motion). Without a plan, write a `timeline.json` and run `nle-build`.
Then walk the person through File > Import > Timeline with "Use sizing
information" checked and the SRT import - the `next_steps` in the result.
