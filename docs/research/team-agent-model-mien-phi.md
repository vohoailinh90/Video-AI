# Claude giữ hai đầu, model miễn phí gánh phần giữa

Làm được, nhưng "miễn phí" vào tháng 10/2026 không phải một nguồn ổn định. Đó là nhiều nguồn nhỏ, đổi điều kiện liên tục và có thể bị đóng bất cứ lúc nào. Thiết kế bền nhất gồm ba phần. Ở đầu, bạn **tự chạy Claude Code chính chủ** (gói Pro) để viết spec có tiêu chí nghiệm thu chạy được bằng lệnh. Ở cuối, bạn lại tự chạy Claude Code để audit một "gói audit" đã nén, gồm diff và log kiểm thử. Ở giữa, **Hermes Agent trên VPS làm hub** (gateway Telegram, kanban, cron) và giao việc cho các worker chạy model miễn phí trong Docker. Giữa các bước luôn có cổng kiểm tra xác định (test, lint, type-check, mutation check) mà model không thể "thuyết phục" để cho qua. Các nguồn miễn phí đáng dựa vào nhất hiện nay là **Mistral free** (khoảng 1 tỷ token/tháng nhưng có thể dùng dữ liệu để huấn luyện), **Gemini API Flash/Flash-Lite qua khóa AI Studio** và **OpenRouter `:free`** (50 lượt/ngày, tăng lên 1.000 lượt/ngày vĩnh viễn sau một lần nạp $10). Groq, NVIDIA và Cloudflare chỉ hợp cho việc phụ, và NVIDIA thường không gửi được OTP về số +84. Nhiều lời khuyên phổ biến đã lỗi thời: **Gemini CLI miễn phí cho tài khoản cá nhân dừng ngày 18/06/2026, Qwen Code OAuth dừng 15/04/2026, iFlow đóng 17/04/2026, GitHub Models nghỉ hẳn 30/07/2026, Cerebras chuyển sang gói dùng thử $5 bắt buộc có thẻ**. Nếu chịu bỏ tiền, khoản đáng chi nhất không phải nâng gói Claude mà là **$10 nạp một lần cho OpenRouter**, kèm (nếu cần) DeepSeek V4.1 Flash trả theo token (ước tính khoảng $0,15 mỗi task ngoài giờ cao điểm) hoặc OpenCode Go $10/tháng. Về điều khoản: gói Pro không cấp API key, và Anthropic đã hạn chế dùng gói thuê bao qua harness bên thứ ba. Vì vậy Hermes không bao giờ được giữ phiên đăng nhập Claude. Việc một agent tự gọi `claude -p` bằng tài khoản Pro có được phép hay không **chưa được xác nhận**. Lưu ý cuối: gần như mọi con số hạn mức trong báo cáo đến từ bản tóm tắt kết quả tìm kiếm, vì trang của các nhà cung cấp không truy cập được trực tiếp. Hãy kiểm lại trong console trước khi dựa vào chúng.

## Bảy ưu đãi "miễn phí" đã hết trước tháng 10/2026

Phần lớn bài hướng dẫn "code bằng AI miễn phí" trên mạng được viết cho năm 2025, khi Google, Alibaba và GitHub còn phát quota rộng rãi. Năm 2026 thì ngược lại. Nhà cung cấp đóng ưu đãi chỉ với 0–6 tuần báo trước (GitHub Models báo trước khoảng 6 tuần, Qwen cắt quota hai đợt rồi đóng hẳn). Vì vậy **không nên xây hệ thống dựa trên một nguồn miễn phí duy nhất**. Bảng dưới liệt kê những thứ không nên làm theo nữa.

