# Team agent trên VPS: Claude giữ hai đầu, model miễn phí làm phần giữa

Hướng dẫn này cài bộ script `scripts/team/` lên VPS Hetzner CX33 (4 vCPU / 8 GB /
80 GB, đang chạy GitHub Actions runner). Lý do chọn thiết kế này nằm trong
[`docs/research/team-agent-model-mien-phi.md`](research/team-agent-model-mien-phi.md).

```text
Bạn ─ request.md
 │
 ▼
Claude Code (bạn tự chạy)  →  spec.md · tasks.md · acceptance.md      team check-spec
 │
 ▼
team run  (script điều phối, KHÔNG phải model)
 ├─ tester   model free A  → commit test         → gates phải FAIL
 ├─ coder    model free B  → commit              → gates (checkout sạch, offline)
 │                           sai thì thử lại ≤3 lần, đổi model, kèm log lỗi
 ├─ reviewer model free C  (repo chỉ đọc)        → prereview.md, 1 vòng sửa BLOCKER
 └─ pack                                          → audit-pack.md (≤1500 dòng)
 │
 ▼
Claude Code (bạn tự chạy)  →  verdict.md
   APPROVE → team push F12 → PR → CI trên runner → merge
   BLOCK   → team run F12 --from verdict   (tối đa 1 vòng audit thêm)
```

Hermes (Telegram) chỉ là nút bấm: "chạy F12", "F12 sao rồi". Toàn bộ thứ tự,
thử lại, đổi model, commit, gates và gói audit đều do `team.py` làm, vì đây là
việc tính được. Nhờ vậy, nếu cấu hình Hermes sai thì pipeline vẫn chạy được bằng SSH.

> Muốn làm video AI có tiếng (HyperFrames) thay vì code? Có team thứ ba, vẫn do Claude
> thiết kế và audit: [`docs/vps-team-video.md`](vps-team-video.md)
> (`setup-vps-team.sh --with-video`, lệnh `team-video`).

> Muốn Codex thay Claude làm thiết kế và audit? Có team thứ hai chạy cạnh team này:
> [`docs/vps-team-codex.md`](vps-team-codex.md) (`setup-vps-team.sh --with-codex`).

## 1. Ai là ai trên VPS

| User | Làm gì | Có quyền gì |
|---|---|---|
| bạn (`--admin`) | viết request, chạy `claude` để viết spec và audit | sudo; nhóm `team` (sửa được spec) |
| `team` | chạy mọi container worker | nhóm `docker`, sở hữu `/srv/team` |
| `hermes` (tuỳ chọn) | gateway Telegram | **chỉ** được `sudo -u team /usr/local/bin/team` với `status`, `check-spec`, `run`, `doctor`; không `push`, không `--force` |
| user của runner | chạy CI | script không đụng tới |

Claude chỉ đăng nhập dưới user của bạn. Không đặt `ANTHROPIC_API_KEY`, và không
đưa phiên đăng nhập Pro cho Hermes, OpenCode hay bất kỳ công cụ nào khác (lý do
nằm trong báo cáo nghiên cứu, mục điều khoản).

Code điều phối được cài vào `/opt/team`, thuộc root. `team` và `hermes` đều không
sửa được nó.

## 2. Cài đặt

```bash
git clone https://github.com/vohoailinh90/Video-AI.git
cd Video-AI
sudo ./scripts/team/setup-vps-team.sh --admin "$USER" --with-hermes
# đăng xuất rồi đăng nhập lại để nhóm `team` có hiệu lực
```

Script chạy lại được nhiều lần. Mỗi khi `git pull` bản mới, chạy lại nó để cập
nhật `/opt/team` và image. Script làm các việc sau:

