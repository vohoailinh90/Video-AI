# Audio tiếng Việt: các repo GitHub nên dùng

Tổng hợp ngày 2026-10-17. Số liệu lấy từ trang GitHub của từng repo, đọc đúng ngày đó. Số sao thay đổi theo thời gian, nên
hãy xem lại trước khi quyết định.

## Cách đọc tài liệu này

- **★** là số sao GitHub tại thời điểm đọc. Trong mỗi nhóm, repo được xếp theo số sao giảm dần.
- **Chưa chạy thử.** Không công cụ nào dưới đây được chạy thử, vì `huggingface.co` bị chính sách mạng của môi trường cloud chặn
  và hầu hết model nằm ở đó. Mọi thông tin là từ README, không phải từ kết quả nghe thử hay đo thử.
- **Giấy phép của mã nguồn không phải giấy phép của model.** Trang GitHub thường chỉ nói về mã. `NC` nghĩa là chỉ được dùng phi
  thương mại. Trước khi đăng video thương mại, hãy đọc model card của đúng model bạn dùng.

## Khuyến nghị nhanh

| Nhu cầu | Thử trước | Lý do | Lưu ý |
|---|---|---|---|
| Giọng đọc, máy có GPU NVIDIA từ 8 GB VRAM | **VoxCPM2** (OpenBMB) | 39.4k★, mã và weights đều Apache-2.0, tiếng Việt nằm trong 30 ngôn ngữ, clone giọng | Cần CUDA 12 trở lên |
| Giọng đọc, chỉ có CPU (kể cả container cloud) | **VieNeu-TTS** v3 Turbo | 2.9k★, làm riêng cho tiếng Việt, 25 giọng, chạy CPU bằng ONNX | Trang không ghi giấy phép riêng cho weights; bản v4 đóng nguồn |
| Phụ đề, bóc băng | **Whisper large-v3** | 110.7k★, MIT, tiếng Việt có trong danh sách ngôn ngữ | Là bản đa ngôn ngữ chung, không tối ưu riêng cho tiếng Việt |
| Bóc băng chính xác nhất cho tiếng Việt | **PhoWhisper** (VinAI) | Whisper tinh chỉnh trên 844 giờ tiếng Việt, tác giả báo kết quả tốt nhất ở các bộ thử | 260★; weights ở Hugging Face |

## 1. Đọc văn bản thành giọng (TTS)

### 1A. Làm riêng cho tiếng Việt

