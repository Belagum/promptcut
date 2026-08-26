---
description: One-off edit on existing files - cut, join, subtitles, music, speed, reframe, remove pauses
---

Use the `video-toolbox` skill in single-action mode. Task: $ARGUMENTS

`probe` the input first when the answer depends on its length, size or whether it
has audio. Pick the one command that does the job, write the result to a new file
next to the source (never overwrite their original), and report the path plus
what changed. Chain commands only when the request genuinely needs it.