- cài docker/git nếu thiếu;
- tạo mạng Docker `team-net` cho worker và service `team-egress` (iptables) để mạng đó chỉ ra được Internet; timer `team-egress-check` (20 giây một lần, chạy bằng root) hỏi lại iptables và subnet của `team-net`, rồi ghi bằng chứng vào `/run/team-egress.ok`. Trước mỗi container có mạng, conductor chạy lại chính kiểm tra đó ngay lúc đó (`sudo -n /usr/local/sbin/team-egress --check`, qua một luật sudoers duy nhất `/etc/sudoers.d/team-egress-check`, khớp đúng dòng lệnh đó và không nhận tham số nào khác) và chỉ khởi động khi luật còn nguyên và đúng mạng worker đang dùng. Kiểm tra không chỉ xem luật có tồn tại mà còn xem các luật DROP có đứng **đầu** `DOCKER-USER` và `INPUT` hay không (một luật ACCEPT nằm trước sẽ quyết định gói tin trước), và `FORWARD` có còn bắt đầu bằng lệnh nhảy vào `DOCKER-USER` hay không (mất lệnh nhảy đó thì các luật DROP trong `DOCKER-USER` không bao giờ được áp dụng). Kiểm tra chỉ nhìn bảng `filter` của iptables; luật nftables viết trực tiếp bên ngoài lớp tương thích iptables thì nó không thấy. Kiểm tra thất bại thì dừng luôn các container đang chạy trên `team-net`; timer (`team-egress --maintain`) đặt lại luật lên đầu rồi kiểm tra lại, nên luật bị xoá hay bị chen lên trên sẽ tự lành trong vòng 20 giây. `doctor` chỉ đọc bằng chứng của timer (dưới 90 giây);
- thêm 4 GB swap nếu máy chưa có;
- tạo user và thư mục;
- tạo wrapper `/usr/local/bin/team`;
- chép `team.env` và `workers.env` mẫu vào `/srv/team` (không bao giờ ghi đè);
- build image `team-worker`;
- với `--with-hermes`: tạo user `hermes` cùng một luật sudoers duy nhất (đã kiểm bằng
  `visudo`), rồi chép skill vào `~hermes/.hermes/skills/team-pipeline/`.

### Key cho worker

```bash
sudo -u team nano /srv/team/workers.env      # mode 600, chỉ user team đọc được
```

| Biến | Lấy ở đâu | Ghi chú |
|---|---|---|
| `OPENROUTER_API_KEY` | openrouter.ai → Keys | Tạo key **riêng**, đặt credit limit thấp. Gói free: khoảng 50 lượt/ngày cho mọi model `:free`. Nạp một lần 5 credit (5 USD, theo thông báo lỗi của OpenRouter tháng 10/2026) nâng lên 1.000 lượt/ngày. |
| `GOOGLE_GENERATIVE_AI_API_KEY` | aistudio.google.com → API keys | Free chỉ còn model Flash/Flash-Lite, và có thể dùng dữ liệu để huấn luyện. |
| `MISTRAL_API_KEY` | console.mistral.ai, gói Experiment (free) | Giả định là có huấn luyện. |
| `GROQ_API_KEY`, `DEEPSEEK_API_KEY` | tuỳ chọn | DeepSeek trả phí, rất rẻ ngoài giờ cao điểm. |
| `NVIDIA_API_KEY` | build.nvidia.com → API Keys (tuỳ chọn) | Gói dùng thử miễn phí, giới hạn số lượt mỗi phút. Hợp làm model dự phòng cuối khi hết quota free ở nơi khác. Coi như prompt có bị ghi log: chỉ dùng cho repo không bí mật. |

Mỗi container chỉ nhận đúng key của provider mà model của nó dùng. Nhưng code do
model viết chạy ngay cạnh key đó, nên hãy coi mọi key trong file này là có thể lộ.
Vì vậy mới cần key riêng có hạn mức thấp.

### Chọn model cho từng vai

```bash
team models openrouter --free      # danh sách thay đổi liên tục, xem lại mỗi tuần
team models google
team models mistral
team models nvidia                 # nếu có NVIDIA_API_KEY
nano /srv/team/team.env            # TEAM_MODELS_TESTER / _CODER / _REVIEWER
team doctor --ping                 # kiểm tra key, quyền file, model còn tồn tại và OpenCode có chạy được không
```

Quy tắc: tester, coder và reviewer dùng ba họ model khác nhau. `doctor` sẽ cảnh
báo nếu coder và reviewer cùng họ. Model đầu tiên là chính, các model sau là dự
phòng. Nếu repo riêng tư, chỉ chọn endpoint không huấn luyện trên dữ liệu (xem
báo cáo nghiên cứu, mục quyền riêng tư).

### Repo riêng tư: deploy key cho user team

