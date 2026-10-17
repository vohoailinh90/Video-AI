# Team video trên VPS: Claude làm kiến trúc sư, model miễn phí dựng video có tiếng

Đây là team thứ ba chạy cạnh [`docs/vps-team.md`](vps-team.md) (team code) và
[`docs/vps-team-codex.md`](vps-team-codex.md). Cùng một conductor
(`scripts/team/team.py`), cùng user `team`, mạng `team-net` và khoá pipeline. Khác ở
**việc làm ra**: không phải code mà là một video HyperFrames (HTML → MP4) **có
audio**, dựng cho repo [`vohoailinh90/Video-AI`](https://github.com/vohoailinh90/Video-AI).

Video-AI chứa bộ skill HyperFrames (`.claude/skills/`, bản upstream được khoá bởi
`skills-lock.json`) và `CLAUDE.md` ghi quy ước của repo. Team theo đúng các quy ước đó: mỗi
video là một thư mục `videos/<id>/` tạo bằng `hyperframes init <id> --example blank` (giữ
nguyên `AGENTS.md` và `CLAUDE.md` mà `init` sinh ra), render nằm trong `videos/<id>/renders/`
và không bao giờ vào git, GSAP được vendor thay vì nạp từ CDN, và không ai sửa tay `.claude/skills/`.

```text
Bạn ─ request.md  (chủ đề, khán giả, độ dài, ngôn ngữ giọng, nhạc)
 │
 ▼
Claude Code (bạn tự chạy)  →  spec.md (brief + kịch bản đọc) · tasks.md · acceptance.md
 │                              team-video check-spec
 ▼
team-video run  (script điều phối, KHÔNG phải model)
 ├─ tester   model free A → videos/<id>.expected.json   → gates phải FAIL (chưa có video)
 ├─ coder    model free B → cảnh HTML + giọng đọc + SFX → gates (checkout sạch, KHÔNG mạng)
 │                          lint · check · render draft · video_gates.py
 │                          sai thì thử lại ≤3 lần, đổi model, kèm log lỗi
 ├─ reviewer model free C (repo chỉ đọc) → prereview.md, 1 vòng sửa BLOCKER
 └─ pack                                  → audit-pack.md (≤1500 dòng)
 │
 ▼
Claude Code (bạn tự chạy)  →  verdict.md
   APPROVE → team-video push V01 → PR → merge → bạn render bản delivery
   BLOCK   → team-video run V01 --from verdict   (tối đa 1 vòng audit thêm)
```

## 1. Ai làm gì, và cái gì do máy phán

| Việc | Ai | Ghi chú |
|---|---|---|
| Brief, kịch bản đọc, danh sách cảnh | **Claude** (đăng nhập Pro của bạn) | Ghi vào `spec.md`: mỗi cảnh có file, giây, chữ trên màn hình, lời đọc |
| `expected.json` (độ dài, kích thước, fps, ngưỡng loudness) | tester (model free) | Chỉ lấy số từ spec; sai/thừa khoá là lỗi |
| Cảnh HTML + GSAP, giọng đọc, SFX, caption | coder (model free) | Đọc skill HyperFrames có sẵn trong repo Video-AI |
| Đọc diff, đối chiếu spec | reviewer (model free) | Không xem/nghe được video |
| **Có tiếng không, to/nhỏ, im lặng, độ dài, kích thước** | **`video_gates.py`** | Tính được → script, không để model phán |
| Chữ đúng spec, kịch bản tự nhiên, test không bị nới | Claude (audit) | Chỉ đọc `audit-pack.md` |

`scripts/team/video/video_gates.py` chạy trên bản render draft và kiểm bằng
ffprobe/ffmpeg:

| Kiểm tra | Mặc định |
|---|---|
| có luồng video; có luồng audio | bắt buộc (`audio.required`) |
| độ dài (cả container lẫn luồng hình riêng) | `duration_s` ± 1,5 s |
| `width`, `height`, `fps` | đúng bằng spec (fps ± 0,05) |
| audio dài ≥ 90% video | `audio.min_coverage` |
| loudness tích hợp | −30…−10 LUFS (nên đặt quanh −16 theo spec) |
| true peak (méo/clipping) | ≤ −0,1 dBFS |
| khoảng im lặng dài nhất | ≤ 4 s |

Đây là heuristic, không phải thính giác: loudness dùng gating tương đối của EBU R128 và
`silence gap` chỉ đếm quãng im lặng dài hơn ngưỡng, nên một video chỉ có vài giây tiếng to xen
nhiều quãng im ngắn vẫn có thể qua. Một track hoàn toàn câm, thiếu, méo hay quá to thì không
qua được. Phần còn lại là việc của Claude khi audit (cửa sổ `audio` bị nới là BLOCK).

Có 13 mutation check cho script này (`tests/mutations/video_gates.yaml`).

## 2. Audio miễn phí: được gì, không được gì

- **Giọng đọc local (Kokoro, chạy offline trong image):** tiếng Anh, Nhật, Trung, Tây
  Ban Nha, Pháp, Hindi, Ý, Bồ Đào Nha (`hyperframes tts --list`).
- **Tiếng Việt: Kokoro không có.** Hãy tự thu âm, hoặc tạo bằng công cụ TTS tiếng Việt
  bên ngoài, đặt file vào `videos/<id>.inputs/` (cạnh, không phải trong, thư mục dự án: `hyperframes init`
  từ chối thư mục không rỗng) rồi commit lên nhánh trước khi chạy, và ghi tên từng file trong `request.md`. Spec
  sẽ chỉ định file nào cho cảnh nào, coder chỉ ghép và cân âm. Danh sách công cụ TTS/STT
  tiếng Việt (kèm giấy phép, chưa chạy thử) ở [`docs/vietnamese-audio.md`](vietnamese-audio.md);
  team không gọi chúng: bạn tạo clip bên ngoài rồi đặt vào `videos/<id>.inputs/`, và ghi
  giấy phép của model trong `request.md` (audit BLOCK file nhị phân không có giấy phép).
- **Không bật TTS cần key (Gemini, HeyGen, ElevenLabs):** mỗi container chỉ nhận key
  của provider model nó chạy, và code do model viết chạy ngay cạnh key. Đưa thêm một key
  TTS vào worker là phá ranh giới đó. HeyGen cũng cần đăng nhập OAuth tương tác.
- **SFX:** 19 file có sẵn trong `.claude/skills/media-use/audio/assets/sfx/`.
- **Nhạc nền:** chỉ file bạn tự thêm (có giấy phép), hoặc không nhạc. Team không tải nhạc.
- **Cân âm:** coder chuẩn hoá giọng về khoảng −16 LUFS bằng `ffmpeg loudnorm`; nhạc nền
  `data-volume` 0,15–0,25; gate bắt nếu quá to, méo hay có đoạn im lặng dài.

## 3. Cài đặt

```bash
git clone https://github.com/vohoailinh90/Video-AI.git
cd Video-AI
sudo ./scripts/team/setup-vps-team.sh --admin "$USER" --with-video [--with-hermes]
# đăng xuất rồi đăng nhập lại để nhóm `team` có hiệu lực
```

`--with-video` thêm: thư mục `/srv/team-video`, lệnh `team-video` (cùng wrapper, đổi tên),
image `team-video-worker:latest` (Chrome, ffmpeg, HyperFrames 0.8.166, GSAP 3.14.2, Kokoro;
khoảng 1,5 GB, build vài phút), `team.env` riêng (RAM 4 GB, `/dev/shm` 1 GB, `/tmp` 2 GB)
và `workers.env` riêng. Với `--with-hermes`: thêm một luật sudoers riêng và skill
`team-video-pipeline`. Dùng chung khoá pipeline với hai team kia: mỗi lúc chỉ chạy một
pipeline (máy 8 GB còn chạy CI).

```bash
sudo -u team nano /srv/team-video/workers.env     # key worker; KHÔNG bao giờ để key Claude
team-video models openrouter --free               # chọn model cho từng vai, rồi:
nano /srv/team-video/team.env
team-video doctor --ping --smoke
```

`doctor --smoke` là bước quan trọng nhất lần đầu: trong **đúng container đã harden**
(không capability, rootfs chỉ đọc, `/dev/shm` nhỏ, không mạng) nó render một video 3 giây
có tiếng rồi chấm bằng `video_gates.py`, và tổng hợp một câu bằng Kokoro. Render lỗi là
`PROBLEM`; giọng Kokoro lỗi chỉ là ghi chú (bạn vẫn dùng được file audio tự cung cấp).

Cài Claude Code dưới user của bạn như trong `docs/vps-team.md`; không đặt `ANTHROPIC_API_KEY`.

## 4. Quy trình một video (ví dụ V01)

```bash
team-video new V01 --repo git@github.com:vohoailinh90/Video-AI.git
nano /srv/team-video/work/V01/request.md           # chủ đề, khán giả, độ dài 30–90 s, giọng, nhạc
```

Có file audio tự cung cấp (bắt buộc với tiếng Việt)? Đưa vào **trước** `team-video run`, và phải commit,
vì khi một vai thất bại conductor xoá mọi file chưa commit (lệnh này chưa được chạy thử trên VPS):

```bash
cd /srv/team-video/work/V01/repo && mkdir -p videos/V01.inputs && cp ~/clips/vo-*.wav videos/V01.inputs/
sudo -u team git add videos/V01.inputs && sudo -u team git commit -m "inputs for V01"
```

`team-video push` cần deploy key có quyền ghi vào Video-AI (cách tạo ở mục "Repo riêng tư"
trong `docs/vps-team.md`; dùng user `team`, thư mục `/var/lib/team/.ssh`) và nên bật branch
protection cho `main`.

**Claude lần 1, viết brief** (đọc `hyperframes-core` và `narration.md` trong repo):

```bash
cd /srv/team-video/work/V01 && claude
#   /model sonnet
#   dán nội dung của:  team-video prompt video-spec V01
#   Claude viết spec.md, tasks.md, acceptance.md rồi tự chạy team-video check-spec V01
```

Spec phải nêu **tổng giây, rộng×cao, fps, loudness** vì tester biến đúng các số đó thành
`expected.json`; số nào thiếu là một kiểm tra không bao giờ chạy.

**Phần giữa, không tốn token Claude:**

```bash
team-video run V01 --detach        # hoặc nhắn Telegram: "chạy V01"
team-video status
tail -f /srv/team-video/work/V01/out/run.log
```

**Claude lần 2, audit:** `team-video prompt video-audit V01` → `verdict.md`.
`APPROVE` → `team-video push V01` → mở PR từ nhánh `team-video/V01` → merge.
`BLOCK` → `team-video run V01 --from verdict --detach` (một vòng thêm).

**Render bản chính thức** (gate chỉ render draft; MP4 không bao giờ vào git):

```bash
cd ~/Video-AI && git pull && cd videos/V01
npx hyperframes render --quality delivery --output ~/V01.mp4
```

Làm trên máy bạn, hoặc trong image trên VPS:
`docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home --tmpfs /tmp:exec,size=2g --shm-size 1g -v "$PWD":/work -w /work/videos/V01 team-video-worker:latest hyperframes render --quality delivery --output /work/renders/V01.mp4`
(lệnh docker này chưa được chạy thử).

Thời gian đo được trên sandbox 4 vCPU: video 5 s 1080p30 ở chất lượng draft render hết
khoảng 6,5 s, nên bản 60 s mất khoảng 1–2 phút cho mỗi lần chạy gate.

## 5. Điều đã kiểm và chưa kiểm

**Đã chạy thật** (HyperFrames 0.8.166, ffmpeg 6.1, Chrome headless shell, Linux):
`hyperframes lint` → `check` → `render --quality draft` → `video_gates.py` trên project
`video/smoke`, **trong network namespace rỗng** (tức là offline như gates), đều pass cả 10
kiểm tra. Mặc định `hyperframes init` nạp GSAP từ CDN, nên team bắt buộc để GSAP trong
`assets/vendor/gsap.min.js` (image có sẵn bản sao ở `/usr/local/share/team-video/`) và
cấm mọi URL, web font, ảnh từ xa. hơn 1050 test và 29 mutation check riêng cho team video canh phần conductor, gate,
wrapper và setup.

**Chưa kiểm được ở session viết bộ này** (không có Docker chạy container, không có VPS):
- build `Dockerfile.video` và Chrome chạy dưới `--cap-drop ALL`, `no-new-privileges`, rootfs chỉ đọc;
  nếu `doctor --smoke` báo render lỗi, đó là chỗ cần chỉnh trước tiên;
- Kokoro trong image: trên sandbox pip wheel `espeakng-loader` báo thiếu dữ liệu espeak;
  image cài thêm `espeak-ng` hệ thống nhưng chưa được thử, `doctor --smoke` sẽ cho biết;
- model miễn phí có viết được cảnh GSAP đủ đẹp không: lần đầu hãy kỳ vọng Claude BLOCK vài lần;
- Hermes, và mọi key cấu hình của OpenCode (xem mục 7 trong `docs/vps-team.md`).

## 6. Bảo mật

Giữ nguyên mô hình của `docs/vps-team.md` (key riêng từng provider, `--cap-drop ALL`,
`.git` bị che, handoff chỉ đọc, Hermes chỉ `status/check-spec/run/doctor`, push theo SHA đã
audit). Riêng team video:
- `video_gates.py` và smoke project nằm trong image, thuộc root: coder không sửa yếu được gate;
- `expected.json` do tester viết; coder bị cấm sửa, và sửa sau bước tester sẽ hiện trong
  mục "Test files changed after the tester commit" của gói audit;
- `renders/`, `snapshots/` và `.hyperframes/` không bao giờ được commit (khớp `.gitignore` của Video-AI);
  `AGENTS.md` và `CLAUDE.md` của từng dự án chỉ được là bản `hyperframes init` viết ra, thêm chỉ dẫn nào là BLOCK; mọi file nhị phân (audio, ảnh,
  font) hiện trong "Binary files changed" và phải có trong spec cùng giấy phép;
- `.claude/` (skill HyperFrames) là đường dẫn nhạy cảm: đổi mà spec không yêu cầu là BLOCK;
- gates không có mạng; `npm_config_offline=true` để `npx` không lặng lẽ tải gì về.

## 7. Xử lý sự cố

| Triệu chứng | Làm gì |
|---|---|
| `doctor`: "TEAM_IMAGE is the code team's image" | đặt `TEAM_IMAGE=team-video-worker:latest` trong `/srv/team-video/team.env` |
| `doctor`: "TEAM_WORKER_SHM is empty" | đặt `TEAM_WORKER_SHM=1g` (Chrome sập với `/dev/shm` 64 MB) |
| `smoke render failed` | xem dòng cuối được in; thử `docker run` thủ công với cùng cờ; Chrome thường cần thêm cờ sandbox hoặc `--shm-size` |
| `smoke narration failed` | Kokoro không chạy trong image: dùng file audio tự cung cấp, hoặc sửa espeak trong `Dockerfile.video` |
| gate `loudness`/`true peak` FAIL | tiếng quá to/nhỏ hoặc méo: coder chuẩn hoá lại (`loudnorm`); đừng nới `expected.json` |
| gate `audio stream` FAIL | thiếu `id` trên `<audio>` (render sẽ câm), hoặc không có audio nào được đặt |
| gate `video duration` FAIL | hình dừng sớm hơn tiếng/khung: cảnh cuối thiếu `data-duration` hoặc timeline ngắn hơn audio |
| gate `silence gap` FAIL | cảnh dài hơn giọng đọc: chỉnh độ dài cảnh theo audio thật |
| `check` báo lỗi mạng/CDN | có URL ngoài (GSAP, font, ảnh): đưa file vào repo |
| "another pipeline is running" | chỉ một pipeline một lúc cho cả ba team; chờ hoặc xem `team-video status` |
