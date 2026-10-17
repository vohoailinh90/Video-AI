# autovideo: làm hàng loạt video có tiếng từ kịch bản do agent viết

Công cụ nằm ở `scripts/autovideo/`. Nó dựa trên [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) (MPT, MIT) và
bài hướng dẫn `Github-radar/digests/2026-10-16-3/moneyprinterturbo/vi.md`. MPT vẫn làm phần nặng: tải clip, đọc lời bằng Edge TTS, tạo phụ đề,
trộn nhạc, ghép video. `autovideo` bọc bên ngoài và thêm phần MPT chưa có:

| Việc | MPT | autovideo |
|---|---|---|
| Viết kịch bản | nhờ một LLM | **agent của Claude viết trước, đưa vào gói kịch bản** (MPT không cần khóa LLM) |
| Nhiều video | `--batch-file`, một lần, lỗi một cái vẫn chạy tiếp, không nhớ gì | chạy lần lượt, **nhớ trạng thái**, chạy lại chỉ làm phần chưa xong hoặc đã sửa |
| Kiểm tra kết quả | không | **QA trên file**: ffprobe, volumedetect, phụ đề |
| Đầu ra | `storage/tasks/<uuid>/` | một thư mục cho mỗi video: video, tiếng, phụ đề, transcript, báo cáo |

Chỉ dùng nguồn clip miễn phí (`pexels`, `pixabay`, `coverr`, `local`). Các nguồn trả tiền của MPT (WaveSpeed, Seedance, OFox...) không mở,
vì mỗi nguồn đó đòi một cờ xác nhận tính tiền riêng.

## Cài đặt (một lần)

```bash
git clone https://github.com/harry0703/MoneyPrinterTurbo.git ~/MoneyPrinterTurbo
cd ~/MoneyPrinterTurbo && uv sync --frozen          # hoặc --python 3.13 nếu máy không có 3.11
```

Khóa API nằm trong `~/MoneyPrinterTurbo/config.toml` (MPT tự tạo từ file mẫu lần chạy đầu): `pexels_api_keys = ["..."]`. Không đặt khóa trong repo này.
Giọng Edge TTS không cần khóa nhưng cần ra được internet tới Microsoft. Kiểm tra: `python3 scripts/autovideo/main.py doctor`
(chỉ in "set / NOT set", không bao giờ in giá trị khóa). Đổi chỗ MPT bằng `--mpt-home` hoặc `$MPT_HOME`.

## Gói kịch bản (pack)

Một file JSON, hoặc một thư mục `pack.json` + `videos/<id>.json` (mỗi video một file để nhiều agent viết song song không đụng nhau; tên file phải là `<id>.json`).

```json
{
  "batch": "meo-lam-video",
  "defaults": { "language": "vi-VN", "aspect": "9:16", "voice": "vi-VN-HoaiMyNeural", "target_seconds": [20, 60] },
  "videos": [{
    "id": "01-ba-meo",
    "title": "Ba mẹo viết lời đọc cho video ngắn",
    "scenes": [
      { "narration": "Mở đầu bằng một câu hỏi để giữ người xem.", "terms": ["person thinking", "question mark"] },
      { "narration": "Mỗi câu chỉ nói một ý, đọc to lên cho dễ nghe.", "terms": ["microphone", "podcast"] }
    ]
  }]
}
```

- Mỗi video có `scenes[]` (lời đọc + từ khóa tìm clip). Từ khóa viết **tiếng Anh** cho kho clip. Lời đọc ghép thành `video_script`, từ khóa gộp thành `video_terms`.
- Cài đặt (đặt trong `defaults` hoặc ghi đè trong từng video): `language`, `aspect` (`9:16`, `16:9`, `1:1`), `voice`, `voice_rate`, `voice_volume`,
  `material_source` + `materials` (clip local), `audio_file` (tiếng có sẵn, ví dụ từ `scripts/vo/`), `bgm` (`none`, `random` hoặc tên file nhạc), `bgm_volume`,
  `subtitles`, `font`, `font_size`, `clip_seconds`, `target_seconds` (ngưỡng độ dài cho QA).
- Tiếng Việt mặc định dùng font `BeVietnamPro-Bold.ttf` (font mặc định của MPT là chữ Hán và không hợp tiếng Việt). Giọng phải cùng ngôn ngữ với `language`.
- Khóa lạ, giọng sai ngôn ngữ, thiếu từ khóa, trùng id... đều báo **một lần cho tất cả lỗi** (`path: message`). Đường link, ký hiệu markdown, emoji trong lời đọc chỉ cảnh báo.

## Lệnh

Ví dụ đặt gói ở `batches/<batch>/` (thư mục này chưa có; tạo khi cần).

```bash
python3 scripts/autovideo/main.py validate batches/meo-lam-video      # kiểm gói, không cần mạng và không cần MPT
python3 scripts/autovideo/main.py plan     batches/meo-lam-video      # từng video: thời lượng ước tính, tham số MPT, thiếu khóa/font/nhạc nào (`--json` có ở plan, run, status)
python3 scripts/autovideo/main.py run      batches/meo-lam-video      # render lần lượt; --only 01-ba-meo, --force, --retries 1, --timeout 1800
python3 scripts/autovideo/main.py status   batches/meo-lam-video      # pending / done / failed / qa_failed / stale (gói đã đổi) / missing (mất video) / unchecked (đổi ngưỡng QA, chưa kiểm lại)
python3 scripts/autovideo/main.py qa       batches/meo-lam-video      # chạy lại QA trên video đã có, không render
```