```bash
sudo -u team mkdir -p -m 700 /var/lib/team/.ssh
sudo -u team ssh-keygen -t ed25519 -N "" -f /var/lib/team/.ssh/id_ed25519
sudo cat /var/lib/team/.ssh/id_ed25519.pub
# GitHub → repo → Settings → Deploy keys → Add, tick "Allow write access" (cần cho `team push`)
sudo -u team ssh -T git@github.com     # chấp nhận host key một lần
```

Deploy key chỉ có quyền trên đúng một repo. Hãy bật branch protection cho `main`,
để mọi thay đổi đều phải đi qua PR và CI.

### Claude Code (dưới user của bạn)

```bash
curl -fsSL https://claude.ai/install.sh | bash
claude          # đăng nhập bằng tài khoản Pro
```

### Hermes (tuỳ chọn, để điều khiển qua Telegram)

```bash
sudo -iu hermes
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
hermes setup    # "bộ não" = Gemini Flash-Lite (key AI Studio riêng) hoặc OpenRouter :free
# ~/.hermes/.env: TELEGRAM_BOT_TOKEN=... (từ @BotFather), TELEGRAM_ALLOWED_USERS=<id Telegram của bạn>
hermes doctor
exit
```

Tham khảo cấu hình trong `scripts/team/hermes/config.example.yaml`. Gateway chạy
nền theo docs Hermes là `hermes gateway install --system`, cần sudo; trước khi
chạy, kiểm tra đường dẫn bằng `sudo -iu hermes which hermes`. Mọi khoá cấu hình
Hermes trong repo này đều **chưa được kiểm chứng trên máy thật**. Khi file mẫu và
`hermes doctor` nói khác nhau, hãy làm theo Hermes.

## 3. Quy trình một feature (ví dụ F12)

```bash
team new F12 --repo git@github.com:vohoailinh90/<repo>.git
nano /srv/team/work/F12/request.md                 # viết yêu cầu, tiếng Việt cũng được
```

**Claude lần 1, viết spec** (khoảng 10–20 phút quota):

```bash
cd /srv/team/work/F12 && claude
#   /model sonnet          (việc rủi ro: /model opusplan)
#   dán nội dung của:  team prompt claude-spec F12
#   Claude viết spec.md, tasks.md, acceptance.md rồi tự chạy team check-spec F12
#   xong thì /exit
```

**Phần giữa, không tốn token Claude:**

```bash
team run F12 --detach          # hoặc nhắn Telegram: "chạy F12"
team status                    # hoặc: "F12 sao rồi"
tail -f /srv/team/work/F12/out/run.log
```

**Claude lần 2, audit** (đọc đúng một file):

```bash
cd /srv/team/work/F12 && claude
#   /model sonnet
#   dán nội dung của:  team prompt claude-audit F12
#   Claude viết verdict.md
```

- `VERDICT: APPROVE` (dòng `VERDICT:` đầu tiên trong `verdict.md` quyết định) → `team push F12`
  → mở PR từ nhánh `team/F12` trên GitHub → CI chạy trên runner → merge. `team push` từ chối
  nếu HEAD đã đổi sau khi đóng gói, hoặc nếu `verdict.md` cũ hơn gói audit.
- `VERDICT: BLOCK` → `team run F12 --from verdict --detach` → audit lại. Chỉ được thêm
  **một** vòng audit. Nếu vẫn BLOCK thì bạn tự quyết định trong Claude Code.

Mẹo giữ quota Pro:

- Gom việc viết spec của vài feature vào cùng một khoảng một giờ, vì cache sống 1 giờ.
- Audit bằng Sonnet. Không cho Claude đọc cả repo.
- `/clear` sau mỗi việc. Xem `/usage` để biết phần nào tốn.

## 4. Các lệnh

