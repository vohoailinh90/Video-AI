# Acceptance {{id}}
<!-- Written by {{title}}. Each line inside a ```bash block is one gate command, run from the repo root on a clean
     checkout with no network; every command must exit 0. After the tester stage they must FAIL (nothing is built).
     video_gates.py judges the render with ffprobe/ffmpeg: streams, length, size, loudness, silence. -->

```bash
cd videos/{{id}} && hyperframes lint
cd videos/{{id}} && hyperframes check
cd videos/{{id}} && mkdir -p renders && hyperframes render --quality draft --output renders/{{id}}.mp4
python3 /usr/local/lib/team-video/video_gates.py videos/{{id}}/renders/{{id}}.mp4 --expect videos/{{id}}.expected.json
```
