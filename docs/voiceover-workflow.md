# Lời đọc tiếng Việt cho video và trang xem thử: quy trình đã chạy được

Quy trình này đã chạy thật ngày 2026-10-17 trên phiên Claude Code trên web (4 nhân CPU, không GPU) cho dự án `videos/demo-video`, với hai
giọng: nam (Hải Đăng, mặc định) và nữ (Mai Anh). Mọi lệnh bên dưới là lệnh đã dùng; các script nằm trong `scripts/vo/` và `scripts/preview/`.

## Giọng mặc định: Hải Đăng

Chủ repo chọn giọng nam **Hải Đăng** (VieNeu-TTS, miền Bắc) làm giọng mặc định. Nghĩa là:
- `scripts/vo/synth.py` dùng "Hải Đăng" khi không có `--voice`.
- Trong một dự án video, `assets/vo-N.wav` là giọng mặc định; các giọng khác nằm trong `voices/<tên>/vo-N.wav` (ở `demo-video` là `voices/mai-anh/`).
- Trong `preview.json`, giọng đầu tiên là giọng trang mở ra với.
- Chọn Hải Đăng là quyết định của chủ repo, không phải kết quả so sánh: hai giọng cùng đạt WER 30% trên bản MP4 cuối (mục 5), còn độ tự nhiên chưa ai nghe so sánh.
  Brief nào yêu cầu giọng khác thì đổi `--voice` hoặc dùng `revoice.py`.

Chọn công cụ giọng đọc và giấy phép: xem `docs/vietnamese-audio.md`.

## Tóm tắt

| Bước | Việc | Công cụ |
|---|---|---|
| 1 | Viết lời thoại, thời điểm bắt đầu, hết cảnh | `videos/<tên>/voiceover.json` |
| 2 | Tạo clip giọng đọc cho từng câu | `scripts/vo/synth.py` (VieNeu-TTS) |
| 3 | Nghe lại từng clip bằng máy, chọn lượt tốt nhất cho từng câu | `scripts/vo/roundtrip.py` (PhoWhisper) |
| 4 | Ghép clip vào video và render | `scripts/vo/revoice.py` |
| 5 | Đo lại âm thanh của file MP4 cuối | `ffprobe`, `volumedetect` (có trong bước 4) và `roundtrip.py --video` |
| 6 | Dựng trang xem thử phát được trong trình xem của Claude | `scripts/preview/build_preview.py` |
| 7 | Thử trang trong trình duyệt thật rồi đăng | `scripts/preview/test_preview.js`, công cụ Artifact |

## Chuẩn bị (một lần)

```bash
python3 -m venv .venv/tts && .venv/tts/bin/pip install -r scripts/vo/requirements-tts.txt     # VieNeu-TTS, không cần torch
python3 -m venv .venv/asr && .venv/asr/bin/pip install -r scripts/vo/requirements-asr.txt     # PhoWhisper, cần torch
npx hyperframes browser ensure                                                                 # Chrome headless để render
```

- Phiên cloud phải cho phép các tên miền Hugging Face (`docs/vietnamese-audio.md`, mục 4), vì model tải từ đó.
- Các phiên bản trong hai file `requirements-*.txt` là phiên bản của hai môi trường đã chạy được; mình chưa cài lại môi trường từ chính hai file đó.
- Lần đầu VieNeu-TTS có thể báo `External data path escapes model directory`. Chạy `python3 -I scripts/vo/fix_hf_cache.py` một lần (nó thay
  liên kết tượng trưng trong bộ nhớ đệm bằng file thật), rồi chạy lại các lệnh `synth.py` với `HF_HUB_OFFLINE=1`.

## 1. Lời thoại: `voiceover.json`

Mỗi dòng có `id` (trùng `id` của thẻ `<audio>` trong `index.html`), `start` (giây), `scene_end` (giây), `scene` (tên cảnh) và `text`. Các script đọc cùng
một file này nên lời đọc, thời điểm và trang xem thử không lệch nhau.