| Ưu đãi cũ (đừng làm theo) | Chuyện đã xảy ra | Dùng thay bằng |
|---|---|---|
| **Gemini CLI miễn phí bằng tài khoản Google cá nhân** (1.000 lượt/ngày) | **Dừng từ 18/06/2026** cho tài khoản cá nhân Free/Pro/Ultra, công bố ngày 19/05/2026. Chỉ còn phục vụ Code Assist Standard/Enterprise, người dùng Google Cloud và khóa API trả phí ([GitHub #27274](https://github.com/google-gemini/gemini-cli/discussions/27274)). Người dùng không đủ điều kiện được báo là nhận HTTP 410 ([converge.ai](https://enter.converge.ai/page/en-US/blog/gemini-cli-alternatives)). | Khóa Gemini API free (chỉ Flash) cắm vào OpenCode/Hermes. Antigravity CLI (`agy`) không đủ dùng (xem dưới). |
| **Qwen Code + Qwen OAuth miễn phí** | Bị cắt từ 1.000 xuống 100 lượt/ngày, rồi **đóng ngày 15/04/2026**. CLI không còn quota miễn phí ([Qwen auth.md](https://raw.githubusercontent.com/QwenLM/qwen-code/main/docs/users/configuration/auth.md), [issue #3203](https://github.com/QwenLM/qwen-code/issues/3203)). | Vẫn dùng được Qwen Code CLI (Apache-2.0) với khóa API của bạn (BYOK). |
| **iFlow CLI** | **Đóng ngày 17/04/2026** (giờ Bắc Kinh), người dùng được khuyên chuyển sang Qoder ([CLIProxyAPI #2561](https://github.com/router-for-me/CLIProxyAPI/issues/2561)). | Không có |
| **GitHub Models** | Ngừng nhận khách mới từ 16/06, **nghỉ hẳn ngày 30/07/2026** ([GitHub changelog](https://github.blog/changelog/2026-07-01-github-models-is-being-fully-retired-on-july-30-2026/)). Blog nào vẫn in "giới hạn tháng 10/2026" cho GitHub Models là sai. | Không có |
| **Cerebras free** (30 RPM, 1 triệu token/ngày, không cần thẻ) | Chuyển thành **gói dùng thử $5, bắt buộc có phương thức thanh toán đã xác minh, hết hạn sau 30 ngày**, giới hạn 5 RPM mỗi model ([UsagePricing](https://usagepricing.com/blueprint/activity/cerebras-2026-07-21-packaging), [Cerebras docs](https://inference-docs.cerebras.ai/support/rate-limits)). | Không có |
| **Gemini API: Pro miễn phí, Flash vài trăm lượt/ngày** | Các model Pro (2.5/3/3.1 Pro) bị rút khỏi gói free khoảng **01/04/2026** ([AgentDeals](https://agentdeals.dev/gemini-api-pricing-changes)). Hạn mức ngày (RPD) của Flash giảm mạnh, và nhân viên Google gọi gói free là "highly unstable" ([diễn đàn Google](https://discuss.ai.google.dev/t/is-gemini-2-5-pro-disabled-for-free-tier/111261)). | Flash/Flash-Lite free (xem bảng nguồn) |
| **Chutes free, Devstral 2 free, "OpenRouter 200/ngày", "Groq 14.400 RPD"** | Chutes bỏ gói 200 lượt/ngày từ 02/2026 ([Chutes](https://chutes.ai/news/community-announcement-february)). Devstral 2 thành trả phí từ 27/01/2026 ([Mistral](https://mistral.ai/news/mistral-vibe-2-0/)). OpenRouter nay là 50 hoặc 1.000 lượt/ngày ([OpenRouter limits](https://openrouter.ai/docs/api-reference/limits)). Groq chuyển sang giới hạn riêng cho từng model ([BenchLM Groq](https://benchlm.ai/free-tier/groq)). | Xem bảng nguồn |

Mâu thuẫn lớn nhất giữa các ghi chú nằm ở **Gemini CLI**. Trang quota trên geminicli.com (chỉ xem được qua snippet tìm kiếm) và tài liệu quota trong repo vẫn ghi 1.000 lượt/ngày, 60 lượt/phút khi đăng nhập Google và 250 lượt/ngày khi dùng khóa API không trả phí ([geminicli.com](https://geminicli.com/docs/resources/quota-and-pricing/), [quota doc trong repo](https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/resources/quota-and-pricing.md)). Ngược lại, thông báo chính thức trên GitHub, được đọc trực tiếp, nói rõ quyền dùng miễn phí của tài khoản cá nhân đã kết thúc ngày 18/06/2026. Tài liệu quota không nhắc gì tới thay đổi này. **Báo cáo này lấy thông báo làm chuẩn và coi trang quota là lỗi thời.** Một điểm vẫn chưa rõ: khóa AI Studio *không trả phí* còn chạy được Gemini CLI không. Thông báo chỉ nói khóa "trả phí" được giữ lại, nên hãy giả định là không. Sản phẩm thay thế, **Antigravity CLI (`agy`)**, cũng không cứu được. Hạn mức gói Starter chỉ tính theo tuần và không được công bố ([CodexBar #3789](https://github.com/steipete/CodexBar/issues/3789)). Ngay cả người dùng Google AI Pro cũng báo hết quota sau khoảng 2 giờ, với khoảng 23–25 nghìn token chi phí cố định cho mỗi request ([discussion #27307](https://github.com/google-gemini/gemini-cli/discussions/27307)).

Có thêm hai chi tiết dễ gây hiểu nhầm. Thứ nhất, tin "Google giới hạn người dùng Gemini miễn phí chỉ còn Flash-Lite" ngày 09/10/2026 là về **ứng dụng Gemini cho người dùng phổ thông, không phải API** ([Computing](https://www.computing.co.uk/news/2026/ai/google-to-restrict-gemini-model-access-for-free-users)). Thứ hai, trang vòng đời model vẫn ghi Gemini 2.5 Flash bị tắt trên API ngày **16/10/2026**, trong khi có báo cáo bị 404 sớm hơn ([diễn đàn Google](https://discuss.ai.google.dev/t/gemini-2-5-flash-deprecated-without-warning-earlier-than-shutdown-date/174217)). Đừng đưa ID model 2.5 vào cấu hình. Hãy dùng 3.5/3.8 Flash hoặc Flash-Lite.

## Model mở chỉ kém Claude 6–20 điểm, nhưng đường miễn phí tới chúng rất hẹp

### Bản đồ model tháng 10/2026

Thế hệ Claude hiện tại gồm **Opus 5.5 (22/09), Sonnet 5.5 (28/09), Haiku 5.5 (07/10/2026) và Fable 5.1**. Tất cả có ngữ cảnh 1M token ([Anthropic models overview](https://platform.claude.com/docs/en/about-claude/models/overview)). OpenAI đã lên GPT-6: Astra ra ngày 03/09, Sol và Luna ra ngày 22/09 ([ProPakistani](https://propakistani.pk/2026/09/24/openai-launches-gpt-6-sol-and-luna-with-50-lower-api-costs/)). Model mới nhất của Google được xác nhận là Gemini 3.5 Flash (19/05), với Terminal-Bench 2.1 đạt 76,2 và SWE-bench Pro đạt 55,1 theo model card ([Appwrite](https://appwrite.io/blog/post/gemini-3-5-flash-deep-dive)). Model Pro tốt nhất đang có vẫn là 3.1 Pro. Model mở mạnh nhất đến từ các phòng lab Trung Quốc và đều là MoE khổng lồ. Kimi K3 có 2,8T tham số, nặng khoảng 1,4 TB và dùng giấy phép riêng ([NYU Shanghai RITS](https://rits.shanghai.nyu.edu/ai/kimi-k3-open-weights-ship-2-8t-parameters-1-4-tb-to-run/)). Ngoài ra còn GLM-5.2 (MIT, SWE-bench Pro 62,1 do Z.ai tự báo) ([NYU RITS GLM-5.2](https://rits.shanghai.nyu.edu/ai/glm-5-2-z-ais-open-weights-coder-beats-gpt-5-5-at-1-6-the-cost/)), GLM-5.3 ([DataNorth](https://datanorth.ai/news/z-ai-releases-glm-5-3)), DeepSeek V4 (MIT) ([DataNorth](https://datanorth.ai/news/deepseek-releases-v4-pro-0813-and-harness-v0-1)) và MiniMax M3 ([DataNorth](https://datanorth.ai/news/minimax-launches-m3)). Không model nào trong số này tự host được trên một VPS thông thường.

| Họ model (bản mới nhất) | Mở/đóng | Chỉ số đáng chú ý | Đường miễn phí thực tế |
|---|---|---|---|
| Claude Opus/Sonnet/Haiku 5.5, Fable 5.1 | Đóng | AA Intelligence Index: Fable 5.1 đạt 65,7, cao nhất | Chỉ qua gói Pro của bạn (Fable tính vào usage credits) |
| GPT-6 Astra/Sol/Luna | Đóng | Luna được báo là có cho người dùng Free/Go | Codex qua ChatGPT Free/Go, quota không công bố |
| Gemini 3.5/3.8 Flash, Flash-Lite | Đóng | 3.5 Flash: SWE-bench Pro 55,1 | **Gemini API free key** |
| Kimi K3 | Mở (giấy phép riêng) | AA 59,7, cao nhất trong nhóm model mở | Không có API free. Có trong OpenCode Go (trả phí). |
| GLM-5.2 / 5.3 | Mở (MIT) | SWE-bench Pro 62,1 (tự báo) | NVIDIA NIM (GLM-5.1/5.2) nếu đăng ký được |
| DeepSeek V4 / V4.1 Flash | Mở (MIT) | AA của V4-Pro-0813 khoảng 53 | NVIDIA NIM (V4 Flash). Rẻ nhất khi trả phí. |
| NVIDIA Nemotron 3 Ultra | Mở | AA khoảng 48, cao nhất trong model mở của Mỹ ([Artificial Analysis](https://artificialanalysis.ai/articles/nvidia-nemotron-3-ultra-released)) | **OpenRouter `:free`, OpenCode Zen free** |
| Qwen3.6 (27B, 35B-A3B), Qwen3.8 27B | Mở (Apache-2.0) | Qwen3.6-27B: SWE-bench Verified 77,2 (tự báo) ([The Decoder](https://the-decoder.com/alibabas-open-model-qwen3-6-leads-googles-gemma-4-across-agentic-coding-benchmarks/)) | Groq (prompt nhỏ) |
| Mistral Medium 3.5, Devstral 2 | Mở | SWE-bench Verified 77,6 (tự báo) ([DataNorth](https://datanorth.ai/news/mistral-medium-3-5-release)) | **Mistral free tier** (chưa xác nhận model nào nằm trong free tier) |
| gpt-oss-120b/20b, Gemma 4 E2B/E4B | Mở (Apache-2.0) | AA: gpt-oss-120b 33,3, Gemma 4 31B 39,2 | Groq/Cloudflare; Gemma E-series tự chạy trên CPU của VPS |

Đặt cạnh nhau, model mở **kém Claude tốt nhất khoảng 6 điểm trên AA index** (Kimi K3 đạt 59,7, Fable 5.1 đạt 65,7) ([tóm tắt AA](https://pasqualepillitteri.it/en/news/14684/open-source-closes-gap-artificial-analysis)). Trên SWE-bench Pro, khoảng cách là **15–20 điểm** (GLM-5.2 đạt 62,1, Claude Opus 5 đạt 79,2 theo BenchLM) ([BenchLM](https://benchlm.ai/md/benchmarks/swe-bench-pro.md)). Trên Terminal-Bench, model mở trông gần ngang Claude, nhưng đó là điểm nhà sản xuất tự chạy trên harness của chính họ. Ngoài ra, một audit của OpenAI ước tính khoảng 30% task trong bộ SWE-bench Pro công khai bị lỗi. Kết luận thực tế: model mở đủ sức **thực thi** một ticket đã được đặc tả rõ và có test canh giữ. Chúng chưa đủ tin cậy để tự **quyết định** thiết kế hay tự tuyên bố mình đã làm đúng. Ghi chú nghiên cứu cũng không tìm thấy Grok 5, Llama 5, Hermes 5, Gemini 4 hay Qwen 4. Nếu gặp bài nào nhắc tới chúng như sản phẩm đã ra mắt, hãy coi chừng.

### Model mở thất bại trong vòng lặp agent theo những kiểu đoán trước được

Các nghiên cứu năm 2026 cho thấy model mở và model nhỏ hỏng theo vài kiểu lặp lại. Trong AgentFloor, 41% lỗi của gemma4:26b là hết ngân sách bước và 36% là gọi tool không tồn tại ([arXiv 2605.00334](https://arxiv.org/pdf/2605.00334)). Trong IDE-Bench, Llama 4 và Grok Code Fast "sửa trước khi đọc" ở 73–92% số lần chạy ([arXiv 2601.20886](https://arxiv.org/pdf/2601.20886)). GLM-5.1 gặp lỗi chí mạng ở 10/32 task, Qwen3.6 Plus ở 21/32 task, một phần do sai cú pháp đầu ra dù đã được dặn trước ([arXiv 2605.06898](https://arxiv.org/pdf/2605.06898)). Model càng nhỏ càng dễ làm hỏng một lệnh shell nguy hiểm ([arXiv 2606.19380](https://arxiv.org/pdf/2606.19380)), và độ tin cậy khi gọi tool sụp hẳn ở model dưới khoảng 4B tham số ([d-central](https://d-central.tech/local-llm-agent-capability/)). Mẫu thử trong các nghiên cứu này nhỏ, nên nên dùng chúng như danh sách kiểu lỗi cần phòng hơn là tỷ lệ chính xác. Thiết kế bên dưới phòng từng kiểu lỗi: task nhỏ có giới hạn số bước, bắt buộc đọc trước khi sửa, sandbox kèm danh sách lệnh cấm, và cổng test/type-check bắt lỗi API bịa.

Còn một bằng chứng ủng hộ việc tách vai. Benchmark architect/editor của Aider (năm 2024, model cũ) cho thấy một "kiến trúc sư" mạnh đi với "người sửa" rẻ mất rất ít chất lượng. Sonnet làm kiến trúc kèm DeepSeek làm editor đạt 78,9, so với 77,4 khi Sonnet chạy một mình. o1-preview kèm DeepSeek đạt 85,0, so với 79,7 khi o1-preview chạy một mình ([dữ liệu architect.yml của Aider](https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/architect.yml)). Ghi chú không tìm thấy nghiên cứu năm 2026 nào đo đúng cấu hình "Claude lập kế hoạch, model miễn phí thực thi". Đây vẫn là giả thuyết hợp lý, chưa được chứng minh.

### Các nguồn API miễn phí còn hoạt động

| Nguồn | Model free | Giới hạn (cần kiểm lại) | Có dùng dữ liệu để huấn luyện? | Xếp loại |
|---|---|---|---|---|
| **Gemini API** (khóa AI Studio, không cần thẻ) | 3.8 Flash, 3.5 Flash-Lite, 3.1 Flash-Lite. Không có Pro. Ngữ cảnh 1M. ([pricing](https://ai.google.dev/gemini-api/docs/pricing)) | Google không còn công bố bảng hạn mức theo model ([BenchLM](https://benchlm.ai/free-tier/google-ai-studio)). Diễn đàn báo 3.8 Flash khoảng 20 RPD, Flash-Lite khoảng 500 RPD ([forum](https://discuss.ai.google.dev/t/gemini-3-8-flash-free-tier-20-rpd-is-too-limited-for-practical-evaluation/180609)). Lỗi 503 vẫn bị trừ vào RPD ([forum](https://discuss.ai.google.dev/t/gemini-api-503-errors-appear-to-consume-free-tier-rpd-leading-to-429-quota-exhaustion/184644)). | Có, gói free dùng để cải thiện sản phẩm. Gói trả phí thì không. | Hub, review, viết test |
| **OpenRouter `:free`** (không cần thẻ hay số điện thoại) | Danh sách xoay vòng. Đang dẫn đầu: Nemotron 3 Ultra, Laguna S 2.1, Nemotron 3.5 Lightning, Nemotron 3 Super ([collection](https://openrouter.ai/collections/free-models)) | **20 RPM. 50 lượt/ngày, hoặc 1.000 lượt/ngày vĩnh viễn sau một lần nạp ≥$10.** Hạn mức tính theo tài khoản, request lỗi cũng bị tính, số dư âm thì trả lỗi 402 ([limits](https://openrouter.ai/docs/api-reference/limits)). | Tùy nhà cung cấp phía sau. 9/19 model free nằm trên host có điều khoản cho phép huấn luyện ([TrueFoundry](https://www.truefoundry.com/blog/openrouter-free-models-whats-actually-free-and-what-it-costs-you)). | Implement, dự phòng |
| **Mistral free/Experiment** | Danh sách model free chưa xác nhận. Devstral 2 đã thành trả phí. | **1 req/s, 500.000 TPM, 1 tỷ token/tháng** ([Mistral help](https://help.mistral.ai/en/articles/225174-what-are-the-limits-of-the-free-tier)) | Có thể. Có nút opt-out trong Admin → Privacy ([Mistral](https://help.mistral.ai/en/articles/455207-can-i-opt-out-of-my-input-or-output-data-being-used-for-training)), nhưng nguồn khác nói phải opt-in mới được dùng → cứ giả định là có huấn luyện. | Nguồn khối lượng lớn nhất |
| **Groq** | gpt-oss-120b, Qwen3.8 27B, … | 30 RPM, 1.000 RPD, **8.000 TPM**, 200.000 TPD ([BenchLM Groq](https://benchlm.ai/free-tier/groq)) | Chưa rõ | Chỉ việc có prompt nhỏ |
| **NVIDIA build.nvidia.com** | Khoảng hơn 100 model, gồm Kimi K2.5, GLM-5.1/5.2, DeepSeek V4 Flash | Khoảng 40 RPM. Chỉ dùng thử/prototype ([NIM FAQ](https://forums.developer.nvidia.com/t/nvidia-nim-faq/300317)). Vòng lặp agent gây lỗi 429 ([forum](https://forums.developer.nvidia.com/t/request-for-api-rate-limit-increase-nvidia-nim-free-tier-for-agentic-coding-workflow/375953)). | Chưa rõ | Model mở mạnh nhất có free, **nếu nhận được OTP** |
| **Cloudflare Workers AI** | Khoảng 80–84 model mở. Model lớn và mới (Kimi K2.6, GLM 5.2, DeepSeek V4) chỉ có ở gói trả phí, gói Free trả về 403. | 10.000 Neurons/ngày, reset lúc 00:00 UTC ([Cloudflare](https://developers.cloudflare.com/workers-ai/platform/pricing/)) | Chưa rõ | Việc phụ |
| **Z.ai** | GLM-4.7-Flash, GLM-4.5-Flash miễn phí. GLM-5.3-Flash phải trả phí. ([Z.ai](https://docs.z.ai/guides/overview/pricing)) | Được báo là 1 request đồng thời ([ToolNavs](https://toolnavs.com/article/1100-zai-released-glm-47-flash-weights-and-api-free-tier-1-concurrency-and-launched-f)) | Chưa rõ | Một luồng |
| **OpenCode Zen free** | Big Pickle, Nemotron 3 Ultra Free, LongCat 2.5 Preview, Step 5 Preview, Space Bunny, MiMo, Ling… "miễn phí trong thời gian giới hạn" ([Zen docs](https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/web/src/content/docs/zen.mdx)) | Không công bố số | **Space Bunny, LongCat 2.5 Preview, Step 5 Preview: không lưu, không huấn luyện.** Big Pickle, Exo, MiMo, Ling: có thể dùng dữ liệu. Nemotron Free: NVIDIA ghi log. | Implement (repo công khai) |
| **SambaNova, Ollama Cloud Free, HF, Cohere** | Nhiều loại | SambaNova chỉ 20 RPD ([docs](https://docs.sambanova.ai/docs/en/models/rate-limits)). Ollama Free chỉ 1 request đồng thời ([Ollama](https://ollama.com/blog/transparent-pricing)). HF chỉ $0,10/tháng ([HF](https://huggingface.co/docs/inference-providers/pricing)). | Chưa rõ | Gần như vô dụng cho agent |
| **Codex qua ChatGPT Free/Go** | GPT-6 Sol/Luna | "limited messages", không có con số công bố ([OpenAI help](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)) | Theo điều khoản ChatGPT | Thỉnh thoảng xin ý kiến thứ hai |

### Quy quota ra số task mỗi ngày

Danh sách hạn mức dài nhưng khó hình dung. Cách dễ hiểu hơn là đổi chúng ra số task. Giả định lấy theo ví dụ tính trong ghi chú: **mỗi task implement khoảng 100 lượt gọi, mỗi lượt mang khoảng 50.000 token ngữ cảnh**. Đây là giả định, không phải số đo. Phép tính cho thấy khi gộp các nguồn lại, quota không phải nút thắt chính với một lập trình viên. Nút thắt thật là độ ổn định và chất lượng.

| Nguồn | Phép tính | ≈ Task implement/ngày |
|---|---|---|
| Mistral free | 1 tỷ token/tháng ≈ 33 triệu/ngày ≈ 660 lượt. TPM giới hạn ở khoảng 10 lượt/phút. | **khoảng 6** |
| Gemini Flash-Lite free | khoảng 500 RPD (số liệu từ diễn đàn) | **khoảng 5** |
| Gemini 3.8 Flash free | khoảng 20 RPD | 0, chỉ đủ khoảng 20 lượt review |
| OpenRouter `:free` | 50 lượt/ngày, hoặc 1.000 lượt/ngày sau khi nạp $10 | 0,5 → **khoảng 10** |
| Groq | 8.000 TPM nên một request 50.000 token không bao giờ lọt qua | 0, chỉ cho commit message hoặc tóm tắt |
| NVIDIA NIM | khoảng 40 RPM, không thấy báo giới hạn ngày | Về lý thuyết cao, thực tế bị 429 và vướng OTP |
| SambaNova, Cloudflare | 20 RPD; khoảng $0,11 Neurons/ngày | khoảng 0 |

Tổng lại, gói $0 cho khoảng 11 task/ngày và gói $10 cho khoảng 20 task/ngày, *nếu* mọi nguồn cùng hoạt động một lúc, mà trong năm 2026 thì hiếm có ngày nào như vậy.

### CLI nào chạy được không cần người trông trên VPS

| CLI | Giấy phép | Chế độ headless | Endpoint OpenAI-compatible | Cạm bẫy đã biết |
|---|---|---|---|---|
| **OpenCode** (v1.18.35, 06/10/2026) | MIT | `opencode run "..." --model provider/model --format json`; `opencode serve` + `--attach` ([cli.mdx](https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/web/src/content/docs/cli.mdx)) | Có (`@ai-sdk/openai-compatible` + `baseURL`). Tích hợp sẵn OpenRouter, Ollama, Zen ([providers.mdx](https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/web/src/content/docs/providers.mdx)) | **Treo khi stdin là pipe không đóng → luôn thêm `< /dev/null`**. Một người báo chỉ 44% lần chạy thành công ([issue #38723](https://github.com/anomalyco/opencode/issues/38723)). `doom_loop`/`external_directory` mặc định `ask` nên có thể kẹt ([permissions.mdx](https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/web/src/content/docs/permissions.mdx)). |
| **Qwen Code** | Apache-2.0 | `qwen -p`, nhận stdin, `--output-format stream-json`, `--approval-mode`, **`--max-wall-time`, `--max-tool-calls`, `--max-session-turns`**, exit code 55/53 ([headless.md](https://raw.githubusercontent.com/QwenLM/qwen-code/main/docs/users/features/headless.md)) | Có (`modelProviders` trong `~/.qwen/settings.json`) | `--yolo` không phải sandbox. `QWEN_CODE_UNATTENDED_RETRY=1` thử lại lỗi 429 mãi mãi. |
| **Goose** | Apache-2.0 | `goose run -t`, `-i -`, `--recipe`, `--output-format json` ([running-tasks.md](https://raw.githubusercontent.com/block/goose/main/documentation/docs/guides/running-tasks.md)) | Có (hơn 15 provider) | Hỗ trợ dùng gói thuê bao qua ACP, nhưng đừng dùng với Claude |
| **Codex CLI** | Apache-2.0 | `codex exec --json`, `--sandbox` | **Chỉ Responses API** (`wire_api = "responses"`) ([OpenRouter tutorial](https://openrouter.ai/blog/tutorials/codex-cli-openrouter/)) | Không hợp với endpoint free kiểu chat/completions |
| Kilo, Cline, Crush, Aider | MIT / Apache / FSL / – | Có | Có | Endpoint free của Kilo có thể ghi log prompt ([Kilo](https://kilo.ai/docs/code-with-ai/agents/free-and-budget-models)) |
| Kiro CLI | Đóng | Cần `KIRO_API_KEY`, chỉ có ở gói trả phí ([Kiro](https://kiro.dev/docs/cli/headless/)) | Không | Gói free không chạy headless được |

Kết luận: chọn CLI vì nó chạy headless tốt, còn model thì chọn riêng. **OpenCode** đáng dùng nhất làm harness implement (cộng đồng lớn, hỗ trợ mọi endpoint, có model free của Zen). **Qwen Code** hợp khi cần trần ngân sách cứng và exit code rõ ràng.

### Mâu thuẫn giữa các ghi chú và cách báo cáo xử lý

| Điểm mâu thuẫn | Phiên bản A | Phiên bản B | Báo cáo dùng |
|---|---|---|---|
| Gemini CLI miễn phí | 1.000 lượt/ngày (trang quota) | Đã dừng 18/06/2026 (thông báo GitHub) | **B.** Trang quota đã lỗi thời. |
| RPD của Gemini Flash free | 20 / 500 (diễn đàn) | 250 / 1.500 (blog tổng hợp) | Không có con số chắc chắn. Xem trong AI Studio. |
| Danh sách model free trên OpenRouter | GLM-5.2, DeepSeek V4 Flash, Qwen3-Coder, Devstral 2 (tháng 6–7) | "Không còn bản free của DeepSeek/Mistral/GLM" (07/2026). Ngày 05/10 còn 19 model text | Lấy bản mới nhất. Đừng ghim cứng ID, hãy xem trang collection. |
| Mistral free và việc huấn luyện | Có thể opt-out | Bắt buộc opt-in | Giả định là **có huấn luyện** |
| GLM-5.2 trên Cloudflare | Được thêm ngày 16/06/2026 | Model lớn trả về 403 trên gói Free | Không dùng được trên gói Free |
| Claude Pro và Opus | "Pro không có Opus" (bên thứ ba) | Tài liệu chính thức: Claude Code trên Pro **mặc định Opus 5.5** ([model-config](https://code.claude.com/docs/en/model-config)) | **Tài liệu chính thức** |
| Số request đồng thời của Z.ai Flash | 1 | 5–10 | 1 |
| DeepSeek V4 Pro sau 14/09/2026 | Bị chuyển sang V4.1 Flash | Vẫn tính phí như cũ | Chưa rõ. Dùng `deepseek-flash`. |
| Giá MiniMax / GLM Coding Plan | $22/$55/$132; GLM Pro $72 | $20/$50/$120; GLM Pro $80 | Xem trang giá trước khi mua |

## Đội hình đề xuất: một hub Hermes, bốn vai miễn phí, hai lần dùng Claude

### Hermes làm hub vì có kanban gán model theo từng task

**Hermes Agent** (Nous Research) là agent tự host, giấy phép MIT. Bản mới nhất **v0.21.6 ra ngày 08/10/2026** và có bản vá bảo mật cho xác thực dashboard, chặn thực thi git filter từ repo lạ, và lỗi vượt allowlist email ([releases](https://github.com/NousResearch/hermes-agent/releases)). Hermes gồm một gateway cho Telegram/Discord/Slack, cron, subagent, MCP, skills và 7 terminal backend, trong đó có Docker ([README](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/README.md)). Đừng nhầm với **họ model Hermes 4** (14B–405B, ra năm 2025, không miễn phí) ([vantaige](https://vantaige.io/blog/nous-hermes-4-self-hosted-setup-vs-closed-agents-2026)). Nous Portal là gói thuê bao, và tài liệu không nhắc tới model miễn phí nào trong đó.

Lý do chọn Hermes nằm ở cách nó điều phối. `delegate_task` chỉ dùng **một** `delegation.model` cho mọi subagent con, không đổi được model theo từng lần gọi. Chính tài liệu khuyên: "For a per-task model, use the kanban board" ([delegation.md](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/features/delegation.md)). Kanban là bảng task bền vững, lưu trong `~/.hermes/kanban.db`. Mỗi worker là một tiến trình riêng chạy theo một profile, mỗi task có thể ghim `--model/--provider`, và có `kanban.failure_limit` (mặc định 2) ([kanban.md](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/features/kanban.md)). Cron có chế độ `--no-agent --script` chạy script mà **không tốn token nào** ([cron.md](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/features/cron.md)), rất hợp cho các cổng kiểm tra và thông báo. Cũng có ba hạn chế cần nhớ. Model chính của Hermes cần **ngữ cảnh tối thiểu 64.000 token** ([quickstart](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/getting-started/quickstart.md)). Fallback chỉ áp dụng trong một lượt, kích hoạt tối đa một lần mỗi lượt, đổi provider sẽ mất prompt cache, và cron job đã ghim model thì không fallback ([fallback-providers.md](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/features/fallback-providers.md)). Và Hermes đổi bản rất nhanh (6 bản vá trong khoảng 5 tuần, có lỗi state.db ở 0.21.0–0.21.2), nên hãy snapshot `~/.hermes` trước mỗi lần `hermes update`. Về các lựa chọn khác: OpenClaw có tiền sử bảo mật cần soi kỹ, và chính nó bị nêu tên trong đợt Anthropic chặn harness bên thứ ba. OpenCode và Goose hợp làm *worker* hơn làm hub. claude-code-router chỉ là gateway model, không phải hub.

### Vai trò, model chính và dự phòng

| # | Vai | Người/công cụ thực hiện | Model chính (miễn phí) | Dự phòng miễn phí | Dự phòng trả phí nhỏ |
|---|---|---|---|---|---|
| 1 | **Kiến trúc + spec** | **Bạn tự chạy Claude Code chính chủ** | Opus 5.5 qua `/model opusplan` cho việc rủi ro; Sonnet 5.5 cho việc thường | Hết quota 5 giờ thì chờ reset. Việc nhỏ (T0/T1) bỏ qua Claude. | Usage credits Claude (giá API), chỉ khi bạn chủ động bật |
| 2 | **Hub điều phối** | Hermes v0.21.6: gateway Telegram, kanban, cron | Gemini Flash-Lite (khóa AI Studio, 1M ngữ cảnh) | `fallback_providers`: OpenRouter `:free`, rồi Mistral free | DeepSeek `deepseek-flash` |
| 3 | **Viết test trước** | Worker Hermes `tester` (hoặc `qwen -p` với `--max-wall-time`) | Mistral free | Gemini Flash-Lite | DeepSeek V4.1 Flash |
| 4 | **Implement** | Phương án A: worker Hermes `coder`. Phương án B: `opencode run` trong Docker worktree. | OpenRouter `:free` (Nemotron 3 Ultra hoặc model coder free đang có); NVIDIA NIM (GLM-5.x, DeepSeek V4 Flash) nếu qua được OTP | Mistral free; Zen free loại không huấn luyện (Space Bunny, LongCat, Step) | **OpenCode Go $10** (Kimi K3, GLM-5.3, DeepSeek V4.x) ([Go docs](https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/web/src/content/docs/go.mdx)) hoặc DeepSeek ngoài giờ cao điểm |
| 5 | **Cổng xác định** | Script + CI (runner tự host trên VPS) | Không dùng model | — | — |
| 6 | **Review chéo** | Worker Hermes `reviewer`, chỉ đọc | Gemini 3.5/3.8 Flash free (khác họ với coder) | Mistral free (nếu coder không dùng Mistral); Codex Free nếu còn lượt | DeepSeek |
| 7 | **Docs, commit message, changelog** | Script `--no-agent` gọi API trực tiếp | Groq gpt-oss-120b (prompt dưới 8.000 token) | Cloudflare; Gemma 4 E2B/E4B chạy CPU ngay trên VPS | — |
| 8 | **Audit cuối** | **Bạn tự chạy Claude Code chính chủ** | Sonnet 5.5, effort thấp hoặc medium | Opus 5.5 cho auth, thanh toán, migration | Usage credits |

Nguyên tắc chính: vai 3, 4 và 6 dùng **ba họ model khác nhau**, để lỗi của người viết không trùng với điểm mù của người kiểm. Nguyên tắc này hợp lý về lý thuyết nhưng chưa có benchmark đo. Cũng không có benchmark nào đánh giá năng lực *viết test, review hay viết docs* của model mở, nên việc gán vai ở đây là phán đoán. Dữ liệu thật sẽ đến từ tỷ lệ qua cổng của chính bạn. Về A và B: phương án A ít thành phần hơn và cho phép air-gap container, vì lời gọi LLM đi từ host còn lệnh chạy trong container. Phương án B dùng harness chuyên cho code nhưng container phải có mạng để gọi model. Không có số đo nào về Hermes khi làm harness code, nên hãy bắt đầu với A và chuyển sang B nếu tỷ lệ qua cổng thấp.

### Quy trình đầu-cuối

| Bước | Ai làm | Đầu vào → Đầu ra | Điều kiện để qua bước |
|---|---|---|---|
| 1. Mở ticket | Bạn | Yêu cầu → `request.md` (ghi rõ repo công khai hay kín) | — |
| 2. Bản đồ repo | Script (0 token) | Repo → `repo-map.txt` (`git ls-files` cộng chữ ký hàm chính) | — |
| 3. **Spec (Claude lần 1)** | Bạn, trong `claude` | request + repo-map + đúng các file liên quan → `spec.md`, `tasks.md`, `acceptance.md` | Mỗi task có *files to touch*, *do-not-touch* và một **lệnh verify chạy được** |
| 4. Phản biện spec (tùy chọn) | Model free mạnh (GLM/Kimi/Nemotron) | spec → `spec-questions.md` (tối đa 30 dòng) | Bạn tự quyết. Chỉ quay lại Claude khi gặp vấn đề chặn đường. |
| 5. Viết test trước | `tester` | acceptance → file test | Test chạy được và **đang FAIL đúng chỗ** |
| 6. Implement | `coder` | tasks + test → commit trên nhánh feature | Thử tối đa `failure_limit` lần; đổi sang model dự phòng (`hermes kanban set-model`); vẫn hỏng thì đặt `blocked` |
| 7. Cổng xác định | CI chạy từ checkout sạch | Nhánh → `gates.log` | test/lint/type xanh, mutation check đạt |
| 8. Review chéo | `reviewer` | diff + spec → `prereview.md` (tối đa 60 dòng, ghi file:line) | Coder sửa lỗi chặn, quay lại bước 7 |
| 9. Docs, commit message | Script gọi model nhỏ | diff stat → docs/changelog | Có kiểm tra i18n/layout nếu repo cần |
| 10. Đóng gói audit | Script (0 token) | Nhánh → `audit-pack.md` | Không vượt trần kích thước. Diff quá lớn thì tách feature. |
| 11. **Audit (Claude lần 2)** | Bạn, trong `claude` | audit-pack → `verdict.md`: APPROVE hoặc BLOCK kèm file:line | BLOCK thì các finding thành task cho bước 6, **tối đa thêm 1 vòng audit** |
| 12. Merge | Bạn | PR, có branch protection | — |

Có hai chi tiết giúp cổng kiểm tra thực sự đáng tin. Thứ nhất, **chạy cổng trong CI từ checkout sạch**, không tin log mà chính sandbox của agent sinh ra, vì agent ghi được vào sandbox đó. Thứ hai, đưa **riêng phần diff của file test bị coder sửa sau bước 5** vào gói audit. Một model yếu có thể "làm cho xanh" bằng cách nới lỏng test, và Claude cần thấy ngay điều đó.

### File bàn giao

```text
.team/<id>/
  request.md         # bạn viết: yêu cầu gốc, ràng buộc, mức nhạy cảm (public/private)
  repo-map.txt       # script sinh: cây file + chữ ký hàm/kiểu chính
  spec.md            # Claude lần 1, ≤120 dòng: mục tiêu, non-goals, thay đổi theo file,
                     #   hợp đồng dữ liệu inline, bất biến, rủi ro bảo mật
  tasks.md           # Claude lần 1: DAG task nhỏ; mỗi task: files to touch / do-not-touch / verify
  acceptance.md      # Claude lần 1: tiêu chí nghiệm thu dạng lệnh chạy được
  spec-questions.md  # (tùy chọn) model free phản biện spec, ≤30 dòng
  prereview.md       # reviewer free: findings ≤60 dòng, file:line + mức độ
  gates.log          # CI: kết quả test/lint/type/mutation, đã cắt gọn
  audit-pack.md      # script: gói nén cho Claude lần 2
  verdict.md         # Claude lần 2: APPROVE | BLOCK + danh sách file:line, ≤40 dòng
AGENTS.md            # quy ước repo, ngắn; mọi worker tự nạp
```

Hermes tự nạp `.hermes.md`, `AGENTS.md`, `CLAUDE.md` và `.cursorrules` trong workspace cho các subagent con ([delegation.md](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/features/delegation.md)). Vì vậy, hãy để quy ước code trong `AGENTS.md` thay vì lặp lại trong spec. Nên nhớ thêm: một `CLAUDE.md` dài và viết riêng cho Claude cũng sẽ bị nạp vào ngữ cảnh của worker miễn phí. Nếu repo dùng GitHub Spec Kit, chu trình `/speckit-specify → /speckit-plan → /speckit-tasks` của nó tương đương bước 3, vì Spec Kit không ràng buộc với agent nào ([Spec Kit](https://raw.githubusercontent.com/github/spec-kit/main/README.md)).

### Phác thảo cấu hình Hermes

Mọi key dưới đây đều được trích từ mã nguồn tài liệu Hermes trên nhánh `main` ngày 10/10/2026, qua một bộ tóm tắt khi tải trang. **Hãy kiểm lại tên key bằng `hermes doctor` và `hermes config` trước khi dùng.** Các base URL đánh dấu "chưa xác minh" lấy từ kiến thức nền của người làm ghi chú, không từ tài liệu nhà cung cấp.

```bash
# Cài đặt (README) — chạy dưới user không phải root, KHÔNG đăng nhập `claude` dưới user này
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
source ~/.bashrc
hermes setup                      # chọn Full Setup / Blank Slate (Quick Setup = Nous Portal trả phí)
hermes config set OPENROUTER_API_KEY sk-or-...   # ghi vào ~/.hermes/.env
chmod 600 ~/.hermes/.env
# trong ~/.hermes/.env thêm: TELEGRAM_ALLOWED_USERS=<id của bạn>; KHÔNG đặt GATEWAY_ALLOW_ALL_USERS=true
sudo hermes gateway install --system   # docs: dành cho VPS/headless
sudo hermes gateway start --system
hermes doctor
hermes kanban init
```

```yaml
# ~/.hermes/config.yaml — PHÁC THẢO, kiểm lại bằng `hermes doctor`
model:
  provider: custom
  base_url: https://generativelanguage.googleapis.com/v1beta/openai/  # chưa xác minh; hoặc chọn provider Gemini có sẵn qua `hermes model`
  default: <id Gemini Flash-Lite trong AI Studio>     # KHÔNG dùng ID 2.5
  key_env: GEMINI_API_KEY
fallback_providers:                 # kích hoạt tối đa 1 lần/lượt; cron ghim model không fallback
  - provider: openrouter
    model: <id model :free đang còn trên trang collection>
  - provider: custom
    base_url: https://api.mistral.ai/v1                  # chưa xác minh
    key_env: MISTRAL_API_KEY
    model: <model Mistral thuộc free tier>
provider_routing:
  data_collection: "deny"           # bật cho repo kín; sẽ loại nhiều endpoint free
terminal:
  backend: docker                   # local/ssh KHÔNG cô lập
  docker_forward_env: []            # không chuyển secret nào vào container
  container_memory: 5120
  docker_network: true              # false = --network=none (air-gap) nếu dependency đã có trong image
approvals:
  mode: smart
  cron_mode: deny
  unattended_mode: deny
  deny:
    - "git push --force*"
    - "rm -rf*"
skills:
  write_approval: true              # mặc định false; chặn model free tự sửa skill
memory:
  write_approval: true
kanban:
  max_in_progress: 2                # giữ dưới RPM của nguồn free
  failure_limit: 2
  default_workdir: /srv/work/<repo>-wt
```

```bash
# Một feature = các task ghim model riêng (profile tester/coder/reviewer phải tạo trước;
# lệnh tạo profile CHƯA xác minh — trang docs profiles trả 404)
hermes kanban create "F12 tests theo .team/F12/acceptance.md" --assignee tester  --model <mistral-id> --provider <provider>
hermes kanban create "F12 implement .team/F12/tasks.md"      --assignee coder   --model <free-coder-id> --provider openrouter
hermes kanban create "F12 viết .team/F12/prereview.md"       --assignee reviewer --model <gemini-flash-id> --provider <provider>
# nối phụ thuộc test → implement → review bằng verb `link` (tham số: hermes kanban --help)
hermes kanban set-model <task_id> <model-dự-phòng> --provider <provider>   # khi model free sập
hermes kanban watch
# cổng/thông báo không tốn token (script phải nằm trong $HERMES_HOME/scripts/)
hermes cron create "every 15m" --no-agent --script gates-notify.sh --deliver telegram --name "gates"
```

### Cô lập worker trên VPS

Backend Docker của Hermes bỏ mọi capability trừ `DAC_OVERRIDE`, `CHOWN` và `FOWNER`, đặt `no-new-privileges` và `--pids-limit 256`. Backend `local` và `ssh` thì **không cô lập**. Quan trọng hơn: **backend container bỏ qua kiểm tra lệnh nguy hiểm** vì coi container là ranh giới ([security.md](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/security.md)). Vậy an toàn phụ thuộc vào thứ bạn mount và chuyển vào container, không phụ thuộc vào cơ chế approval. Hermes tự loại các biến môi trường có tên chứa KEY, TOKEN, SECRET, PASSWORD… khỏi terminal. Gateway mặc định từ chối mọi người, chỉ cho phép người trong allowlist. OpenCode không có sandbox riêng, và `--yolo` của Qwen cũng không phải sandbox. Vì vậy `--auto` hay `--yolo` chỉ an toàn bên trong container. Thêm các lớp sau cho chắc. Chỉ mount đúng worktree của feature. Dùng GitHub token chỉ có quyền trên một repo. Bật branch protection trên `main` để agent chỉ push được lên nhánh feature. Bind dashboard vào localhost và truy cập qua SSH tunnel. Cập nhật lên v0.21.6 vì bản này vá lỗi thực thi git filter từ repo lạ. Về tài nguyên, các nguồn bên thứ ba báo Hermes chạy được với 2 GB RAM khi chỉ dùng CLI ([BinaryLane](https://support.binarylane.com.au/support/solutions/articles/11000137513-installing-hermes-agent-on-binarylane)), cần khoảng 4 GB khi có gateway và cron ([EvoMap](https://evomap.ai/blog/self-host-hermes-agent-vps)), và khoảng 2 vCPU/8 GB khi chạy Docker ([Hostinger](https://www.hostinger.com/in/tutorials/?p=132539)). VPS chỉ có CPU thì chỉ chạy nổi Gemma 4 E2B/E4B (4-bit), và chỉ để phân loại hoặc viết commit message. Số đo duy nhất có được là trên Raspberry Pi 5 (khoảng 3 token/s) và trên laptop (khoảng 17 token/s) ([Google LiteRT-LM](https://developers.google.com/edge/litert-lm/models/gemma-4)), nên hãy tự đo VPS của bạn bằng `llama-bench`.

## Hai lần dùng Claude: đúng điều khoản và tốn ít quota nhất

### Vì sao bạn phải tự gõ lệnh `claude`

Gói Pro được dùng bằng cách đăng nhập vào Claude hoặc Claude Code. Nếu biến `ANTHROPIC_API_KEY` đang được đặt, Claude Code sẽ dùng nó và **tính tiền theo API**, không trừ vào gói ([Claude Code costs](https://code.claude.com/docs/en/costs), [Anthropic support](https://support.claude.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan)). Các nguồn thứ cấp mô tả ba đợt siết của Anthropic. Ngày 09/01/2026, Anthropic chặn phía server các công cụ bên thứ ba như OpenCode, Cline và RooCode dùng OAuth của gói Pro/Max ([The New Stack](https://thenewstack.io/?p=22822734)). Tháng 02/2026, điều khoản giới hạn token OAuth của gói thuê bao cho Claude Code và Claude.ai, không bao gồm Agent SDK ([Gigazine](https://gigazine.net/gsc_news/en/20260220-anthropic-third-party-block)). Ngày 04/04/2026, Anthropic thông báo hạn mức gói thuê bao không còn dùng được với harness bên thứ ba như OpenClaw ([implicator.ai](https://www.implicator.ai/anthropic-cuts-openclaw-from-claude-subscriptions-citing-unsustainable-compute-costs/)). Google cũng từng có một đợt khóa tài khoản hàng loạt với lỗi 403 "ToS violation" khi người dùng đăng nhập Gemini/Antigravity bằng OAuth qua CLI mã nguồn mở bên thứ ba ([diễn đàn Google](https://discuss.ai.google.dev/t/urgent-mass-403-tos-bans-on-gemini-api-antigravity-for-open-source-cli-users-paid-tier/124508)).

Hermes có sẵn skill `claude-code` để điều khiển `claude -p` hoặc chạy `claude` trong tmux ([SKILL.md](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/skills/autonomous-ai-agents/claude-code/SKILL.md)). Tức là về kỹ thuật thì làm được. Nhưng **không có nguồn chính thức nào xác nhận việc một agent tự động gọi `claude -p` bằng tài khoản Pro là được phép**, và các ghi chú cũng không đọc được trang điều khoản gốc của Anthropic. Thiết kế an toàn vì vậy là: bạn tự chạy `claude` một cách tương tác, trên laptop hoặc qua SSH dưới một user Linux riêng mà user của Hermes không đọc được thư mục `~/.claude`. Hermes không cài và không đăng nhập Claude. Không đặt `--provider anthropic` cho task kanban (cách này cần API key và tính tiền riêng). Không đưa phiên đăng nhập Pro vào claude-code-router, OpenCode hay Goose ACP. Các điểm **chưa được xác nhận** gồm: (a) agent gọi `claude -p` thay bạn có hợp lệ không; (b) con số cụ thể của hạn mức 5 giờ và hạn mức tuần; (c) giá gói Pro theo khu vực ở Việt Nam; (d) Fable có hạn mức tuần riêng hay không.

### Gói Pro thực sự cho bạn những gì

Pro có giá $20/tháng, hoặc $17/tháng nếu trả trước $200 cho cả năm. Gói gồm Opus, Sonnet, Haiku và Claude Code; Fable tính vào usage credits ([claude.com/pricing](https://claude.com/pricing)). Có một hạn mức phiên reset mỗi 5 giờ và một hạn mức tuần **dùng chung cho mọi model và mọi bề mặt**: claude.ai, Claude Code, Desktop và cả các phiên cloud ([Pro plan](https://support.claude.com/en/articles/8325606-what-is-the-pro-plan), [Claude Code on the web](https://code.claude.com/docs/en/claude-code-on-the-web)). Anthropic không công bố con số tuyệt đối. Ngày 06/05/2026, Anthropic nhân đôi hạn mức 5 giờ của Claude Code ([Anthropic](https://www.anthropic.com/news/higher-limits-spacex)). Một điểm quan trọng: **trên Pro, Claude Code mặc định chạy Opus 5.5** (effort medium) ([model-config](https://code.claude.com/docs/en/model-config)), là lựa chọn tốn quota nhất mỗi lượt. Vì vậy, chọn model là việc phải làm có chủ đích.

### Chiến thuật cho hai lần dùng Claude

| | Lần 1: spec | Lần 2: audit |
|---|---|---|
| Model | `/model opusplan` cho T2/T3 (Opus lập kế hoạch, Sonnet thực thi); `/model sonnet` cho việc thường | `/model sonnet`, `/effort` thấp hoặc medium. Opus chỉ dùng cho auth, thanh toán, migration. |
| Đầu vào | `request.md` + `repo-map.txt` + **đúng** các file liên quan | **Chỉ** `audit-pack.md` |
| Đầu ra | `spec.md` tối đa 120 dòng, `tasks.md`, `acceptance.md` | `verdict.md` tối đa 40 dòng |
| Không làm | Không viết code triển khai, không đọc cả repo | Không chạy lại test (đã có `gates.log`), không mở file ngoài pack trừ khi có nghi vấn cụ thể |
| Sau đó | `/clear` | `/clear` |

Đòn bẩy lớn nhất là bắt **tiêu chí nghiệm thu phải chạy được bằng lệnh ngay từ spec**. Khi đó audit chỉ còn là *so sánh* diff với tiêu chí, không còn là *điều tra* lại từ đầu. Mọi việc tính được bằng máy (test, lint, type-check, mutation) để CI trả lời, và Claude chỉ phán xét thiết kế, bảo mật và mức độ khớp spec. Các mẹo chính thức của Anthropic củng cố hướng này ([Claude Code costs](https://code.claude.com/docs/en/costs)). Dùng `/clear` giữa các việc không liên quan. Giữ `CLAUDE.md` dưới khoảng 200 dòng. Tắt các MCP server không dùng; đặc biệt đừng gắn PAL MCP hay claude-code-router vào phiên Claude, vì mỗi tool đều chiếm ngữ cảnh. Dùng hook để lọc output test trước khi nó tới model. **Không dùng subagent hay agent team** (agent team tốn khoảng 7 lần token). Không chạy song song nhiều phiên cloud, vì phiên song song tiêu hạn mức theo tỷ lệ. Xem `/usage` để biết phần nào đang tốn. Prompt cache trên gói thuê bao sống **1 giờ**, nên hãy gom việc viết spec và audit của vài feature vào cùng một khung khoảng một giờ. Nghỉ quá 1 giờ thì toàn bộ ngữ cảnh mất cache. Có thể hạ ngưỡng tự compact bằng `CLAUDE_CODE_AUTO_COMPACT_WINDOW`.

Script đóng gói audit chỉ cần git, không cần model:

```bash
#!/usr/bin/env bash
# build-audit-pack.sh <id> [base]  — chạy sau khi CI xanh
set -euo pipefail
id=$1; base=${2:-main}; d=.team/$id; out=$d/audit-pack.md
{
  echo "# Audit pack $id"
  echo "## Acceptance";            cat "$d/acceptance.md"
  echo "## Diffstat";              git diff --stat "$base"...HEAD
  echo "## Gates (CI, cắt gọn)";   tail -n 60 "$d/gates.log"
  echo "## Pre-review findings";   cat "$d/prereview.md"
  echo "## Test files changed";    git diff -U3 "$base"...HEAD -- 'tests/**' '**/*test*'
  echo "## Diff";                  git diff -U3 "$base"...HEAD -- . ':(exclude)*.lock' ':(exclude)package-lock.json'
} > "$out"
wc -l "$out"
```

Prompt audit mẫu: *"Chỉ đọc `.team/F12/audit-pack.md`. Đối chiếu diff với Acceptance. `gates.log` là kết quả CI, không cần chạy lại. Trả về tối đa 40 dòng: `VERDICT: APPROVE|BLOCK`; các lỗi chặn (file:line, lý do, cách sửa); tối đa 5 dòng nhận xét không chặn. Đặc biệt chú ý mục 'Test files changed'."* Nếu hết quota Pro giữa chừng mà cần audit gấp, bật usage credits là một lựa chọn rẻ. Sonnet 5.5 có giá API $2/$10 cho mỗi triệu token ([models overview](https://platform.claude.com/docs/en/about-claude/models/overview)). Một pack 30.000 token vào và 2.000 token ra tốn khoảng **$0,08**, chưa tính token thinking (Sonnet 5.5 không tắt được thinking). Cần biết thêm là prompt cache khi dùng credits chỉ sống 5 phút.

## Chi phí, quyền riêng tư, Việt Nam và những con số phải tự kiểm

### Bảng chi phí hàng tháng

| Hạng mục | Lộ trình A: thêm $0 | Lộ trình B: thêm $10 một lần | Lộ trình C: khoảng $6–20/tháng |
|---|---|---|---|
| Claude Pro (trả theo năm) | $200/năm ≈ $16,7/tháng, đã trả | như A | như A |
| VPS | Đã có | Đã có | Đã có |
| Hermes, OpenCode, Qwen Code, Goose | $0 (MIT/Apache-2.0) | $0 | $0 |
| Gemini free, Mistral free, Groq, NVIDIA, Cloudflare, Zen free | $0 | $0 | $0 |
| OpenRouter `:free` | 50 lượt/ngày | **$10 một lần → 1.000 lượt/ngày, giữ nguyên kể cả khi số dư về $0** | như B |
| Worker trả phí | — | — | **OpenCode Go $10/tháng** (Kimi K3, GLM-5.3, DeepSeek V4.x, giới hạn tiền theo 5 giờ/tuần/tháng), **hoặc** DeepSeek V4.1 Flash: khoảng $0,15/task ngoài giờ cao điểm, tức khoảng $6 cho 40 task |
| Audit khi hết quota Pro | Chờ reset | Chờ reset | Usage credits, khoảng $0,08 mỗi lần chưa tính thinking |
| **Tổng chi thêm** | **$0** | **$10 một lần** | **khoảng $6–20/tháng** |

Con số $0,15/task là phép tính trong ghi chú với giả định 100 lượt, ngữ cảnh 50.000 token, 90% cache hit và khoảng 1.000 token đầu ra mỗi lượt. Giá DeepSeek `deepseek-flash` ngoài giờ cao điểm là $0,15 cho input không cache, $0,003 cho input có cache và $0,60 cho output mỗi triệu token, và **gấp đôi trong giờ cao điểm** ([DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/)). Các gói phẳng khác để tham khảo: Z.ai GLM Coding Lite $18/tháng ($12,60 nếu trả năm) ([Digital Applied](https://www.digitalapplied.com/blog/glm-coding-plan-worth-it-2026-value-analysis)), MiniMax Token Plan $20–22 ([MiniMax](https://platform.minimax.io/docs/guides/pricing-token-plan)), Ollama Pro $20 kèm $60 usage ([Ollama](https://ollama.com/pricing)), Kimi Moderato $19 ([Kimi](https://www.kimi.com/en/help/membership/membership-pricing)). Thứ tự nên làm: chạy A trong 1–2 tuần để đo, lên B vì đây là khoản có đòn bẩy cao nhất, và chỉ lên C khi tỷ lệ qua cổng của coder miễn phí thấp. Chọn OpenCode Go nếu muốn dùng model mở mạnh nhất. Chọn DeepSeek trả theo token nếu khối lượng việc ít.

### Free tier nào có thể học từ code của bạn

Gói free của Gemini dùng dữ liệu để cải thiện sản phẩm. Chỉ khi liên kết thanh toán (Tier 1), dữ liệu mới không bị dùng ([pricing](https://ai.google.dev/gemini-api/docs/pricing)). Chính sách cho người dùng ngoài EU/UK/EEA lại khác ([OpenRouter blog](https://openrouter.ai/blog/tutorials/free-llm-apis-compared/)). Việt Nam nằm ngoài khu vực đó, nên hãy giả định dữ liệu bị dùng. Mistral free cũng nên coi là có huấn luyện. Trên OpenRouter, tài khoản có công tắc privacy riêng cho model free, và một đợt kiểm tra thấy 9/19 model free chạy trên host cho phép huấn luyện, còn endpoint Google AI Studio lưu dữ liệu 55 ngày ([TrueFoundry](https://www.truefoundry.com/blog/openrouter-free-models-whats-actually-free-and-what-it-costs-you)). Trên OpenCode Zen, một số model free có thể dùng dữ liệu, Nemotron Free được dặn "đừng gửi dữ liệu mật", và Muse Spark Contributor huấn luyện model của Meta ([Zen docs](https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/web/src/content/docs/zen.mdx)). Ghi chú không tìm thấy điều khoản dữ liệu của Groq, Cloudflare, NVIDIA, SambaNova, Z.ai, và không xác minh được điều khoản của DeepSeek. Quy tắc thực hành: **repo công khai hoặc code bỏ đi** thì dùng nguồn nào cũng được. **Repo kín** thì chỉ dùng endpoint không huấn luyện (Zen Space Bunny/LongCat/Step, Gemini trả phí, OpenRouter với `data_collection: "deny"`). Dù trường hợp nào, **không bao giờ để secret hay dữ liệu khách hàng trong repo** mà worker đọc được.

### Những vướng mắc riêng khi ở Việt Nam

**NVIDIA build.nvidia.com** là nguồn duy nhất có lỗi đăng ký ghi nhận cụ thể cho Việt Nam. Nhiều người dùng số +84, kể cả Viettel, báo không nhận được OTP, gặp lỗi dropdown hoặc thông báo "exceeded limits" trong các thread từ tháng 8 đến tháng 10/2026. NVIDIA nói kỹ sư đang xử lý nhưng chưa có bản sửa ([thread 1](https://forums.developer.nvidia.com/t/phone-verification-not-working-from-vietnam-84-need-manual-api-key-activation/375499), [thread 2](https://forums.developer.nvidia.com/t/unable-to-receive-sms-otp-for-vietnam-84-phone-number/385184)). Nếu gặp lỗi này, hãy viết cho help@build.nvidia.com. Với Google: danh sách quốc gia của Antigravity bị cắt trước chữ "V" nên chưa xác định được, và Google kiểm tra quốc gia ghi trong điều khoản tài khoản của bạn ([Antigravity FAQ](https://www.antigravity.google/docs/faq)). Có báo cáo lỗi giả "User location is not supported" ([forum](https://discuss.ai.google.dev/t/antigravity-cli-intermittently-rejects-gemini-requests-with-false-user-location-is-not-supported/177287)), và có trường hợp IP Việt Nam bị chặn dù Việt Nam nằm trong danh sách vùng của API ([forum](https://discuss.ai.google.dev/t/api-access-issue-region-restriction/107160)). Nếu VPS đặt ở nước khác với quốc gia của tài khoản Google, hãy thử trước khi dựa vào. Codex thì có trang trợ giúp tiếng Việt và có trong mọi gói kể cả Free/Go ([OpenAI help vi-VN](https://help.openai.com/vi-vn/articles/11369540-using-codex-with-your-chatgpt-plan)). Bạn cũng đã dùng ChatGPT Plus từ Việt Nam, nên đây là con đường đã có tiền lệ chạy được. **Giờ cao điểm của DeepSeek là 01:00–04:00 và 06:00–10:00 UTC từ thứ Hai đến thứ Sáu, tức 08:00–11:00 và 13:00–17:00 giờ Việt Nam**, trùng đúng giờ làm việc. Hãy xếp lịch cho các lô implement chạy buổi tối, ban đêm hoặc cuối tuần để giá giảm một nửa. Ghi chú chưa xác nhận được Groq, Mistral, OpenRouter, Cloudflare và Z.ai có chặn Việt Nam hay không.

### Danh sách kiểm lại trong console

Các ghi chú được thu thập ngày 10/10/2026, trong một môi trường chặn truy cập trực tiếp phần lớn trang nhà cung cấp (Google AI, OpenRouter, Groq, Mistral, NVIDIA, DeepSeek, Z.ai…). Con số của các nhà cung cấp này đến từ bản tóm tắt kết quả tìm kiếm hoặc blog tổng hợp, mà nhiều blog tổng hợp là trang tự sinh gần như trùng nhau. Chỉ các trang của Anthropic và GitHub được đọc trực tiếp; GitHub ở đây gồm docs nguồn của Hermes, OpenCode, Qwen Code và Gemini CLI.

| Cần kiểm | Ghi chú đang nói | Kiểm ở đâu |
|---|---|---|
| RPD/RPM của Gemini free theo từng model | 3.8 Flash khoảng 20, Flash-Lite khoảng 500; nơi khác nói 250–1.500 | AI Studio → trang rate limit của project |
| Danh sách và hạn mức OpenRouter free | 20 RPM; 50 → 1.000 lượt/ngày; danh sách xoay vòng | Trang collections/free-models; mục Privacy của tài khoản |
| Mistral | 1 req/s, 500.000 TPM, 1 tỷ token/tháng; chưa rõ model nào free | Console → Limits; Admin → Privacy |
| Groq | 30 RPM, 1.000 RPD, 8.000 TPM, 200.000 TPD | Console → Limits |
| NVIDIA | Khoảng 40 RPM; OTP cho số +84 | Góc phải trên build.nvidia.com |
| Z.ai GLM-4.7-Flash | 1 request đồng thời | Thử trực tiếp |
| Antigravity / Codex Free | Không công bố | `agy -p /usage --output-format json`; `/status` trong Codex |
| Claude Pro | Không có con số; mặc định Opus 5.5 | `/usage`, `/status`, `/model`, Settings → Usage |
| DeepSeek | Giá V4.1 Flash, giờ cao điểm; số phận V4 Pro sau 14/09 | Trang pricing và change log |
| OpenCode Zen/Go | Danh sách model free, chính sách dữ liệu từng model | Docs Zen/Go |
| Mọi key YAML của Hermes | Trích từ docs nguồn qua bộ tóm tắt | `hermes doctor`, `hermes config`, `hermes kanban --help` |

## Áp đội hình vào các vai của repo này

Các vai trong `.claude/agents/` của repo đều là subagent Claude Code đặt `model: sonnet`. Mỗi lần gọi một subagent như vậy đều trừ vào quota Pro, đúng thứ bạn đang thiếu. Trong đội hình này, các vai đó vẫn giữ *chức năng*, nhưng người đảm nhận được đổi sang worker miễn phí bên ngoài. Riêng hai lần dùng Claude vẫn do phiên chính của bạn thực hiện, nên sổ ngân sách agent (`artifacts/handoff/agent-budget.json`) gần như không bị tiêu.

| Vai trong repo | Người đảm nhận trong đội này | Artifact và trần độ dài (theo `CLAUDE.md`) |
|---|---|---|
| `requirement-analyst` | Bạn cùng Claude ở lần 1. Model free có thể soạn trước danh sách câu hỏi mở. | Giải quyết khi ambiguity = 2 |
| `architect` | Claude lần 1 | `artifacts/architecture/<id>.md` ≤200 dòng, `artifacts/plans/<id>.md` ≤120 dòng |
| `architecture-critic` | Tùy chọn: model free mạnh (GLM/Kimi/Nemotron), một vòng | `artifacts/critiques/<id>.md` ≤80 dòng |
| `implementer` | Worker free `coder` (Hermes hoặc OpenCode) | — |
| `test-engineer` | Worker free `tester` cộng `scripts/mutation_check.py` | — |
| `code-reviewer` / `code-reviewer-t3` | Tách làm hai: review chéo free (lọc) và Claude lần 2 (quyết) | `artifacts/reviews/<id>.md` ≤120 dòng |
| Các kiểm tra xác định | `scripts/mutation_check.py`, `scripts/i18n_check.py`, `scripts/layout_check.py`; CI chạy trên VPS qua `gh variable set CI_RUNNER --body self-hosted` (`docs/ci-runner-mode.md`) | 0 token |

`scripts/route.py` vẫn hữu ích để quyết định một yêu cầu cần chạy bao nhiêu bước của quy trình. T0 chỉ cần worker free và cổng kiểm tra, không cần Claude. T1 thêm review chéo free, còn Claude audit thì tùy chọn hoặc kiểm ngẫu nhiên. T2 chạy đủ quy trình. T3 chạy đủ, dùng Opus ở cả hai lần, và chỉ dùng endpoint không huấn luyện nếu code là code kín. Muốn áp dụng chính thức cho repo này, bạn cần sửa `agent-routing/policy.yaml`, vì hiện tại chính sách mặc định T1+ có `code-reviewer` là subagent Claude. Đây là thay đổi chính sách, nên hãy làm có chủ đích chứ đừng để nó diễn ra ngầm.

## Kết luận

Thứ khan hiếm thực sự không phải token Claude mà là **độ tin cậy của phần miễn phí**. Model, quota và điều khoản thay đổi theo tháng, còn ba thứ giữ nguyên là định dạng spec, các cổng kiểm tra xác định và gói audit. Vì thế hãy đầu tư công sức vào ba thứ đó. Model chỉ nên là một dòng trong `config.yaml`, đổi được trong năm phút khi nguồn miễn phí tiếp theo bị đóng. Từ đó suy ra hai điều. Một, vai trò đáng tiền nhất của Claude là biến sự mơ hồ thành tiêu chí chạy được bằng lệnh. Spec càng "thực thi được" thì lần audit cuối càng rẻ, và một phiên Sonnet ngắn đọc pack 30.000 token có giá trị hơn nhiều so với Opus đọc cả repo. Hai, khoản $10 cho OpenRouter mang lại nhiều sức chịu đựng hơn bất kỳ lần nâng gói Claude nào, vì nâng Claude không bù được thứ phần miễn phí đang thiếu.

Bước tiếp theo đáng làm là chạy thử hai tuần và ghi lại ba chỉ số: tỷ lệ qua cổng ở bước 7 theo từng model, tỷ lệ BLOCK của Claude ở bước 11, và phần trăm quota Pro tiêu cho mỗi feature theo `/usage`. Không benchmark công khai nào đo được năng lực viết test hay review của model mở. Bộ số liệu này sẽ là bài đánh giá nội bộ cho thấy model nào đáng giữ, và có cần lên lộ trình C hay không.
