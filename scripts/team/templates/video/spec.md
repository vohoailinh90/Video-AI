# Spec {{id}}
<!-- Written by {{title}}. At most 120 lines: `{{team}} check-spec` rejects more.
     Free models build this without asking questions: every duration, word and file name must be explicit. -->

## Goal
TODO({{lead}}): "This video tells [audience] that [message]."

## Format
TODO({{lead}}): total seconds, width x height, fps (30), language, project folder `videos/{{id}}/`.

## Scenes
TODO({{lead}}): one row per scene: file `compositions/NN-name.html` | start-end seconds | exact on-screen text | motion.
Durations add up to the total. Voice length wins: the coder trues scene lengths to the real audio.

## Narration script
TODO({{lead}}): the exact words per scene, about 2.5 words per second, written as they should be spoken
(numbers spelled out). Voice id (e.g. af_heart) or the supplied audio file per scene.

## Audio plan
TODO({{lead}}): narration loudness about -16 LUFS; music bed volume under the voice; sound effects named from
the bundled library; every supplied file and its licence. "None" for music if none.

## Design
TODO({{lead}}): palette, type (font files that exist in the repo), safe margins, caption style.

## Non-goals
TODO({{lead}})

## Invariants
Offline build: no CDN, web font or remote image. GSAP at `assets/vendor/gsap.min.js`. `.claude/` untouched.
No `.mp4` in git. Every `<audio>` has an `id`.

## Risks and open points
TODO({{lead}})
