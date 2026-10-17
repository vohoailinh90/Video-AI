# Video thử: VoiceStudio (tự động từ bài GitHub Radar 2026-10-13)

Video 70.4 giây, 1920×1080, 30 khung hình/giây, 5 cảnh, lời đọc tiếng Việt giọng Hải Đăng (VieNeu-TTS) và nhạc nền tự tạo.
File này do `scripts/radar/make_video.py` tạo ra; cách làm và giới hạn: `docs/radar-to-video.md`.

## Nguồn

`source/draft-vi.json` là bản sao nguyên văn của file `digests/2026-10-13/voicestudio/draft-vi.json` trong repo `https://github.com/vohoailinh90/Github-radar` (bản ghi cuối cùng của file: `d375c0a04d23171a105b51b974478f192fb55987 2026-10-13`); video này được dựng từ bản chép giống hệt từng byte của nó trong `tests/fixtures/voicestudio.json` (so bằng sha256) (sha256 `d3f2c2e12dd985bf...`). Repo được viết về: `debpalash/VoiceStudio`. Video không dùng mã, hình hay âm thanh nào của repo đó.
Cảnh, lời đọc và chữ trên màn hình đều lấy từ các trường của bài; mỗi dòng của `voiceover.json` ghi trường nó lấy (`source`).

## Chạy lại

Từ thư mục gốc của repo:

```bash
python3 -I scripts/vo/check_facts.py --source videos/voicestudio-auto/source/draft-vi.json --lines videos/voicestudio-auto/voiceover.json --html videos/voicestudio-auto/index.html
python3 -I scripts/radar/make_video.py render videos/voicestudio-auto --asr-python <python của môi trường PhoWhisper>
```

File MP4 không được commit (`renders/` bị `.gitignore` chặn). Tổng hợp giọng có yếu tố ngẫu nhiên, nên các clip đã chọn nằm trong `assets/`.
Sửa lời đọc trong `voiceover.json` rồi chạy `make_video.py voice videos/voicestudio-auto --only vo-N --tts-python ...` cho các dòng đã sửa.

## Lời đọc

| Clip | Bắt đầu | Lời đọc | Lượt chọn | Sai/tổng từ của clip |
|---|---|---|---|---|
| `vo-1` | 0.6 s | VoiceStudio. Tự nhân bản giọng nói và lồng tiếng đa ngôn ngữ ngay trên máy tính mà không cần gửi dữ liệu lên đám mây. | 1 | 2/25 |
| `vo-2` | 7.9 s | Nhiều người sáng tạo nội dung và lập trình viên muốn tạo giọng đọc, lồng tiếng hay phiên âm nhưng e ngại chi phí dịch vụ đám mây cùng rủi ro lộ dữ ... | 1 | 0/36 |
| `vo-3` | 16.4 s | VoiceStudio giải quyết vấn đề này bằng một ứng dụng desktop trọn gói chạy khép kín trên máy. | 3 | 3/18 |
| `vo-4` | 23.14 s | Người dùng chọn giọng mẫu hoặc tải lên tệp âm thanh tham chiếu, sau đó nhập văn bản cần đọc hoặc chọn tệp video cần lồng tiếng. | 1 | 3/27 |
| `vo-5` | 29.56 s | Backend xử lý nạp mô hình tương ứng và điều phối việc tính toán đến phần cứng phù hợp để tổng hợp hoặc bóc băng giọng nói. | 2 | 2/27 |
| `vo-6` | 36.22 s | Hệ thống tạo ra tệp âm thanh hoàn chỉnh và cho phép điều khiển tự động qua giao tiếp Local API hoặc Model Context Protocol. | 1 | 4/25 |
| `vo-7` | 47.18 s | Phân tách kiến trúc rõ ràng giữa giao diện desktop Electron và backend AI bằng Python để dễ bảo trì. | 3 | 4/20 |
| `vo-8` | 53.68 s | Thiết kế cơ chế linh hoạt tận dụng đa dạng phần cứng từ card đồ họa cao cấp đến chỉ chạy trên CPU. | 1 | 2/23 |
| `vo-9` | 60.58 s | Mã nguồn dùng giấy phép AGPL-3.0, nhưng trọng số mô hình và dữ liệu giọng nói có điều kiện cấp phép riêng. | 2 | 4/25 |

## Đã kiểm tra

- Cổng đối chiếu bài (`check_facts.py`): checked 9 lines and 34 on-screen text pieces (1 numbers in narration): all traced to the source
- `npm run check`: 0 error(s), 6 warning(s), 0 info(s) | ◇  Check passed
- File MP4: 70.4 giây; âm thanh cả file trung bình -20.5 dB, đỉnh -1.3 dB
- PhoWhisper-small nghe lại âm thanh cắt từ MP4: sai 27/226 từ (12%). Máy nghe lại không thay được người nghe: từ tiếng Anh đọc kiểu Việt hóa có thể vẫn dễ hiểu với người Việt.


## Giới hạn

- Chưa có người nghe và đánh giá độ tự nhiên của giọng, nhất là với từ tiếng Anh.
- `check_facts.py` chỉ kiểm số, tên (chữ Latin) và lệnh; lời đọc mặc định là câu nguyên văn của bài nên không lệch ý, nhưng câu nào đã được viết lại cần người đối chiếu.
- Khổ 16:9, chưa có phụ đề.
