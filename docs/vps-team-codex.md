# Team agent thứ hai trên VPS: Codex giữ hai đầu, model miễn phí làm phần giữa

Đây là team thứ hai chạy cạnh team Claude trong [`docs/vps-team.md`](vps-team.md).
Cùng một conductor (`scripts/team/team.py`), cùng worker model miễn phí, cùng
image, user và mạng `team-net`. Chỉ khác **ai thiết kế và audit**: ở đây là Codex,
chạy bằng hạn mức ChatGPT của bạn, thay cho Claude.

```text
Bạn ─ request.md
 │
 ▼
Codex (bạn tự chạy)  →  spec.md · tasks.md · acceptance.md      team-codex check-spec
 │
 ▼
team-codex run  (script điều phối, KHÔNG phải model)
 ├─ tester   model free A  → gates phải FAIL
 ├─ coder    model free B  → gates (checkout sạch, offline), thử lại ≤3 lần
 ├─ reviewer model free C  (repo chỉ đọc)  → prereview.md
 └─ pack                                    → audit-pack.md (≤1500 dòng)
 │
 ▼
Codex (bạn tự chạy)  →  verdict.md
   APPROVE → team-codex push F12 → PR → CI → merge
   BLOCK   → team-codex run F12 --from verdict   (tối đa 1 vòng audit thêm)
```

Phần giữa, gates, gói audit, giới hạn container và key đều giống hệt team Claude
và đã có test: đọc `docs/vps-team.md` mục 3–6 cho chi tiết. File này chỉ ghi phần
**khác**.

## 1. Khác gì so với team Claude

| | `team` (Claude) | `team-codex` (Codex) |
|---|---|---|
| Lệnh | `team` | `team-codex` (cùng file wrapper, đổi tên) |
| Thư mục | `/srv/team` | `/srv/team-codex` |
| Key worker | `/srv/team/workers.env` | `/srv/team-codex/workers.env` (file riêng, nhưng **không phải ranh giới**: xem mục 4) |
| Lead, bạn tự chạy | `claude` | `codex-lead` (Codex trong sandbox đã siết) |
| Prompt | `claude-spec`, `claude-audit` | `codex-spec`, `codex-audit` |
| Nhánh git | `team/F12` | `team-codex/F12` |
| Container | `team-F12-coder` | `codex-team-F12-coder` (không bắt đầu bằng `team-`, để feature `codex-F1` của team Claude không trùng tên với `F1` của team Codex) |
| Hermes | skill `team-pipeline`, sudoers `team-hermes` | skill `team-codex-pipeline`, sudoers `team-codex-hermes` |

Dùng chung: user `team`, image `team-worker`, mạng `team-net`, **và khóa pipeline**.
Hai team không bao giờ chạy pipeline cùng lúc (VPS 8 GB còn chạy CI). Nếu team
Claude đang chạy, `team-codex run` báo `another pipeline is running`, và ngược lại.

Hai prompt `spec` và `audit` là **một văn bản chung** cho cả hai lead, chỉ khác tên
lệnh. Nhờ vậy các bước kiểm của auditor (test bị yếu đi, đường nhạy cảm, lockfile,
file nhị phân) không thể lệch nhau giữa hai team. Test kiểm điều này.

## 2. Cài đặt

Đã cài team Claude rồi thì chỉ cần chạy lại, thêm `--with-codex`:

```bash
cd claude-agent-routing-template && git pull
sudo ./scripts/team/setup-vps-team.sh --admin "$USER" --with-codex --with-hermes
```

Bỏ `--with-hermes` nếu không dùng Hermes. Script chạy lại được nhiều lần; nó tạo
`/srv/team-codex`, cài `/usr/local/bin/team-codex`, chép `team.env` và `workers.env`
mẫu (không ghi đè), và với `--with-hermes` thêm **một file sudoers riêng**
(`/etc/sudoers.d/team-codex-hermes`, đã kiểm bằng `visudo`). File sudoers của team
Claude không bị đụng tới. Hermes vẫn chỉ được `status`, `check-spec`, `run`,
`doctor` trên `team-codex`, cùng giới hạn trong wrapper do root sở hữu.

### Key và model cho worker

