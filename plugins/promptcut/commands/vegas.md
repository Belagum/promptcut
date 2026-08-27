---
description: Hand the video to VEGAS Pro - a script builds the project with pan/crop keyframes, voiceover, ducked music, titles, markers
---

Use the `nle-export` skill with target `vegas`. Request: $ARGUMENTS

With an existing `plan.json` run `nle-from-plan --plan plan.json --target vegas`;
add `--run` to start VEGAS on the generated script right away (check `doctor`
shows `nle.vegas`). Without a plan, write a `timeline.json` and run `nle-build`.
Explain that the `.cs` script builds and saves a `.veg`, how to run it from
Tools > Scripting on an empty project, and Insert > Subtitles From File for the
SRT - the `next_steps` in the result.