| Lệnh | Việc |
|---|---|
| `team new ID --repo URL [--base main]` | clone repo, tạo nhánh `team/ID`, tạo template và `repo-map.txt` |
| `team check-spec ID` | spec ≤120 dòng; mỗi task có `Files:`, `Do not touch:`, `Verify:`; acceptance có lệnh; không còn `TODO(` |
| `team run ID [--from tester\|coder\|review\|pack\|verdict] [--detach]` | chạy pipeline; khi bị chặn, chạy lại sẽ tiếp tục từ bước hỏng |
| `team work tester\|coder\|reviewer ID [--model M]` | chạy riêng một vai một lần |
| `team gates ID` / `team pack ID [--force]` | chạy riêng gates hoặc đóng gói audit (từ chối nếu đang có pipeline khác chạy, vì cùng ghi `gates.log`/`audit-pack.md`). `pack` và `push` chỉ chấp nhận `gates.log` của đúng commit HEAD, đúng các lệnh trong `acceptance.md` hiện tại và có kết quả `RESULT: PASS` |
| `team status [ID]` | trạng thái mọi feature |
| `team prompt NAME ID` | in prompt (`claude-spec`, `claude-audit`, `tester`, …) |
| `team models PROVIDER [--free]` | liệt kê model id provider đang có |
| `team doctor [--ping]` | docker, image, quyền `workers.env`, key, họ model, model bị rút |
| `team push ID` | push nhánh, chỉ khi `verdict.md` là APPROVE |

## 5. Bảo mật: những gì được đảm bảo và những gì không

Có test và mutation check canh giữ (`tests/test_team.py`, `tests/mutations/team.yaml`):

- **Key:** mỗi container chỉ nhận key của provider model đó. Key không bao giờ nằm trên
  dòng lệnh. Gates không nhận key nào.
- **Container:** `--cap-drop ALL`, `no-new-privileges`, root filesystem chỉ đọc,
  `--pids-limit 256`, giới hạn RAM/CPU, chạy bằng uid của `team`.
- **Git:**
  - Worker không thấy thư mục `.git` thật (bị che bằng tmpfs).
  - Git trên host tắt hooks, fsmonitor và `ext::`, nên code do model cài vào repo
    không chạy được trên host.
- **Phân quyền đọc/ghi:**
  - Reviewer chỉ đọc được repo.
  - File bàn giao (spec, tasks, acceptance) được mount chỉ đọc, nên coder không dời
    được "cột gôn".
- **Gates:** chạy trên bản checkout sạch của HEAD, không có mạng (mặc định).
- **Mạng của worker:** worker chạy trên mạng `team-net`, ra Internet được (để gọi API).
  iptables chặn mọi đường vào chính VPS (runner, Hermes), các dải IP nội bộ và dịch vụ
  metadata `169.254.169.254` của cloud.
- **Hermes:** chỉ được `status`, `check-spec`, `run` và `doctor`. Không được `push`, `--force`,
  `new` hay `work`. Giới hạn này nằm trong wrapper do root sở hữu, không nằm trong prompt.
- **Push:** `team push` chỉ chạy khi `verdict.md` là APPROVE cho đúng HEAD đã đóng gói, và push
  chính commit đó theo SHA (không theo tên nhánh), trong lúc giữ khoá pipeline. Cái nó tin nằm
  **ngoài** thư mục feature, trong `<TEAM_HOME>/seals/<id>.json` (thư mục 0750, chỉ conductor ghi):
  SHA của HEAD, SHA-256 của `audit-pack.md` và digest của `spec.md`/`acceptance.md` lúc đóng gói.
  Một lead làm theo chỉ dẫn chèn trong gói có thể sửa mọi thứ trong thư mục feature của nó (repo,
  `state.json`, `gates.log`), nhưng không sửa được seal, nên push từ chối commit, gói hay spec đã đổi.
  Thư mục gốc của mỗi team (`/srv/team`, `/srv/team-codex`, `/srv/team-video`) là `2750`: tài khoản của bạn
  (nhóm `team`) đọc và vào được nhưng không thêm, đổi tên hay xoá được gì ngay trong đó, nên không thay được cả thư mục
  `seals/`; chỉ `work/` bên dưới là `2770`. Chạy lại `setup-vps-team.sh` để áp dụng cho bản đã cài. Đổi quyền thư mục gốc
  không động tới thứ đã nằm trong đó, nên với bản cài từ lúc thư mục còn ghi được cho nhóm, setup còn kiểm tra `seals/`:
  chỉ giữ nếu đúng là thư mục thật của user `team`, mode 750, chỉ chứa file thường; còn lại (một symlink trỏ vào
  thư mục lead ghi được, hay thư mục do lead tạo) thì xoá và để conductor tạo lại, rồi phải `pack` và audit lại các feature
  đã đóng dấu trong đó. Chính conductor cũng từ chối ghi hoặc tin một seal nằm trong `seals/` không phải thư mục thường
  của chính nó, kể cả khi chưa chạy lại setup.