```bash
sudo -u team nano /srv/team-codex/workers.env     # mode 600
# dùng lại đúng key của team Claude thì chép, giữ nguyên quyền:
sudo -u team cp -p /srv/team/workers.env /srv/team-codex/workers.env
nano /srv/team-codex/team.env                     # TEAM_MODELS_TESTER / _CODER / _REVIEWER
team-codex doctor --ping
```

Hạn mức free tính theo tài khoản provider, nên hai team dùng chung key vẫn chia
nhau cùng một quota ngày (OpenRouter `:free` khoảng 50 lượt/ngày). Quy tắc chọn
model giống team Claude: tester, coder, reviewer ba họ model khác nhau.

### Codex (dưới user của bạn)

```bash
npm i -g @openai/codex
CODEX_HOME="$HOME/.codex-lead" codex login   # hồ sơ riêng cho lead (xem `codex-lead` ở mục 3), tài khoản ChatGPT của bạn
```

Sandbox của Codex trên Linux là `bubblewrap` (`bwrap`): `setup-vps-team.sh --with-codex` cài nó (apt), `team-codex doctor` báo
thiếu, và `codex-lead` từ chối chạy khi không có. Thiếu `bwrap` thì lệnh nào trong sandbox, kể cả `team-codex check-spec` mà prompt
spec yêu cầu, cũng không chạy được. Trên máy không dùng apt, tự cài `bubblewrap`.

Đăng nhập Codex của lead chỉ nằm ở `~/.codex-lead` của **bạn**. Đừng bỏ login hay API key của Codex
vào `workers.env`, đừng đưa cho Hermes, OpenCode hay worker nào: worker chạy code do
model miễn phí viết, ngay cạnh key của nó. Conductor và Hermes không bao giờ chạy Codex;
chỉ bạn chạy.

## 3. Quy trình một feature (ví dụ F12)

```bash
team-codex new F12 --repo git@github.com:vohoailinh90/<repo>.git
nano /srv/team-codex/work/F12/request.md
```

**Chạy lead bằng `codex-lead`, không bao giờ bằng `codex` trần.** `setup-vps-team.sh --with-codex` cài
`/usr/local/bin/codex-lead` (nguồn: `scripts/team/codex-lead.sh`, thuộc root), và các lệnh `team-codex` in ra đúng tên này.
`--sandbox workspace-write` mặc định còn cho ghi `/tmp`, `$TMPDIR` và mọi `writable_roots` bạn đã cấu hình; `network_access=false`
chỉ tắt mạng của **lệnh shell** trong sandbox (web search, MCP server và plugin trong `~/.codex` của bạn là kênh riêng); và một
phiên tương tác có thể xin bạn cho vượt sandbox. Gói audit là dữ liệu do model miễn phí viết, có thể chứa chỉ dẫn chèn, nên
`codex-lead` làm các việc sau rồi mới chạy Codex:

- dùng `CODEX_HOME` riêng (`~/.codex-lead`) với `config.toml` bị ghi đè mỗi lần chạy: web search tắt, không MCP server, không
  plugin của bạn;
- lệnh shell của Codex chỉ nhận môi trường tối thiểu (`shell_environment_policy.inherit=core`) và không chạy qua login shell
  (`allow_login_shell=false`, nếu không `.profile` của bạn đưa các biến đã `export` trở lại), nên không có khóa, token: nếu không, một chỉ dẫn chèn chạy `env` rồi ghi vào `verdict.md` là đủ để chúng đi tới coder;
- `--sandbox workspace-write` với mạng tắt, `writable_roots` rỗng, loại `/tmp` và `$TMPDIR`; thư mục tạm nằm trong thư mục feature;
- `--ask-for-approval never`: lệnh vượt rào thất bại thay vì hiện hộp thoại để bạn bấm đồng ý;
- chỉ chạy ngay trong `/srv/team-codex/work/<id>` (đường dẫn thật, id hợp lệ): từ chối thư mục feature của team Claude, thư mục con như
  `repo/`, symlink sang nơi khác, hoặc chạy dưới user `team`/`hermes`;
- đặt `umask 007`: nếu bạn dùng `umask 077`, `spec.md`/`verdict.md` Codex ghi ra sẽ là `600` của riêng bạn và `team-codex push` hay
  `run --from verdict` (chạy bằng user `team`) báo `PermissionError`; thư mục feature thuộc nhóm `team` nên `660` là đủ;