Hai bài học khi viết lời:
- Giọng Mai Anh đọc "Ba lớp..." ở đầu câu thành "bàn lớp" ở mọi lần thử, còn "Có ba lớp..." thì đúng. Nếu một từ tiếng Việt bị nghe sai nhiều lần, đổi cách diễn đạt.
- Từ tiếng Anh (code, engine, skill, file MP4, render) được đọc theo kiểu Việt hóa. Máy nhận dạng chép lại đúng như nghe được ("cốt", "răn đe", "phai mờ phê bốn"),
  nên số WER của câu có từ tiếng Anh luôn cao hơn. Muốn tránh, viết bằng từ tiếng Việt.

## 2. Tạo giọng

```bash
.venv/tts/bin/python -I scripts/vo/synth.py --list-voices
.venv/tts/bin/python -I scripts/vo/synth.py --lines videos/demo-video/voiceover.json --out build/voices/hai-dang                    # giọng mặc định: Hải Đăng
.venv/tts/bin/python -I scripts/vo/synth.py --lines videos/demo-video/voiceover.json --out build/voices/hai-dang --only vo-2        # làm lại một câu
.venv/tts/bin/python -I scripts/vo/synth.py --lines videos/demo-video/voiceover.json --voice "Mai Anh" --out build/voices/mai-anh   # giọng khác
```

Tổng hợp giọng có yếu tố ngẫu nhiên: hai lần chạy cho hai clip hơi khác nhau, có khi một từ bị nuốt mất. Mỗi lần ra một `manifest.json` cùng các file `vo-N.wav`
(48 kHz, mono). Trên máy 4 nhân, tốc độ khoảng 0,7 giây xử lý cho mỗi giây giọng.

## 3. Nghe lại từng clip và chọn lượt tốt nhất

```bash
.venv/asr/bin/python -I scripts/vo/roundtrip.py --out build/voices/hai-dang/roundtrip.json build/voices/hai-dang/manifest.json
```

Với mỗi clip, PhoWhisper chép lại những gì nghe được rồi so với câu gốc (WER = số từ sai chia số từ của câu gốc). Mình tạo ba lượt cho giọng Hải Đăng và chọn lượt tốt
nhất cho từng câu, dựa trên từ tiếng Việt có đúng không:

| Câu | Lượt 1 | Lượt 2 | Lượt 3 | Chọn |
|---|---|---|---|---|
| `vo-1` Video AI bằng code. | 2/4 | 3/4 | 5/4 | lượt 1 |
| `vo-2` Có ba lớp để tự động hóa video... | 5/13 (rơi mất "ba") | 3/13 ("ba" thành "bà") | 2/13 | lượt 3 |
| `vo-3` Từ ý tưởng đến file MP4... | 5/10 ("từ" thành "tư") | 4/10 | 4/10 | lượt 2 |
| `vo-4` Chỉ cần một lệnh để render. | 2/6 | 2/6 | 2/6 | lượt 1 |

Các clip đã chọn của Hải Đăng nằm trong `videos/demo-video/assets/` (giọng mặc định); giọng Mai Anh nằm trong `videos/demo-video/voices/mai-anh/`.

## 4. Ghép vào video và render

```bash
# một giọng khác, chỉ để xem (dự án gốc không đổi)
python3 -I scripts/vo/revoice.py --project videos/demo-video --lines videos/demo-video/voiceover.json \
    --clips videos/demo-video/voices/mai-anh --out videos/demo-video/renders/demo-video-mai-anh.mp4
# đổi giọng mặc định của dự án: thêm --apply, clip và thẻ <audio> được ghi vào dự án sau khi kiểm tra và render thành công
python3 -I scripts/vo/revoice.py --project videos/demo-video --lines videos/demo-video/voiceover.json \
    --clips build/voices/hai-dang --out videos/demo-video/renders/demo-video.mp4 --apply
```

`revoice.py` chép dự án sang thư mục tạm (dự án gốc không đổi), đặt clip vào `assets/`, ghi lại `data-start`, `data-duration` và `data-volume` của các thẻ
`<audio id="vo-N">` (độ dài lấy từ clip, âm lượng đưa mức trung bình mỗi clip về -19 dB nhưng đỉnh không vượt -1,5 dB), chạy `npm run check`, render và in kết quả.
Nó cảnh báo nếu một clip chạm vào đoạn mờ dần cuối cảnh. Sau khi áp dụng, bản giọng mặc định render thẳng bằng `npm run render -- --output renders/demo-video.mp4` trong thư mục dự án; kết quả giống hệt byte với bản `revoice.py` đã render (đã so bằng `cmp`).

