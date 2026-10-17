# Video-AI

Video dưới dạng code: mỗi video là một dự án [HyperFrames](https://github.com/heygen-com/hyperframes) (HTML + GSAP, render ra MP4
có audio). Quy ước của repo nằm trong [`CLAUDE.md`](CLAUDE.md).

## Hai cách làm video

1. **Cùng Claude Code, trên máy bạn:** mở repo, nói yêu cầu; Claude gọi `/hyperframes` rồi dựng trong `videos/<tên>/`.
2. **Team agent miễn phí trên VPS** (Claude làm kiến trúc sư, model free dựng, script chấm âm thanh và hình): team nằm trong repo
   [`vohoailinh90/claude-agent-routing-template`](https://github.com/vohoailinh90/claude-agent-routing-template) (`scripts/team/`),
   hướng dẫn cài và dùng ở `docs/vps-team-video.md` của repo đó. Repo này chỉ giữ các video mà team làm ra; phần quy ước dành cho
   team nằm trong mục "VPS agent team" của [`CLAUDE.md`](CLAUDE.md).

   ```bash
   # trên VPS, từ bản clone của repo template
   sudo ./scripts/team/setup-vps-team.sh --admin "$USER" --with-video
   team-video doctor --ping --smoke
   team-video new V01 --repo git@github.com:vohoailinh90/Video-AI.git
   ```

## Có gì trong repo

| Đường dẫn | Nội dung |
|---|---|
| `.claude/skills/` | bộ skill HyperFrames (upstream, khoá bằng `skills-lock.json`, không sửa tay) |
| `videos/<tên>/` | mỗi video một dự án (`index.html`, `compositions/`, `assets/`) |
| `videos/<tên>.expected.json` | ngưỡng cho gate của team (độ dài, loudness, ...): nằm cạnh thư mục dự án, không nằm trong đó, vì `hyperframes init` từ chối thư mục không rỗng |
| `videos/<tên>.inputs/` | file người vận hành đưa vào (ví dụ giọng đọc tiếng Việt từng cảnh), cũng nằm cạnh thư mục dự án |
| `scripts/` | công cụ dùng chung: `vo/` (lồng tiếng), `preview/` (trang xem thử), `radar/` (từ bản tin ra video) |
| `docs/` | quy trình lồng tiếng, âm thanh tiếng Việt, từ bản tin ra video, `TEAM.md` |
| `tests/` | test của `scripts/radar` |