- **Dung lượng:** log của một container chỉ ghi tối đa `TEAM_LOG_MAX_BYTES` (cho cả một lần chạy gates);
  thư mục làm việc `/work` mà worker ghi vào không được lớn thêm quá `TEAM_WORKSPACE_GROWTH_BYTES`
  (container bị dừng, lần thử bị bỏ; còn một lần đo cuối khi container thoát, nên ghi nhanh rồi thoát giữa hai lần đo định kỳ cũng bị bắt).
  Trước khi `git add -A` (ghi thêm một bản mỗi file đổi dưới dạng object của git), conductor kiểm tra file đổi cộng `TEAM_MIN_FREE_BYTES`
  có vừa với dung lượng trống không; không vừa thì bỏ lần thử và dừng. Danh sách đường dẫn đổi chỉ được đọc tới vài MB (quá thì dừng với
  "too many paths"), và file bàn giao cho worker (`spec.md`, `repo-map.txt`, ...) được mở không theo symlink rồi sao chép vào thư mục
  tạm trong team home để mount, nên một symlink trỏ tới `workers.env` không bao giờ được gắn vào container. Hai giới hạn này giữ một vòng lặp hay một file khổng lồ khỏi làm đầy ổ đĩa của VPS. Container chạy với `--log-driver none`
  (Docker không giữ thêm một bản log `json-file` không xoay vòng của output), và diff đưa cho reviewer hay vào gói audit chỉ được đọc
  tới `TEAM_PACK_MAX_BYTES` (hoặc 20 MB với `pack --force`) rồi dừng `git`, nên vài file lớn không bị nạp nguyên vào bộ nhớ.
- **Thay đổi nhạy cảm:** gói audit liệt kê riêng các thay đổi ở `.github/` (CI chạy ngay trên
  VPS này), `CLAUDE.md`, `AGENTS.md`, `.claude/`, và lockfile phụ thuộc. Diff của lockfile nằm
  trong gói (không bị lược), vì CI trên VPS cài gói theo chính lockfile đó.
- **`team-net` có sẵn:** nếu đã có mạng `team-net` với subnet khác, setup dừng lại thay vì báo
  thành công mà luật iptables không phủ được.
- **Test bị yếu đi:** test nào bị sửa sau bước tester đều hiện riêng trong gói audit.
- **Giới hạn audit:** gói audit ≤1500 dòng; chỉ một vòng audit thêm.

Không đảm bảo, cần bạn tự quản:

- Worker vẫn ra Internet được, nên code do model viết có thể gửi key ra ngoài. Dùng
  key riêng có hạn mức thấp.
- User `team` thuộc nhóm `docker`, tức là tương đương root trên VPS. Ranh giới thật
  là: chỉ `team.py` (code root-owned) ra lệnh cho docker, còn Hermes chỉ gọi được
  `team`.
- **Phiên audit của lead Claude chạy bằng chính tài khoản của bạn** (team Claude và team video; Codex thì có sandbox
  riêng, xem `docs/vps-team-codex.md`). Gói audit chứa chữ do model miễn phí viết: nếu một chỉ dẫn chèn trong đó
  qua được lead, phiên đó làm được mọi thứ bạn làm được, kể cả `team push --force` hay `git push` thẳng.
  Seal và quyền thư mục chặn việc xuất bản một commit/gói/spec khác dưới lần APPROVE, không chặn một phiên đã bị
  chiếm quyền dùng chính quyền của bạn. Ba lớp giảm rủi ro, theo thứ tự từ yếu đến mạnh:
  (1) `team push --force` hỏi xác nhận trên terminal (`/dev/tty`), nên không chạy được từ script hay shell của agent,
  nhưng một agent tự mở pseudo-terminal thì vẫn vượt qua; (2) khởi động lead bằng
  `claude --settings /opt/team/lead-settings.example.json`: chặn `team push`, `git push`, `sudo`, `gh` và mọi lệnh
  có `--force` (chỉ là hàng rào, không phải sandbox); (3) lớp thật: chạy phiên audit dưới một tài khoản Unix riêng
  không có `sudo`, không có khoá SSH/token push và không thuộc nhóm `team` có quyền ghi, còn bạn tự `team push` ở
  terminal của mình. Chỉ lớp (3) là ranh giới.
