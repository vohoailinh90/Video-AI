# Video thử: VoiceStudio (từ bài GitHub Radar ngày 2026-10-13)

Video 53,6 giây, 1920×1080, 30 khung hình/giây, 5 cảnh, lời đọc tiếng Việt bằng giọng mặc định Hải Đăng (VieNeu-TTS) và nhạc nền tự tạo.
Đây là bản thử cho câu hỏi "tạo video từ nội dung bài trên repo được chưa": mọi chữ, số và lệnh trong video lấy từ các trường của một bài radar,
và một script kiểm tra điều đó. Cách làm từng bước: `docs/voiceover-workflow.md`, mục 8.

## Nguồn

`source/draft-vi.json` là bản sao nguyên văn của `digests/2026-10-13/voicestudio/draft-vi.json` trong repo `vohoailinh90/Github-radar`
(commit `d375c0a`, quét ngày 2026-10-13, repo được viết về: `debpalash/VoiceStudio`, giấy phép AGPL-3.0). File gồm các trường đã qua kiểm tra của bài
(`draft`) và số liệu (`facts`). Video không dùng mã, hình hay âm thanh nào của VoiceStudio, chỉ nêu lại thông tin trong bài.

Mỗi dòng trong `voiceover.json` có `source`: danh sách trường của bài mà câu đó diễn đạt lại (ví dụ `draft.how_it_works.steps[0]`).

## Chạy lại

Từ thư mục gốc của repo:

```bash
python3 -I scripts/vo/check_facts.py --source videos/voicestudio/source/draft-vi.json \
    --lines videos/voicestudio/voiceover.json --html videos/voicestudio/index.html     # mọi số, tên, lệnh có trong bài
cd videos/voicestudio
npx hyperframes browser ensure                          # nếu máy chưa có Chrome headless shell
npm run check
npm run render -- --output renders/voicestudio.mp4
```

File MP4 không được commit (`renders/` bị `.gitignore` chặn). Tổng hợp giọng có yếu tố ngẫu nhiên: tạo lại clip sẽ ra bản hơi khác, nên các clip
đã chọn nằm trong `assets/`. Nếu đổi `voiceover.json` hoặc clip, chạy `scripts/vo/revoice.py ... --apply` (xem README của `demo-video`) để đặt lại
thời điểm, thời lượng và âm lượng của các thẻ `<audio>`.

## Lời đọc và cách chọn lượt đọc

Mỗi câu tạo 3 lượt, PhoWhisper-small nghe lại từng clip, chọn lượt ít sai nhất (cột cuối là số từ sai trên tổng số từ của clip đã chọn). Hai câu (`vo-4`, `vo-6`) đổi cách diễn đạt sau lượt đầu vì
nhiều từ tiếng Anh bị đọc lệch; hai câu đó được tạo lại 3 lượt với lời mới (`vo-4` thêm một đợt nữa vì từ "nạp" bị nghe sai ở cả 3 lượt).

| Clip | Bắt đầu | Lời đọc | Lượt chọn | Sai/tổng |
|---|---|---|---|---|
| `vo-1` | 0,6 s | VoiceStudio tự nhân bản giọng nói và lồng tiếng ngay trên máy tính, không cần gửi dữ liệu lên đám mây. | 2 | 2/21 |
| `vo-2` | 7,2 s | Nhiều người e ngại chi phí đám mây và rủi ro lộ dữ liệu âm thanh, mà tự cấu hình mô hình AI trên máy lại phức tạp. VoiceStudio gói tất cả vào một ứng dụng desktop chạy khép kín trên máy. | 3 | 4/42 |
| `vo-3` | 18,4 s | Bạn chọn giọng mẫu hoặc tải âm thanh tham chiếu, rồi nhập văn bản cần đọc. | 1 | 0/16 |
| `vo-4` | 22,5 s | Phần backend tải mô hình tương ứng, rồi giao việc tính toán cho phần cứng phù hợp. | 8 (lượt thứ 2 của lời cuối) | 1/17 |
| `vo-5` | 26,9 s | Kết quả là tệp âm thanh hoàn chỉnh, và có thể điều khiển tự động qua Local API. | 3 | 2/18 |
| `vo-6` | 33,3 s | Ba điều đáng học: giao diện Electron tách riêng khỏi phần xử lý AI viết bằng Python, chạy được từ card đồ họa đến chỉ CPU, và mở cho tác tử AI điều khiển qua MCP. | 6 (lượt thứ 3 của lời mới) | 2/36 |
| `vo-7` | 44,5 s | Lưu ý: mã nguồn dùng giấy phép AGPL, còn trọng số mô hình có điều kiện cấp phép riêng. | 3 | 4/19 |
| `vo-8` | 49,6 s | Muốn chạy thử từ mã nguồn, dùng ba lệnh này. | 1 | 0/10 |

