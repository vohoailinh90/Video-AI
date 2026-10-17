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

Khóa API nằm trong `~/MoneyPrinterTurbo/config.toml` (MPT tự tạo từ file mẫu lần chạy đầu): `pexels_api_keys = ["..."]`. MPT xoay vòng qua mọi phần tử của danh sách và gửi nguyên phần tử đó, nên danh sách rỗng hay có một phần tử rỗng đều bị `plan`/`run` từ chối. Không đặt khóa trong repo này.
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
  `material_source` + `materials` (clip local), `audio_file` (tiếng có sẵn, ví dụ từ `scripts/vo/`), `bgm` (`none`, `random` hoặc tên file nhạc đuôi mp3, m4a, aac, wav, flac, ogg, opus hay wma, như MPT; `audio_file` hẹp hơn: chỉ mp3, wav, m4a, aac, flac, ogg, vì CLI của MPT từ chối cả manifest với đuôi khác; đuôi không phân biệt hoa thường). Tên font và tên file nhạc là một tên file (không có thư mục, không ký tự điều khiển) với đúng đuôi; MPT không giới hạn các ký tự khác nên `Noto Sans (Condensed).ttf` hay `Rock & Roll.mp3` đều dùng được, `bgm_volume`,
  `subtitles`, `font`, `font_size`, `clip_seconds`, `target_seconds` (ngưỡng độ dài cho QA).
- Tiếng Việt mặc định dùng font `BeVietnamPro-Bold.ttf` (font mặc định của MPT là chữ Hán và không hợp tiếng Việt). Giọng phải cùng ngôn ngữ với `language`.
- Khóa lạ, giọng sai ngôn ngữ, thiếu từ khóa, trùng id, clip hoặc file tiếng local không có hoặc không đọc được... đều báo **một lần cho tất cả lỗi** (`path: message`). Clip local và `audio_file` không được nằm trong thư mục kết quả của chính video đó (`build/autovideo/<batch>/<id>/`): mỗi lần render xóa kết quả cũ ở đó (ví dụ `narration.mp3`) nên file đầu vào sẽ mất; hãy sao chép ra chỗ khác (ví dụ dùng lại lời đọc cũ thì copy `narration.mp3` ra ngoài). Tiêu đề phải là một dòng; tiêu đề và đường dẫn file không được chứa ký tự điều khiển (xuống dòng, tab, chuỗi escape), vì `plan` và `run` in chúng ra terminal. Đường link, ký hiệu markdown, emoji trong lời đọc chỉ cảnh báo.

## Lệnh

Ví dụ đặt gói ở `batches/<batch>/` (thư mục này chưa có; tạo khi cần).

```bash
python3 scripts/autovideo/main.py validate batches/meo-lam-video      # kiểm gói, không cần mạng và không cần MPT
python3 scripts/autovideo/main.py plan     batches/meo-lam-video      # từng video: thời lượng ước tính, tham số MPT, thiếu khóa/font/nhạc nào (`--json` có ở plan, run, status)
python3 scripts/autovideo/main.py run      batches/meo-lam-video      # render lần lượt; --only 01-ba-meo, --force, --retries 1, --timeout 1800
python3 scripts/autovideo/main.py status   batches/meo-lam-video      # pending / done / failed / qa_failed / stale (gói đã đổi) / missing (mất video) / unchecked (đổi ngưỡng QA, chưa kiểm lại)
python3 scripts/autovideo/main.py qa       batches/meo-lam-video      # chạy lại QA trên video đã có, không render
```

Mã thoát: 0 tất cả tốt (với `status`: mọi video đã `done`, tính cả file thật và ngưỡng QA hiện tại), 1 có video lỗi, không qua QA, chưa render, mất hoặc hỏng file kết quả (`missing`: thiếu file, hoặc nội dung file khác với lúc render; tính cả `mpt.log` vì QA đọc nó để biết nhạc có được trộn không (so băm SHA-256, nên `status` và `run` đọc mỗi file kết quả một lần)), hoặc là bản cũ so với gói (`stale`) (với `plan`: không tìm thấy MPT, hoặc thiếu khóa/font/nhạc khiến `run` không chạy được), 2 gói hoặc tham số sai (kể cả `--retries` âm, `--timeout` không dương), 3 một lần chạy khác đang giữ batch. Kết quả ở `build/autovideo/<batch>/` (đã nằm trong `.gitignore`):

```
state.json  summary.json  summary.md
<id>/video.mp4  narration.mp3  subtitles.srt  transcript.txt  transcript.json  job.json  report.json  mpt.log
```

`transcript.json` có lời từng cảnh kèm thời điểm bắt đầu/kết thúc (tính từ phụ đề) và toàn bộ cue. Lời là lời trong gói, **không phải** kết quả nghe lại âm thanh;
muốn nghe lại thì dùng `scripts/vo/roundtrip.py` (PhoWhisper).

## QA