- Free tier có thể huấn luyện trên code của bạn.
- Runner GitHub chạy chung máy: nếu user của runner thuộc nhóm `docker`, job CI cũng
  tương đương root. Xem `docs/ci-runner-mode.md` trong repo claude-agent-routing-template.

## 6. Xử lý sự cố

| Triệu chứng | Làm gì |
|---|---|
| vim báo `E510: Can't make backup file` khi lưu `team.env` | thư mục gốc của team không cho nhóm ghi (để bảo vệ seal), mà vim mặc định đổi tên file cũ để sao lưu: dùng `nano`, hoặc trong vim `:set backupcopy=yes` rồi lưu lại |
| `doctor`: "not offered by … any more" | model free đã bị rút: chọn lại bằng `team models`, sửa `team.env` |
| `doctor`: "not in OpenCode's model catalog" | provider đã có model nhưng danh mục của OpenCode (models.dev) chưa có, worker không chạy được: chọn model khác, vài ngày sau thử lại |
| worker thoát ngay, log báo lỗi config OpenCode | phiên bản OpenCode bạn cài không nhận một khoá trong `scripts/team/opencode.json`: bỏ khoá đó, chạy lại setup. Kiểm tra: `docker run --rm team-worker opencode --version` |
| "another pipeline is running" | mỗi lúc chỉ chạy một pipeline (máy 8 GB, dùng chung với CI); chờ hoặc xem `team status` |
| `blocked: …` | xem `out/*.log` và `gates.log`, sửa spec hoặc model, rồi `team run ID` để chạy tiếp |
| `BLOCKED: ... egress ...` / worker không gọi được API | conductor không khởi động container có mạng khi `team-egress` tắt, khi `sudo -n team-egress --check` thất bại (luật iptables đã bị xoá, `iptables -F`, firewall reload, một luật khác bị chèn lên trước luật DROP, hoặc thiếu luật sudoers: chạy lại setup), hoặc khi `TEAM_WORKER_NETWORK`/`TEAM_GATES_NETWORK` không phải mạng đã được kiểm tra (chỉ `team-net` có luật); chạy lại `setup-vps-team.sh`. Kiểm tra: `sudo /usr/local/sbin/team-egress --check`, `journalctl -u team-egress-check`, `docker network inspect team-net`. Nếu bạn gọi model qua proxy trong mạng nội bộ, hãy sửa `/usr/local/sbin/team-egress`. |
| `BLOCKED: every coder model run failed, last error: ... free-models-per-day` | hết quota `:free` trong ngày của OpenRouter: chờ sang ngày, nạp 5 credit, hoặc thêm model của provider khác vào `TEAM_MODELS_CODER` |
| test cần cài thư viện | đặt `TEAM_GATES_SETUP` trong `team.env` (bước này có mạng, các lệnh gates thì không) |
| pack quá dài | tách feature nhỏ hơn, hoặc `team pack ID --force` (tốn quota Claude hơn) |
| Gemini báo "User location is not supported" | Google kiểm tra theo quốc gia của tài khoản: chuyển vai đó sang provider khác |

## 7. Chưa kiểm chứng được trên máy thật

Session viết bộ script này không có Docker, không có mạng tới các provider và
không có Hermes. Vì vậy những điểm sau cần kiểm khi chạy lần đầu, tốt nhất với
một feature nhỏ trên repo thử nghiệm:

- **OpenCode:**
  - tên package npm `opencode-ai` và cách `opencode run --model` in kết quả;
  - các khoá `permission` trong `opencode.json`;
  - tên biến môi trường key của từng provider (bảng `PROVIDER_KEYS` trong `team.py`;
    sửa bằng `TEAM_KEY_<PROVIDER>=<VAR>` trong `team.env`).
- **Hermes:** mọi khoá cấu hình và đường dẫn thư mục skills.
- **Hạn mức free tier:** chúng thay đổi hằng tháng; số liệu và nguồn ở báo cáo nghiên cứu.

Phần còn lại đã có test, chạy được trong CI không cần Docker: thứ tự các bước,
thử lại, đổi model, commit, gates, gói audit, cách ly key, chặn hook git.