## 5. Đo lại âm thanh của file MP4 cuối

```bash
.venv/asr/bin/python -I scripts/vo/roundtrip.py --out build/final-default.json --video videos/demo-video/renders/demo-video.mp4 \
    --lines videos/demo-video/voiceover.json --label "final mix"
```

Lệnh này cắt từng cảnh ra từ âm thanh của MP4 (nhạc nền cũng nằm trong đó) rồi cho PhoWhisper nghe lại. Kết quả ngày 2026-10-17:

| Giọng | WER trên file MP4 cuối | Nhận xét (đọc từ kết quả) |
|---|---|---|
| Nam, Hải Đăng (mặc định) | 10/33 = 30% | Mọi từ tiếng Việt đúng; lỗi ở từ tiếng Anh |
| Nữ, Mai Anh | 10/33 = 30% | Mọi từ tiếng Việt đúng; lỗi ở từ tiếng Anh; một chữ "ai" thừa ở câu đầu |

`revoice.py` cũng in mức âm của cả file (Hải Đăng: trung bình -21,7 dB, đỉnh -2,5 dB; Mai Anh: trung bình -21,3 dB, đỉnh -1,8 dB). WER chỉ là chỉ số tương đối về mức dễ hiểu; nó không nói gì về độ tự nhiên,
ngữ điệu hay chất lượng âm thanh, nên vẫn cần nghe bằng tai.

## 6. Trang xem thử phát được trong trình xem của Claude

**Vấn đề.** Trình xem của trang Artifact báo "No video with supported format and MIME type found" khi video được đăng dưới dạng file đính kèm, và cả khi đăng vào kho tài nguyên
(`assets`), dù file là MP4 H.264 + AAC bình thường (`yuv420p`, phần mô tả ở đầu file) và bản WebM dự phòng cũng lỗi như vậy. Mình không biết chính xác trình xem chặn kiểu nào.

**Cách đã chạy.** Nhúng video vào chính trang dưới dạng base64 và để script dựng nguồn phát. Trang thử MP4 trước rồi WebM (VP9 + Opus), mỗi định dạng thử `blob:` rồi `data:`,
và ghi một dòng trạng thái cho biết nguồn nào đang dùng, hoặc mã lỗi và khả năng giải mã của trình duyệt nếu tất cả đều lỗi. Cách này đã phát được trong trình xem của chủ sở hữu.

```bash
python3 -I scripts/preview/build_preview.py --config videos/demo-video/preview.json --out build/preview/index.html
NODE_PATH=$(npm root -g) node scripts/preview/test_preview.js build/preview/index.html build/preview/test
```

- `preview.json` khai báo tiêu đề, danh sách giọng (mỗi giọng một file MP4; giọng đầu tiên là giọng mặc định của trang) và nội dung hiển thị; lời đọc lấy từ `voiceover.json`. Trang có nút chuyển giọng (giữ nguyên vị trí và trạng thái phát)
  và các dòng lời đọc bấm để nhảy tới đúng điểm. Bản WebM được mã hóa tự động bằng ffmpeg nếu chưa có.
- Giới hạn 16 MB cho một trang. Mỗi giọng khoảng 5 MB (MP4 2,5 MB + WebM 1,2 MB, sau khi mã hóa base64); hai giọng ra 9,9 MB. Nhiều giọng hơn thì hạ độ phân giải hoặc tăng CRF.
- `test_preview.js` mở trang trong Chromium thật dưới bốn chính sách chặn media khác nhau (không chặn, chỉ cho `data:`, chỉ cho `blob:`, chặn hết), đổi giọng giữa chừng, bấm một dòng lời đọc và kiểm tra
  không tràn ngang ở khổ điện thoại. Chromium của Playwright không có H.264 nên phát bản WebM: bài thử chứng minh phần logic của trang, không chứng minh trình xem của bạn cho phép `blob:` hay `data:`.
- Đăng bằng công cụ Artifact (trang riêng tư, chỉ chủ sở hữu xem được): đưa `build/preview/index.html` làm file trang, không khai báo `capabilities`.