Lời đọc là bản rút gọn, diễn đạt lại từ các trường của bài, không chép nguyên văn. Cảnh 3 (cách chạy) chia thành ba clip, mỗi bước một clip, để từng ô hiện ra
đúng lúc câu tương ứng được đọc; cảnh 2 và 4 đặt từng thẻ theo chỗ ngắt hơi trong clip (đo bằng `ffmpeg silencedetect`).

## Nhạc nền

`assets/pad.wav` tự tạo bằng ffmpeg, không dùng nhạc của bên thứ ba (mono, 16 kHz vì đã lọc thấp ở 900 Hz, nên chỉ 1,7 MB):

```bash
ffmpeg -y \
 -f lavfi -i "sine=frequency=110:sample_rate=44100:duration=54" \
 -f lavfi -i "sine=frequency=164.81:sample_rate=44100:duration=54" \
 -f lavfi -i "sine=frequency=220:sample_rate=44100:duration=54" \
 -f lavfi -i "sine=frequency=277.18:sample_rate=44100:duration=54" \
 -filter_complex "[0]volume=0.5[a];[1]volume=0.35[b];[2]volume=0.3[c];[3]volume=0.15,tremolo=f=0.35:d=0.6[d];[a][b][c][d]amix=inputs=4:normalize=0,lowpass=f=900,afade=t=in:st=0:d=1.5,afade=t=out:st=51.5:d=2.5,volume=0.55" \
 -ac 1 -ar 16000 assets/pad.wav
```

`gsap.min.js` là GSAP 3.14.2 chép từ `videos/demo-video/` (giấy phép "no charge" của GreenSock, **không phải MIT**: https://gsap.com/standard-license).

## Đã kiểm tra (2026-10-17)

- `check_facts.py`: 8 dòng lời đọc và 51 đoạn chữ trên màn hình đều truy được về bài; thử trên một mẫu cố ý sai (số, tên, lệnh bịa) thì script báo lỗi.
- `npm run check`: 0 lỗi, 6 cảnh báo (gợi ý tách mỗi cảnh thành sub-composition), bố cục 0 vấn đề trên 9 mẫu, độ tương phản chữ 37/37 đạt WCAG AA.
- Đã xem 11 ảnh chụp từ bản dựng và 4 khung hình lấy từ file MP4: không thấy chữ nào bị cắt hay chồng.
- File MP4: H.264 + AAC, đúng 53,6 giây; âm thanh cả file trung bình -20,5 dB, đỉnh -1,3 dB (không câm).
- Mức dễ hiểu: PhoWhisper-small nghe lại âm thanh cắt từ MP4, sai 19/179 từ (11%). Lỗi nằm ở từ tiếng Anh và tên riêng (VoiceStudio đọc thành "voi studio", backend,
  Python, desktop, AGPL, Local API), cộng hai chữ tiếng Việt bị nghe lệch ("đám" thành "đã", "ba" thành "bà"). Máy nghe lại không thay được người nghe: một từ
  Anh đọc kiểu Việt hóa có thể vẫn dễ hiểu với người Việt dù máy chép khác.

## Giới hạn

- Chưa có người nghe và đánh giá độ tự nhiên, độ dễ hiểu của giọng đọc, nhất là các từ tiếng Anh.
- `check_facts.py` chỉ kiểm số, tên (chữ Latin) và lệnh. Câu tiếng Việt diễn đạt lại có thể lệch ý mà script không bắt được, nên cần một người đọc lời đọc đối chiếu với bài.
- Bố cục 16:9. Bài radar xuất bản dạng dọc (`portrait`), nên bản 9:16 là việc làm thêm. Chưa có phụ đề (cần thời điểm từng từ của tiếng Việt).
- Cảnh vẫn viết tay trong `index.html`: chưa có script tự biến một bài thành video.
