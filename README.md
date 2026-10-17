# Video-AI

Video dưới dạng code: mỗi video là một dự án [HyperFrames](https://github.com/heygen-com/hyperframes) (HTML + GSAP, render ra MP4
có audio). Quy ước của repo nằm trong [`CLAUDE.md`](CLAUDE.md).

## Hai cách làm video

1. **Cùng Claude Code, trên máy bạn:** mở repo, nói yêu cầu; Claude gọi `/hyperframes` rồi dựng trong `videos/<tên>/`.
2. **Team agent miễn phí trên VPS** (Claude làm kiến trúc sư, model free dựng, script chấm âm thanh và hình):
   xem [`docs/vps-team-video.md`](docs/vps-team-video.md).

   ```bash
   sudo ./scripts/team/setup-vps-team.sh --admin "$USER" --with-video
   team-video doctor --ping --smoke
   team-video new V01 --repo git@github.com:vohoailinh90/Video-AI.git
   ```

## Có gì trong repo

| Đường dẫn | Nội dung |
|---|---|
| `.claude/skills/` | bộ skill HyperFrames (upstream, khoá bằng `skills-lock.json`, không sửa tay) |
| `videos/<tên>/` | mỗi video một dự án (`index.html`, `compositions/`, `assets/`, `expected.json`) |
| `scripts/team/` | conductor, image worker (`Dockerfile.video`), prompt, `video/video_gates.py` |
| `docs/` | hướng dẫn team video, mô hình bảo mật, báo cáo nghiên cứu model miễn phí |
| `tests/` | test của team (`python3 -m unittest discover -s tests`) và mutation check |