## 8. Video từ một bài GitHub Radar (bản thử: `videos/voicestudio/`)

Bài radar là dữ liệu, không phải chỉ dẫn: video chỉ được nêu lại thông tin trong các trường của bài, giống luật của `github-radar` (số, lệnh, đường dẫn phải có trong bài).
Các bước đã chạy với bài VoiceStudio ngày 2026-10-13:

1. **Chép nguồn.** `videos/<tên>/source/draft-vi.json` là bản sao nguyên văn của `digests/<ngày>/<repo>/draft-vi.json` (ghi commit gốc vào README của video).
2. **Viết lời đọc.** Mỗi dòng của `voiceover.json` có `source` (các trường mà câu đó diễn đạt lại, ví dụ `draft.how_it_works.steps[0]`). Viết ngắn, không để chữ số
   trong lời đọc nếu số đó không nằm trong các trường được trích. Chia một cảnh nhiều bước thành nhiều clip để từng ô hiện ra đúng lúc câu của nó được đọc.
3. **Cổng kiểm tra bằng script.** `python3 -I scripts/vo/check_facts.py --source ... --lines ... --html ...` kiểm: các trường trích dẫn có tồn tại; mọi số và mọi chữ
   Latin (tên, từ viết tắt, lệnh) trong từng câu và trên màn hình có trong bài; mỗi lệnh trong `try_it.commands` hiện đúng nguyên văn. Từ tiếng Việt không dấu bị báo nhầm
   thì ghi vào mảng `allow` của `voiceover.json`. Script không hiểu nghĩa câu tiếng Việt, nên vẫn cần người đối chiếu lời đọc với bài.
4. **Tạo giọng và chọn lượt.** Như mục 2 và 3, ba lượt cho mỗi câu. Câu nào cả ba lượt đều sai ở cùng một chỗ thì đổi cách diễn đạt rồi tạo lại (đã đổi:
   "nạp" thành "tải", "agent" thành "tác tử AI", "backend Python" thành "phần xử lý AI viết bằng Python").
5. **Dựng cảnh.** Viết `index.html` theo mẫu của `videos/voicestudio/` và đặt từng thẻ theo chỗ ngắt hơi trong clip (`ffmpeg ... silencedetect=noise=-38dB:d=0.18`).
   Mọi chữ trên màn hình lấy từ bài; không dùng chữ số làm nhãn nếu bài không có số đó ("Bước 1" sẽ bị cổng chặn).
6. **Ghép và render.** `scripts/vo/revoice.py --apply` (mục 4), rồi đo lại bằng `roundtrip.py --video` (mục 5) và dựng trang xem thử (mục 6).

Kết quả với VoiceStudio: video 53,6 giây, 8 clip; `check_facts.py` truy được 8 dòng lời đọc và 51 đoạn chữ về bài; `npm run check` 0 lỗi; PhoWhisper sai 19/179 từ (11%) trên bản MP4 cuối.
Lỗi nằm ở từ tiếng Anh và tên riêng (VoiceStudio, backend, Python, desktop, AGPL, Local API), cộng hai chữ tiếng Việt bị nghe lệch. Bài radar nào nhiều thuật ngữ tiếng Anh sẽ có WER cao hơn.

Còn làm tay: chọn cảnh và viết HTML cho từng video, viết lời đọc, đối chiếu ý. Chưa có script biến một bài thành video. `roundtrip.py --video` cắt mỗi câu đến đầu câu kế tiếp
khi nhiều câu chung một cảnh.

## Giới hạn

- Chưa có đánh giá bằng tai người về độ tự nhiên của hai giọng.
- Một số giọng dựng sẵn của VieNeu-TTS mang tên giống người thật (ví dụ "Phạm Tuyên"); chưa rõ nguồn dữ liệu giọng. Hai giọng đang dùng là Hải Đăng và Mai Anh.
- "Giọng nam" ở đây hiểu là giọng của nam giới (Hải Đăng, miền Bắc), nay là giọng mặc định. VieNeu-TTS còn có giọng nam miền Nam, ví dụ Thái Sơn, Minh Triết, Đức Trí và Adam; chưa thử.