Mỗi video được đo trên file thật. Mục `error` mà trượt thì không đăng: đọc được, có một luồng hình, có tiếng, đúng khổ, độ dài trong `target_seconds`,
tiếng không im lặng (trung bình dưới -50 dB), phụ đề có đủ, đúng thứ tự, không vượt độ dài video, và phủ ít nhất 80% từ của lời đọc. Mục `error` còn có `music_mixed` (khi bgm bật): bài nhạc hỏng hoặc không giải mã được thì MPT chỉ ghi một dòng lỗi `failed to mix background music` vào log rồi render tiếp không nhạc, và lời đọc vẫn làm video nghe được, nên file không cho thấy gì; tool tìm dòng đó trong lời MPT in ra và ghi một dòng kết quả vào `mpt.log` để QA đọc. Đây là kiểm tra duy nhất dựa vào log chứ không phải file, và dựa vào đúng câu chữ của bản MPT đã kiểm tra: nếu MPT đổi câu chữ thì kiểm tra này không bắt được nữa. Mục `warn`: độ dài video lệch quá 3 giây so với tiếng.
Mỗi lần QA chấp nhận hay từ chối một thư mục (sau khi render, và sau `qa`), state ghi lại băm các file kết quả đang có ở đó; file bổ sung bằng tay (ví dụ `subtitles.srt`) mà `qa` đã tính thì được theo dõi từ đó, và sau này bị sửa hay xóa thì job thành `missing`. Đổi `target_seconds` không làm render lại: `run` và `qa` chỉ kiểm lại video có sẵn (`status` báo `unchecked` cho tới khi kiểm). Video vẫn trượt thì giữ `qa_failed`; sửa gói hoặc ngưỡng, hoặc `run --force --only <id>` để render lại.
Một job đã trượt QA (sau `1 + --retries` lần thử) không bị `run` lần sau render lại, vì đầu vào không đổi thì kết quả gần như không đổi: `run` báo `qa_failed` kèm lý do rồi đi tiếp. Muốn thử lại thì sửa gói, hoặc `run --force --only <id>` (thêm `--retries N` nếu muốn nhiều lần thử hơn trong lần chạy đó; `--retries` chỉ là số lần thử thêm trong MỘT lần chạy, không được nhớ giữa các lần). Job `failed` (engine không render được) thì lần `run` sau vẫn thử lại.
File nhạc tùy chỉnh (`bgm`, khi âm lượng > 0) và font phụ đề (khi bật phụ đề) nằm trong thư mục của MPT, ngoài gói (MPT chỉ dùng file có đường dẫn thật nằm trong đúng thư mục đó: symlink trỏ ra ngoài bị MPT từ chối, nên `plan` và `run` báo lỗi trước khi chạy; với nhạc, MPT thử `storage/bgm` rồi `resource/songs`): tool ghi băm nội dung hai file đó khi render, và `run` render lại khi file bị thay hoặc mất (`status` và `qa` cũng báo `stale` khi tìm được MPT; không tìm được MPT thì không nói gì về hai file này). Thứ gói không nêu tên (config.toml của MPT, phiên bản MPT) không được theo dõi. Với `bgm: random` (mặc định, âm lượng > 0), `plan` và `run` báo lỗi khi MPT không có bài nhạc nào dùng được trong `storage/bgm` và `resource/songs` (MPT sẽ lặng lẽ render không nhạc, và QA không bắt được vì lời đọc vẫn nghe được); đặt `bgm: "none"` nếu cố ý không dùng nhạc. MPT chọn ngẫu nhiên một bài và bỏ qua lặng lẽ bài không mở được, nên mọi bài trong hai thư mục đó phải đọc được, nếu không `plan`/`run` báo tên bài hỏng.
`run` và `qa` ghi state và báo cáo nên giữ khoá `<batch>/.lock` (`flock`, chỉ Linux/macOS) trong suốt lần chạy: chạy hai lần cùng một batch thì lần sau thoát với mã 3 thay vì ghi đè state của nhau. Ctrl-C hoặc SIGTERM dừng cả MPT đang render (cùng mọi tiến trình MPT đã khởi động) rồi mới thoát, nên không có MPT mồ côi chạy tiếp sau khi khoá đã nhả; job bị ngắt ở trạng thái `running` và lần `run` sau sẽ render lại nó. `status` chỉ đọc nên không cần khoá. Các batch khác nhau độc lập với nhau; MPT khuyên không render hai video cùng lúc, và tool không chặn việc đó giữa các batch.
Mọi giá trị, dài bao nhiêu cũng vậy, của các trường trong config.toml của MPT có tên chứa key, token, secret hay password bị thay bằng `***` trước khi log và báo cáo được lưu (giá trị chỉ có khoảng trắng thì bỏ qua; việc phát hiện lỗi trộn nhạc làm trên chữ gốc trước khi che, rồi ghi kết quả thành một dòng `[autovideo] music mix failed:` ở cuối `mpt.log` (nội dung dòng đó cũng được che như phần còn lại), nên che bí mật không làm mất hay làm sai kết quả).

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
