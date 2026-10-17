# Từ bài GitHub Radar thành video, bằng script

`scripts/radar/make_video.py` biến một bài radar (`draft-vi.json` của repo `github-radar`) thành một dự án video có lời đọc tiếng Việt, render ra MP4, mà **không cần model nào viết nội dung**.
Bản làm tay trước đó: `videos/voicestudio/` và `docs/voiceover-workflow.md`, mục 8.

## Dùng nhanh

```bash
# xem trước: video sẽ gồm những gì, lời đọc dài bao nhiêu (không ghi file nào)
python3 -I scripts/radar/make_video.py plan ../Github-radar/digests/2026-10-13/voicestudio/draft-vi.json

# làm tất cả: dựng khung, tạo giọng, chọn lượt, render, đo, viết README
python3 -I scripts/radar/make_video.py all ../Github-radar/digests/2026-10-13/voicestudio/draft-vi.json \
    --tts-python .venv/tts/bin/python --asr-python .venv/asr/bin/python --preview
```

Hai môi trường Python (`.venv/tts`, `.venv/asr`) và tên miền Hugging Face: xem `docs/voiceover-workflow.md`, phần "Chuẩn bị". Trong phiên cloud, thêm `--tts-hf-home` và `--asr-hf-home` nếu bộ nhớ đệm model nằm ở thư mục khác.
Thiếu `--asr-python` thì lệnh vẫn chạy: dùng lượt đầu tiên của mỗi câu và không đo mức dễ hiểu (README ghi "chưa đo").

## Bốn bước

| Bước | Lệnh | Làm gì |
|---|---|---|
| 1 | `scaffold DIGEST` | Chạy `hyperframes init`, chép bài vào `source/draft-vi.json` (kèm `provenance.json`: đường dẫn, sha256, commit cuối của file), viết `voiceover.json`, `index.html` (thời lượng ước tính) và nhạc nền; chạy cổng đối chiếu trên bản nháp. Không ghi đè dự án có sẵn |
| 2 | `voice PROJECT --tts-python ...` | Tạo 3 lượt giọng Hải Đăng cho mỗi câu, cho PhoWhisper nghe lại từng lượt, chọn lượt ít sai nhất, đo độ dài thật, xếp lại thời gian toàn video, viết lại `index.html`, `voiceover.json` và nhạc nền theo độ dài thật, chạy cổng đối chiếu |
| 3 | `render PROJECT` | `scripts/vo/revoice.py --apply` (đặt âm lượng, `npm run check`, render MP4), đo mức âm và đo lại lời đọc trên chính file MP4, ghi `README.md` và `preview.json`; `--preview` dựng thêm trang xem thử trong `build/` |
| 4 | `all DIGEST` | Ba bước trên liền nhau |

Báo cáo từng bước nằm ở `build/<tên dự án>/report.json` (không commit).

## Bài thành cảnh thế nào

Mỗi cảnh gồm các đơn vị (unit): một clip lời đọc cộng một phần tử trên màn hình, lấy nguyên văn từ trường của bài (chỉ bỏ dấu nháy mã, gộp khoảng trắng).
Lời đọc đi vào bộ tổng hợp giọng có chữ số được đọc thành chữ (62.958 thành "sáu mươi hai nghìn chín trăm năm mươi tám"); chữ trên màn hình giữ nguyên chữ số.

| Cảnh | Trường của bài | Lời đọc | Trên màn hình |
|---|---|---|---|
| Mở đầu | `facts`, `title`, `hook` | tên repo, rồi `hook` | tên repo cỡ lớn, phần sau dấu `:` của `title`, các chip: sao, fork, giấy phép, ngôn ngữ, ngày quét |
| Vấn đề | `problem` | câu mở đầu, và câu nêu tên công cụ (nếu `problem` có hơn hai câu) | câu đầu là thẻ vấn đề, câu nêu tên công cụ là thẻ lời giải |
| Cách chạy | `how_it_works.steps`, `components` | `text` của từng bước (tối đa 4) | `title` của từng bước thành ô nối bằng mũi tên; sau đó hàng "các mảnh ghép" (tên và đường dẫn bằng chứng) |
| Học được gì | `learn` | từng mục (tối đa 3) | thẻ chứa nguyên văn |
| Lưu ý và thử | `caveats`, `try_it` | từng lưu ý (tối đa 2), rồi `note` của `try_it` | thẻ lưu ý; cửa sổ terminal gõ các lệnh của `try_it.commands` (tối đa 4); địa chỉ `facts.url` ở chân |

