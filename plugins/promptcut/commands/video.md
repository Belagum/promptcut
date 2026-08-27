---
description: Make a full video from an idea or a script - storyboard, voiceover, images, music, subtitles, render
---

Use the `video-toolbox` skill. The person wants a finished video from: $ARGUMENTS

Steps, in order:

1. If the request is thin, ask at most two questions that actually change the
   output: language and voice of the narration, aspect (16:9 or 9:16), and
   whether images should be generated or pulled from stock. Then stop asking and
   work.
2. If they pasted a script, keep their wording. If they gave a topic, write the
   narration yourself, then show it as plain text for approval before spending
   anything.
3. Write `plan.json` next to their working directory, run `plan-check`, then
   `build --fake` and report duration and shot count.
4. On approval run the real `build`. Report the mp4 path, duration and
   `spend_usd`.
5. Offer `capcut-from-plan` or `nle-from-plan --target premiere|resolve|vegas`
   if they may want to hand-tweak in their editor.