| # | Repo | ★ | Giấy phép | Điểm nổi bật | Lưu ý |
|---|---|---|---|---|---|
| 1 | [pnnbao97/VieNeu-TTS](https://github.com/pnnbao97/VieNeu-TTS) | 2.9k | Apache-2.0 (mã) | v3 Turbo 48 kHz, 25 giọng Bắc/Trung/Nam, clone từ clip 3–8 giây, ONNX chạy CPU (RTF khoảng 0.5 trên Core i5 thế hệ 12) | v4 đóng nguồn, chỉ có qua API; int8 cần CPU có VNNI, không thì âm thanh có thể rè |
| 2 | [tronghieuit/v-tts](https://github.com/tronghieuit/v-tts) | 383 | **CC BY-NC 4.0** | 74.8M tham số, 5 giọng, clone từ 3–10 giây, không cần GPU | Cấm dùng thương mại nếu chưa có phép bằng văn bản |
| 3 | [NTT123/vietTTS](https://github.com/NTT123/vietTTS) | 259 | MIT | Duration model + acoustic model + HiFiGAN | README nói dự án **không còn cập nhật**, người kế nhiệm là LightSpeed |
| 4 | [nguyenthienhy/F5-TTS-Vietnamese](https://github.com/nguyenthienhy/F5-TTS-Vietnamese) | 174 | MIT (mã) | Pipeline tinh chỉnh F5-TTS cho tiếng Việt, tác giả báo khoảng 1000 giờ dữ liệu | Là pipeline huấn luyện, không phải model dựng sẵn; một trang tổng hợp ghi model là CC-BY-NC-SA, **chưa xác minh** |
| 5 | [nguyenvulebinh/VietVoice-TTS](https://github.com/nguyenvulebinh/VietVoice-TTS) | 105 | MIT | Chọn giới tính, vùng miền, phong cách (tin tức, audiobook...), cảm xúc; clone từ clip + lời; ONNX CPU/GPU | README không nói weights ở đâu; chưa lên PyPI |
| 6 | [dangvansam/viet-tts](https://github.com/dangvansam/viet-tts) | 88 | Apache-2.0 (mã), **model CC BY-NC** | 24 giọng có sẵn, API tương thích OpenAI (`/v1/audio/speech`), clone giọng | Bộ cài Python chỉ hỗ trợ Linux; model huấn luyện từ dữ liệu "in-the-wild" |

### 1B. Công cụ đa ngôn ngữ có tiếng Việt (đã kiểm chứng trên trang GitHub)

| # | Repo | ★ | Giấy phép | Bằng chứng tiếng Việt | Lưu ý |
|---|---|---|---|---|---|
| 1 | [OpenBMB/VoxCPM](https://github.com/OpenBMB/VoxCPM) | 39.4k | Apache-2.0 (mã và weights) | Liệt kê trong 30 ngôn ngữ | Python 3.10–3.12, CUDA từ 12.0, khoảng 8 GB VRAM; có chế độ thiết kế giọng bằng mô tả |
| 2 | [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice) | 14.6k | Apache-2.0 (mã) | `docs/languages.md`: "Vietnamese, vi, vie, 8481.98" giờ dữ liệu | Hơn 600 ngôn ngữ; trang không ghi giấy phép weights |
| 3 | [rany2/edge-tts](https://github.com/rany2/edge-tts) | 12.3k | GPL-3.0 (suy ra từ file `gpl-3.0.txt`) | Tên giọng `vi-VN-HoaiMyNeural` và `vi-VN-NamMinhNeural` chỉ thấy ở các nguồn bên thứ ba; kiểm lại bằng `edge-tts --list-voices` | Gọi dịch vụ TTS **trực tuyến** của Microsoft Edge, không chạy cục bộ; README không nói gì về độ ổn định hay điều khoản dùng thương mại |
| 4 | [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl) | 5.9k | GPL-3.0 | `docs/VOICES.md` có dòng "Tiếng Việt, Vietnam (Vietnamese, vi_VN)" | Tài liệu ghi Piper "dành cho dùng cá nhân và nghiên cứu TTS"; giấy phép từng giọng nằm trong `MODEL_CARD` |

## 2. Nhận dạng giọng nói (STT) cho phụ đề và bóc băng

### 2A. Làm riêng cho tiếng Việt

| # | Repo | ★ | Giấy phép | Điểm nổi bật | Lưu ý |
|---|---|---|---|---|---|
| 1 | [VinAIResearch/PhoWhisper](https://github.com/VinAIResearch/PhoWhisper) | 260 | BSD-3-Clause (repo) | 5 cỡ (tiny 39M đến large 1.55B), tinh chỉnh từ Whisper trên 844 giờ. WER cỡ large: 8.14 (CMV-Vi), 4.67 (VIVOS), 13.75 và 26.68 (VLSP 2020 Task-1/2) | Trang không nêu giấy phép của weights; đề nghị trích dẫn bài báo |
| 2 | [dangvansam/viet-asr](https://github.com/dangvansam/viet-asr) | 179 | Apache-2.0 | Model nhỏ 13M, khoảng 100 giờ dữ liệu | Dựa trên PyTorch 1.8.1 cũ; không có số WER; ít phù hợp hơn PhoWhisper |
| 3 | [khanld/ASR-Wav2vec-Finetune](https://github.com/khanld/ASR-Wav2vec-Finetune) | 152 | Trang không ghi | Bộ công cụ tinh chỉnh Wav2vec 2.0, có hướng dẫn cho dữ liệu tiếng Việt | Là công cụ huấn luyện, không phải model dựng sẵn |
| 4 | [khanld/chunkformer](https://github.com/khanld/chunkformer) | 87 | Trang ghi huy hiệu CC BY 4.0; model card (theo kết quả tìm kiếm) ghi **CC BY-NC 4.0** | Bóc băng âm thanh rất dài (README nói tới 16 giờ), model CTC và RNN-T cho tiếng Việt, có ONNX từ 2026-06 | Hai nguồn mâu thuẫn về giấy phép: **đọc model card trước khi dùng thương mại** |

### 2B. Công cụ đa ngôn ngữ có tiếng Việt (đã kiểm chứng)

| # | Repo | ★ | Giấy phép | Bằng chứng tiếng Việt | Lưu ý |
|---|---|---|---|---|---|
| 1 | [openai/whisper](https://github.com/openai/whisper) | 110.7k | MIT | `whisper/tokenizer.py` có dòng `"vi": "vietnamese"` | Dùng bản `large-v3` đa ngôn ngữ; các bản `.en` chỉ cho tiếng Anh |
| 2 | [QwenLM/Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR) | 3.7k | Apache-2.0 | Bảng ngôn ngữ có "Vietnamese (vi)" | Bản 1.7B và 0.6B; ví dụ trong README giả định có GPU |

## 3. Đã xem xét nhưng không đưa vào bảng

- **Kokoro** (đang dùng trong `npx hyperframes tts`): không có giọng tiếng Việt.
- **thinhlpg/vixtts-demo** (viXTTS): chỉ là bản demo suy luận, tác giả nói không còn bảo trì và không công bố mã tinh chỉnh.
  Model card (theo kết quả tìm kiếm) ghi giấy phép model công cộng của Coqui, vốn hạn chế thương mại.
- **phatjkk/SpeakIt_Vietnamese_TTS** (khoảng 101★) và **iconclub/zalo-tts**: theo kết quả tìm kiếm, cả hai phụ thuộc dịch vụ
  Zalo qua API, không phải model chạy cục bộ. Chưa mở trang để xác nhận.
- **k2-fsa/sherpa-onnx** (15.3k★, Apache-2.0): README không liệt kê tiếng Việt. Có nguồn bên thứ ba nhắc tới một model
  Zipformer tiếng Việt chạy trên sherpa-onnx, nhưng **chưa xác nhận từ nguồn chính thức**.
- **Meta MMS** và các model khác: chưa kiểm tra.

## 4. Nối vào HyperFrames

- **Giọng đọc.** Tạo mỗi cảnh một file `.wav`, đặt vào `videos/<tên>/assets/vo-1.wav`, `vo-2.wav`... Dùng thẻ
  `<audio id="vo-1" src="assets/vo-1.wav" data-start="0.5" data-duration="1.63" data-volume="1.3"></audio>`. Đo độ dài bằng
  `ffprobe`, rồi chỉnh `data-duration` của từng cảnh cho khớp. `id` là bắt buộc, thiếu thì audio bị câm khi render.
- **Phụ đề, bóc băng.** `npx hyperframes transcribe <file> --model large-v3 --language vi`. Model mặc định của lệnh này là
  `small.en`, chỉ dành cho tiếng Anh, nên phải truyền `--model large-v3` cho tiếng Việt. Lệnh này **chưa chạy thử** với tiếng Việt.
  Tùy chọn `--engine auto` dùng Parakeet nếu nó hỗ trợ ngôn ngữ đó; chưa kiểm tra Parakeet có tiếng Việt hay không.
- **Mạng.** Hầu hết model tải từ Hugging Face. Muốn dùng trong phiên cloud, thêm `huggingface.co` (và các tên miền CDN của nó)
  vào Allowed domains của môi trường.

## 5. Giấy phép và đạo đức khi dùng giọng

- Bản **phi thương mại**: v-tts, model của viet-tts, ChunkFormer (theo model card), model F5-TTS-Vietnamese (theo trang tổng
  hợp, chưa xác minh), giọng Piper ("cá nhân và nghiên cứu"). Đừng dùng cho video thương mại nếu chưa đọc model card.
- Chỉ clone giọng của người bạn có quyền sử dụng. README của VietVoice-TTS yêu cầu gắn nhãn nội dung giọng AI, và README của
  OmniVoice cấm mạo danh và lừa đảo. Hãy làm theo cả hai.
- Với dịch vụ trực tuyến như edge-tts, kiểm tra điều khoản của nhà cung cấp trước khi dùng cho nội dung thương mại.

## 6. Việc nên làm tiếp

1. Cho phép `huggingface.co` trong môi trường cloud.
2. Với 2–3 ứng viên (gợi ý: VoxCPM2 nếu có GPU, VieNeu-TTS nếu chỉ có CPU), tạo cùng một đoạn tiếng Việt rồi nghe thử.
3. Nhận dạng ngược đoạn đó bằng PhoWhisper để đo mức dễ hiểu, như đã làm dở với Kokoro.
4. Chọn một công cụ, rồi viết thành skill hoặc script gọi thống nhất để mọi video dùng cùng một cách.

## Lệnh cài (theo README, chưa chạy thử)

```bash
# TTS
pip install vieneu                                   # VieNeu-TTS; dùng: Vieneu().infer("...", voice="Phạm Tuyên")
pip install voxcpm                                   # VoxCPM2; batch: voxcpm batch --input in.txt --output-dir outs
pip install omnivoice                                # OmniVoice; omnivoice-infer --model k2-fsa/OmniVoice --text "..." --output a.wav
git clone https://github.com/nguyenvulebinh/VietVoice-TTS.git && cd VietVoice-TTS && pip install -e ".[cpu]"
python -m vietvoicetts "Xin chào các bạn!" output.wav --gender female --area northern

# STT
pip install -U openai-whisper                        # cần ffmpeg
pip install -U qwen-asr                              # Qwen3-ASR
pip install chunkformer                              # ChunkFormer (xem giấy phép model trước)
```

PhoWhisper (theo README, cần tải weights từ Hugging Face):

```python
from transformers import pipeline
transcriber = pipeline("automatic-speech-recognition", model="vinai/PhoWhisper-small")
text = transcriber(path_to_audio_with_sampling_rate_16kHz)["text"]
```