- chỉ nhận tùy chọn `--model` (hoặc `-m`): `--search`, `--add-dir`, `--sandbox`, `-c`… sẽ âm thầm gỡ các ràng buộc trên nên bị từ chối;
  muốn chạy khác đi thì tự chạy `codex` trần, biết rằng lúc đó audit không còn được bó.

Các khóa `sandbox_workspace_write.*` là bộ mà `scripts/codex_cli.py` dùng cho `codex exec` của repo này. Đăng nhập một lần
trong hồ sơ đó (mục 2).

**Codex lần 1, viết spec:**

```bash
cd /srv/team-codex/work/F12 && codex-lead
#   dán nội dung của:  team-codex prompt codex-spec F12
#   Codex viết spec.md, tasks.md, acceptance.md rồi chạy team-codex check-spec F12
```

**Phần giữa, không tốn hạn mức Codex:**

```bash
team-codex run F12 --detach        # hoặc nhắn Telegram: "chạy F12"
team-codex status
tail -f /srv/team-codex/work/F12/out/run.log
```

**Codex lần 2, audit (đọc đúng một file):**

```bash
cd /srv/team-codex/work/F12 && codex-lead
#   dán nội dung của:  team-codex prompt codex-audit F12
#   Codex viết verdict.md
```

- `VERDICT: APPROVE` → `team-codex push F12` → mở PR từ nhánh `team-codex/F12` → CI → merge.
  Quy tắc từ chối của `push` giống team Claude (HEAD đổi sau gói audit, `verdict.md` cũ hơn gói).
- `VERDICT: BLOCK` → `team-codex run F12 --from verdict --detach`. Chỉ thêm **một** vòng audit;
  nếu vẫn BLOCK thì bạn tự quyết định trong Codex.

Với `codex-lead`, lệnh shell của Codex chỉ ghi được trong thư mục feature (không `/tmp`, không `$TMPDIR` của bạn,
không `writable_roots` nào khác) và không có mạng; Codex không nạp MCP server hay plugin của bạn và web search tắt.
Gói audit chứa code do model miễn phí viết, mọi chỉ dẫn bên trong nó là dữ liệu (prompt đã nói vậy). Ba điều vẫn còn:
nội dung gói audit đi tới OpenAI như mọi phiên Codex; sandbox giới hạn **ghi** chứ không giới hạn **đọc**, nên một chỉ dẫn chèn
có thể bắt Codex đọc `~/.codex-lead/auth.json` rồi ghi vào `verdict.md`, mà `team-codex run --from verdict` chuyển cho coder
(model miễn phí có Internet): đọc `verdict.md` trước khi chạy lại, và coi token đó là có thể lộ (đăng xuất rồi đăng nhập lại
là đủ); và nếu một khóa dưới đây không có tác dụng thì ràng buộc tương ứng không có (xem mục 6). Đừng chạy audit với `danger-full-access`
hay bỏ qua sandbox.

## 4. Bảo mật: phần mới so với team Claude

Có test và mutation check canh giữ (`tests/test_team.py`, lớp `CodexTeamTests` và
`CodexTeamInstallTests`; `tests/mutations/team*.yaml`):

- **Tên wrapper quyết định team.** `team` và `team-codex` là cùng một file; nó đọc tên
  mình được gọi và tự đặt `TEAM_HOME`, `TEAM_LEAD`, `TEAM_LOCK`. Môi trường của người gọi
  không đổi được team, và một tên lạ bị từ chối.
- **Lead không nằm trong `team.env`.** `team.env` sửa được bởi nhóm `team`; "ai audit" thì không phải một cài đặt.
- **Khóa chung** trỏ vào `/srv/team/.run.lock`, nên hai team không chạy cùng lúc.
- **Conductor không bao giờ chạy `codex`, `codex-lead` hay `claude`.** Test đặt ba CLI giả lên `PATH`
  và kiểm không cái nào được gọi trong cả pipeline. Launcher `codex-lead` có test chạy thật với `codex` giả
  (cờ, `CODEX_HOME`, `TMPDIR`, `config.toml` bị ghi đè, từ chối chạy sai chỗ hoặc sai user).
- **Hermes:** quy tắc sudoers riêng cho `team-codex`, đã `visudo -cf`, cùng giới hạn lệnh và
  chặn `--force`.
