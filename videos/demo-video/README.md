# Video mẫu: Video AI bằng code

Video 17 giây, 1920×1080, 30 khung hình/giây, 4 cảnh, có lời đọc tiếng Việt và nhạc nền. Dùng để thử toàn bộ quy trình HyperFrames
(HTML + GSAP, render ra MP4, kiểm tra bằng `check`) và để thử giọng đọc tiếng Việt. Có hai giọng: nữ (Mai Anh, mặc định) và nam (Hải Đăng).

## Chạy lại

```bash
cd videos/demo-video
npx hyperframes browser ensure                          # nếu máy chưa có Chrome headless shell
npm run check
npx hyperframes render --output renders/demo-video.mp4
```

File MP4 không được commit (`renders/` bị `.gitignore` chặn); render lại mất khoảng 35–45 giây trên máy 4 nhân CPU. Lần chạy đầu cần mạng
để tải font từ Google Fonts.

Bản giọng nam (chạy từ thư mục gốc của repo): `revoice.py` chép dự án sang thư mục tạm, thay clip giọng, chỉnh thời lượng và âm lượng rồi render, dự án gốc không đổi.

```bash
python3 -I scripts/vo/revoice.py --project videos/demo-video --lines videos/demo-video/voiceover.json \
    --clips videos/demo-video/voices/hai-dang --out videos/demo-video/renders/demo-video-nam.mp4
```

Trang xem thử có nút chuyển giữa hai giọng: `docs/voiceover-workflow.md`, mục 6.

## Lời đọc

Mỗi cảnh một clip, đặt trong `index.html` bằng thẻ `<audio id="vo-N" ...>`. Lời đọc, thời điểm bắt đầu và tên cảnh nằm trong `voiceover.json`
(các script đọc file này); bảng dưới đây là bản đọc được của nó:

| Clip | Bắt đầu | Lời đọc |
|---|---|---|
| `vo-1` | 0,5 giây | Video AI bằng code. |
| `vo-2` | 4,1 giây | Có ba lớp để tự động hóa video: engine, skill và kiến thức. |
| `vo-3` | 9,2 giây | Từ ý tưởng đến file MP4, hoàn toàn tự động. |
| `vo-4` | 13,6 giây | Chỉ cần một lệnh để render. |

Câu thứ hai khác chữ trên màn hình ("3 lớp để tự động hóa video"). Giọng đọc "Ba lớp" ở đầu câu bị nghe thành "bàn lớp" ở mọi lần thử, còn "Có ba lớp"
thì đúng.

## Nguồn gốc các tài nguyên

| File | Nguồn | Giấy phép |
|---|---|---|
| `assets/vo-1.wav` đến `vo-4.wav` | VieNeu-TTS v3 Turbo, giọng dựng sẵn "Mai Anh", 48 kHz mono. Tổng hợp có yếu tố ngẫu nhiên, tạo lại sẽ ra bản hơi khác | Model Apache-2.0 (theo model card). Chưa rõ nguồn dữ liệu của giọng dựng sẵn |
| `voices/hai-dang/vo-1.wav` đến `vo-4.wav` | VieNeu-TTS v3 Turbo, giọng dựng sẵn "Hải Đăng" (nam, miền Bắc), 48 kHz mono. Mỗi câu chọn một trong 2–3 lượt tổng hợp, theo bảng ở `docs/voiceover-workflow.md`, mục 3 | Như trên |
| `assets/pad.wav` | Nhạc nền tự tạo bằng ffmpeg (lệnh bên dưới), không dùng nhạc của bên thứ ba | Không vướng bản quyền bên thứ ba |
| `gsap.min.js` | GSAP 3.14.2, chép sẵn vào dự án để render không phụ thuộc mạng | Giấy phép "no charge" của GreenSock (https://gsap.com/standard-license), **không phải MIT**; xem điều khoản trước khi dùng cho sản phẩm thương mại |
| `AGENTS.md`, `CLAUDE.md` | `hyperframes init` tạo ra | Của HyperFrames (Apache-2.0) |

Lệnh tạo `assets/pad.wav`:

```bash
ffmpeg -y \
 -f lavfi -i "sine=frequency=110:sample_rate=44100:duration=17" \
 -f lavfi -i "sine=frequency=164.81:sample_rate=44100:duration=17" \
 -f lavfi -i "sine=frequency=220:sample_rate=44100:duration=17" \
 -f lavfi -i "sine=frequency=277.18:sample_rate=44100:duration=17" \
 -filter_complex "[0]volume=0.5[a];[1]volume=0.35[b];[2]volume=0.3[c];[3]volume=0.15,tremolo=f=0.35:d=0.6[d];[a][b][c][d]amix=inputs=4:normalize=0,lowpass=f=900,afade=t=in:st=0:d=1.5,afade=t=out:st=15:d=2,volume=0.55" \
 -ac 2 assets/pad.wav
```

## Đã kiểm tra

Đo ngày 2026-10-17 trên hai file MP4 đã render từ chính các file đang có trong repo:

| | Nữ, Mai Anh | Nam, Hải Đăng |
|---|---|---|
| Định dạng | H.264 + AAC, 1920×1080, 30 khung hình/giây, đúng 17 giây | giống bản nữ |
| Mức âm cả file (giọng + nhạc nền) | trung bình -21,2 dB, đỉnh -1,8 dB | trung bình -21,7 dB, đỉnh -2,5 dB |
| PhoWhisper-small nghe lại âm thanh cắt từ MP4 | WER 10/33 = 30% | WER 10/33 = 30% |

- `npm run check`: 0 lỗi, 5 cảnh báo (gợi ý tách mỗi cảnh thành sub-composition), bố cục không lỗi, độ tương phản chữ 51/51 đạt WCAG AA. Bản giọng nam cũng qua `npm run check` (do `revoice.py` chạy).
- Ở cả hai giọng, mọi từ tiếng Việt được chép đúng; lỗi nằm ở từ tiếng Anh (code, engine, skill, file MP4, render), vì giọng đọc chúng theo kiểu Việt hóa (bản nữ còn bị chép thừa một chữ "ai" ở câu đầu). Chi tiết và giới hạn của phép đo: `docs/vietnamese-audio.md`, mục 0.
- Chưa có đánh giá bằng tai về độ tự nhiên và chất lượng âm thanh của cả hai giọng.
