---
description: Cut vertical shorts or reels - from a topic, a script, or an existing long video
---

Use the `video-toolbox` skill. Target: $ARGUMENTS

Vertical defaults: `aspect 9:16`, `subtitles.max_chars 26`, big bold subtitles,
6-10 shots of 8-14 words, music bed at -23 dB, total 25-55 seconds.

If the input is an existing video file: `transcribe --granularity word`, pick the
strongest self-contained stretches from the transcript, `cut` each one,
`reframe --aspect 9:16 --mode blur`, then `subs-burn`. Report one file per short.

If the input is a topic or script: storyboard it into `plan.json`, `build --fake`
to check the length, then `build`.
