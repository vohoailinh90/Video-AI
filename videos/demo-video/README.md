# Video mẫu: Video AI bằng code

Video 17 giây, 1920×1080, 30 khung hình/giây, 4 cảnh, có lời đọc tiếng Việt và nhạc nền. Dùng để thử toàn bộ quy trình HyperFrames
(HTML + GSAP, render ra MP4, kiểm tra bằng `check`) và để thử giọng đọc tiếng Việt.

## Chạy lại

```bash
cd videos/demo-video
npx hyperframes browser ensure                          # nếu máy chưa có Chrome headless shell
npm run check
npx hyperframes render --output renders/demo-video.mp4
```

File MP4 không được commit (`renders/` bị `.gitignore` chặn); render lại mất khoảng 35–45 giây trên máy 4 nhân CPU. Lần chạy đầu cần mạng
để tải font từ Google Fonts.

## Lời đọc

Mỗi cảnh một clip, đặt trong `index.html` bằng thẻ `<audio id="vo-N" ...>`:

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

- `npm run check`: 0 lỗi, 5 cảnh báo (gợi ý tách mỗi cảnh thành sub-composition), bố cục không lỗi, độ tương phản chữ 51/51 đạt WCAG AA.
- File MP4 sau khi render: H.264 + AAC, đúng 17 giây. Giọng nổi hơn nhạc nền khoảng 18 dB, đỉnh âm -1,8 dB.
- Mức dễ hiểu: PhoWhisper-small nghe lại âm thanh cắt từ MP4, WER 11/33 = 33%. Mọi từ tiếng Việt được chép đúng; lỗi chỉ nằm ở từ tiếng Anh (code,
  engine, skill, file MP4, render), vì giọng đọc chúng theo kiểu Việt hóa. Chi tiết và giới hạn của phép đo: `docs/vietnamese-audio.md`, mục 0.
- Chưa có đánh giá bằng tai về độ tự nhiên và chất lượng âm thanh.
