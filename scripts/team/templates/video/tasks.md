# Tasks {{id}}
<!-- Written by {{title}}. One `## ` section per task, small enough for a single model run: one scene, or one
     audio step. Every task needs all three fields with a value: `{{team}} check-spec` rejects it otherwise. -->

## T1: TODO({{lead}}) project skeleton (hyperframes init) and vendored GSAP
Files: TODO({{lead}}) videos/{{id}}/index.html, hyperframes.json, meta.json, package.json, AGENTS.md, CLAUDE.md, assets/vendor/gsap.min.js (all under videos/{{id}}/)
Do not touch: TODO({{lead}}) .claude/, videos/{{id}}.expected.json, other videos
Verify: TODO({{lead}}) cd videos/{{id}} && hyperframes lint

## T2: TODO({{lead}}) narration audio for every scene
Files: TODO({{lead}}) videos/{{id}}/assets/audio/
Do not touch: TODO({{lead}}) .claude/, videos/{{id}}.expected.json
Verify: TODO({{lead}}) ffprobe -v error -show_entries format=duration -of csv=p=0 videos/{{id}}/assets/audio/vo-01.wav

## T3: TODO({{lead}}) scene 1
Files: TODO({{lead}}) videos/{{id}}/compositions/01-name.html
Do not touch: TODO({{lead}}) .claude/, videos/{{id}}.expected.json
Verify: TODO({{lead}}) cd videos/{{id}} && hyperframes lint