Mã thoát: 0 tất cả tốt (với `status`: mọi video đã `done`, tính cả file thật và ngưỡng QA hiện tại), 1 có video lỗi, không qua QA, chưa render, mất file, hoặc là bản cũ so với gói (`stale`) (với `plan`: không tìm thấy MPT, hoặc thiếu khóa/font/nhạc khiến `run` không chạy được), 2 gói hoặc tham số sai (kể cả `--retries` âm, `--timeout` không dương), 3 một lần chạy khác đang giữ batch. Kết quả ở `build/autovideo/<batch>/` (đã nằm trong `.gitignore`):

```
state.json  summary.json  summary.md
<id>/video.mp4  narration.mp3  subtitles.srt  transcript.txt  transcript.json  job.json  report.json  mpt.log
```

`transcript.json` có lời từng cảnh kèm thời điểm bắt đầu/kết thúc (tính từ phụ đề) và toàn bộ cue. Lời là lời trong gói, **không phải** kết quả nghe lại âm thanh;
muốn nghe lại thì dùng `scripts/vo/roundtrip.py` (PhoWhisper).

## QA

Mỗi video được đo trên file thật. Mục `error` mà trượt thì không đăng: đọc được, có một luồng hình, có tiếng, đúng khổ, độ dài trong `target_seconds`,
tiếng không im lặng (trung bình dưới -50 dB), phụ đề có đủ, đúng thứ tự, không vượt độ dài video, và phủ ít nhất 80% từ của lời đọc. Mục `warn`: độ dài video lệch quá 3 giây so với tiếng.
Đổi `target_seconds` không làm render lại: `run` và `qa` chỉ kiểm lại video có sẵn (`status` báo `unchecked` cho tới khi kiểm). Video vẫn trượt thì giữ `qa_failed`; sửa gói hoặc ngưỡng, hoặc `run --force --only <id>` để render lại.
File nhạc tùy chỉnh (`bgm`, khi âm lượng > 0) và font phụ đề (khi bật phụ đề) nằm trong thư mục của MPT, ngoài gói: tool ghi băm nội dung hai file đó khi render, và `run` render lại khi file bị thay hoặc mất (`status` và `qa` cũng báo `stale` khi tìm được MPT; không tìm được MPT thì không nói gì về hai file này). Thứ gói không nêu tên (config.toml của MPT, phiên bản MPT) không được theo dõi.
`run` và `qa` ghi state và báo cáo nên giữ khoá `<batch>/.lock` (`flock`, chỉ Linux/macOS) trong suốt lần chạy: chạy hai lần cùng một batch thì lần sau thoát với mã 3 thay vì ghi đè state của nhau. Ctrl-C hoặc SIGTERM dừng cả MPT đang render (cùng mọi tiến trình MPT đã khởi động) rồi mới thoát, nên không có MPT mồ côi chạy tiếp sau khi khoá đã nhả; job bị ngắt ở trạng thái `running` và lần `run` sau sẽ render lại nó. `status` chỉ đọc nên không cần khoá. Các batch khác nhau độc lập với nhau; MPT khuyên không render hai video cùng lúc, và tool không chặn việc đó giữa các batch.
Khóa API trong log của MPT bị thay bằng `***` trước khi lưu.

## Đã kiểm tra gì, chưa kiểm tra gì

- `python3 -m unittest discover -s tests` (28 test, chạy với một MPT giả ghi media thật bằng ffmpeg): gói, tham số MPT, transcript, QA, chạy lại/bỏ qua/sửa,
  lỗi giữa chừng, hết giờ, che khóa, doctor. Hai lỗi cố ý (tắt che khóa, bỏ ngưỡng im lặng) làm test đỏ.
- Đã chạy với MPT thật (checkout mới nhất ngày 2026-10-17) bằng clip local và `audio_file`: ra MP4 1080x1920 có tiếng, QA đạt, chạy lại thì bỏ qua.
- **Chưa chạy**: Edge TTS (giọng `vi-VN-HoaiMyNeural`/`vi-VN-NamMinhNeural`), tải clip Pexels/Pixabay và phụ đề do Edge tạo, vì phiên cloud này không ra được
  `speech.platform.bing.com`, `api.pexels.com`. Tham số cho các đường đó dựng theo mã nguồn MPT; hãy chạy `plan` rồi `run` một video ngắn trên máy có mạng trước khi chạy cả lô.
- Bản quyền clip, nhạc và font vẫn là việc của người đăng: xem thư mục `task_dir` trong `report.json` để biết MPT đã lấy gì.

## Phần còn lại

Lớp team agent của Claude (kiến trúc viết kịch bản, nhiều writer song song, reviewer) chưa nằm trong repo này: chủ repo tạo riêng. Nó chỉ cần ghi gói kịch bản đúng schema
ở trên, gọi `validate` / `plan` / `run` / `qa`, và đọc `report.json`.