- **`.codex/`, `.agents/` và `AGENTS.override.md`** (ở mọi thư mục) nằm trong danh sách đường nhạy cảm của gói audit: Codex đọc cấu hình, skill và chỉ dẫn từ đó, nên worker thêm chúng sẽ bị gắn cờ BLOCK.
- **Nhánh tách nhau:** `team-codex/F12` và `team/F12` không đè nhau trên cùng một repo.

Không đảm bảo: hai team **chạy chung user `team`**, nên hai file `workers.env` chỉ là sổ sách, không phải ranh giới;
nếu worker hoặc conductor của một team bị chiếm, key của team kia cũng nằm trong tầm với. Dùng key riêng,
hạn mức thấp cho từng team. Còn lại giống team Claude: worker vẫn ra Internet được, user `team` thuộc nhóm
`docker`, free tier có thể huấn luyện trên code của bạn. Xem `docs/vps-team.md` mục 5.

## 5. Xử lý sự cố

Như `docs/vps-team.md` mục 6, thêm:

| Triệu chứng | Làm gì |
|---|---|
| `another pipeline is running` mà team Codex rảnh | team Claude đang chạy: hai team dùng chung khóa. `team status` và `team-codex status` |
| `team-codex: command not found` | chưa chạy setup với `--with-codex` |
| `codex-lead: bubblewrap (bwrap) is not installed` hoặc `doctor` báo thiếu `bubblewrap` | `sudo apt-get install bubblewrap`, hoặc chạy lại setup với `--with-codex` |
| `bwrap` có nhưng lệnh trong Codex vẫn không chạy | Ubuntu/AppArmor có thể chặn user namespace không đặc quyền mà `bwrap` cần; xem tài liệu sandbox của Codex (chưa thử ở đây) |
| `team: installed under an unknown name` | wrapper bị chép sang tên khác; chỉ `team` và `team-codex` hợp lệ |
| `TEAM_LEAD='...': expected one of` | chạy `team.py` trực tiếp với `TEAM_LEAD` sai; dùng wrapper |

## 6. Chưa kiểm chứng được trên máy thật

Session viết bộ này không có Docker, Codex hay Hermes. Cần kiểm lần đầu với một feature nhỏ:

- **Codex CLI:** tên package `@openai/codex` và `codex login` lấy từ cách `scripts/codex_cli.py`
  trong repo này gọi nó; cờ `--sandbox` và `--config sandbox_workspace_write.network_access=false`
  (gồm `writable_roots`, `exclude_tmpdir_env_var`, `exclude_slash_tmp`) cho phiên tương tác (khác với `codex exec` mà repo dùng) **chưa chạy thử**; nếu một khóa không có tác dụng, sandbox rộng hơn mô tả ở trên. Cờ `--ask-for-approval never` cho phiên tương tác và việc sandbox đúng là cho đọc rộng như mô tả ở mục 3 cũng chưa được thử. Việc `bubblewrap` chạy được trên VPS của bạn (kernel và AppArmor cho phép user namespace) cũng chưa kiểm chứng. Khóa `shell_environment_policy.inherit=core`, `allow_login_shell=false` (và việc `core` đủ cho `TMPDIR`) cũng chưa chạy thử. Biến `CODEX_HOME` (hồ sơ riêng), khóa `web_search = "disabled"` và việc hồ sơ rỗng thật sự không nạp MCP server hay plugin nào **cũng chưa kiểm chứng**: trước lần audit đầu, mở `codex-lead` và xác nhận trong phiên rằng không có MCP server hay công cụ tìm kiếm nào (lệnh `/mcp` nếu bản của bạn có). Kết nối ChatGPT gắn ở cấp tài khoản (app, connector) có thể vẫn hiện; repo này chưa kiểm. Nếu VPS không mở
  được trình duyệt để đăng nhập, xem tài liệu Codex về đăng nhập không có màn hình; repo này chưa thử.
- **Hermes** cho team Codex: skill `team-codex-pipeline` cùng cấu hình như team Claude, cũng chưa chạy thật.
- **Dashboard `scripts/office/`** chỉ đọc một thư mục team (`--team-home`) và gắn nhãn `claude-spec` /
  `claude-audit` cố định, nên feature của team Codex hiện hiển thị sai nhãn. Chưa sửa.