Cảnh nào bài không có dữ liệu thì bị bỏ. Mỗi hàng chữ cố định (tiêu đề cảnh, "Số liệu theo ngày quét", "sao", "fork") nằm trong phần tử `data-label` của mẫu và không bị đối chiếu; mọi chữ khác phải đến từ bài.

**Ngân sách lời đọc** (`--speech-seconds`, mặc định 60 giây, ước lượng 19 ký tự mỗi giây). Bắt đầu từ: tên + hook, hai câu của vấn đề, 4 bước, 3 mục học, 2 lưu ý, ghi chú thử. Nếu vượt ngân sách thì cắt theo thứ tự cố định:
lưu ý còn 1, mục học còn 2, bỏ ghi chú thử (các lệnh vẫn hiện), bước còn 3. Hook, vấn đề, 3 bước và 1 lưu ý không bao giờ bị cắt; nếu vẫn dài hơn thì `plan` và `scaffold` in cảnh báo "over the speech budget".

## Cổng đối chiếu (không do model quyết định)

`scripts/vo/check_facts.py` chạy ở mỗi bước. Mỗi dòng của `voiceover.json` ghi `source` (các trường của bài); mọi số, tên chữ Latin và lệnh trong dòng đó phải có trong các trường ấy, và chữ trên màn hình phải có trong toàn bộ bài.
Mỗi lệnh của `try_it.commands` phải hiện đúng nguyên văn. Lỗi thì `voice` dừng, in lý do, nhưng file đã ghi nên có thể sửa tiếp.

Sửa lời đọc: được. Mở `voiceover.json`, sửa `text` (và `source` nếu cần) của dòng đó, rồi chạy `voice PROJECT --only vo-4 --tts-python ...`. Script giữ lại câu bạn sửa (kể cả khi chạy lại `voice`), tính lại chữ đọc, tạo lại giọng cho dòng đó và để cổng quyết định câu mới còn đúng với bài không.
Từ tiếng Việt viết không dấu (như "giao", "cho", "ba") bị cổng báo nhầm là tên Latin; ghi vào mảng `allow` của `voiceover.json`.
Dòng nào lượt tốt nhất vẫn sai quá 30% số từ được đánh cờ trong báo cáo: thường vì từ tiếng Anh, hãy viết lại câu bằng từ tiếng Việt như đã làm với video VoiceStudio ("nạp" thành "tải", "agent" thành "tác tử AI").

## Kiểm thử

```bash
python3 -m unittest discover -s tests -v    # không cần mạng, model hay trình duyệt: số thành chữ, tách câu, ngân sách, thời gian, mã HTML, cổng đối chiếu
```

Các bài kiểm thử dùng bốn bài radar thật chép vào `tests/fixtures/` (một bài thường, một bài không có `try_it`, một bài có `problem` một câu, một bài dài nhất).

## Giới hạn

- Chỉ bài tiếng Việt (`lang: vi`); VieNeu-TTS đọc tiếng Việt, và các nhãn cố định viết bằng tiếng Việt.
- Lời đọc là câu nguyên văn của bài, viết để đọc chứ không để nghe: câu dài, nhiều từ tiếng Anh. Mức dễ hiểu đo bằng máy; chưa có người nghe đánh giá độ tự nhiên.
- Khổ 16:9 và không có phụ đề (cần thời điểm từng từ của tiếng Việt). Bài radar xuất bản dạng dọc nên bản 9:16 là việc làm thêm.
- Bố cục: `npm run check` (0 lỗi, 0 vấn đề bố cục) đã chạy trên 9 bài radar thật khi dựng khung với clip im lặng; chưa render và nghe từng bài.
- Cổng đối chiếu chỉ kiểm số, tên và lệnh, không hiểu nghĩa: câu viết lại bằng tay cần người đối chiếu với bài.
