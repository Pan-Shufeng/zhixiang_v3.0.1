# 知向 × DSH 本地接口（3.1.0-dsh）

默认本地网页 `http://127.0.0.1:8186`；`GET /api/health` 返回应用身份、版本和进程号，`GET /api/bootstrap` 返回问题、来源、设置及构建时间。独立网页和 DSH MCP 调用同一个本地后端与数据目录。

## 搜索与原文

`POST /api/search` 接受 `{question, period?, question_id?, query?, focus?}`，其中 `focus` 是 `general|official|perspectives`。自然语言默认经固定版本 DSH 原生 DeepSeek 搜索；`query` 是用户明确覆盖的关键词。返回 `202 {job_id,question_id}`，用 `GET /api/jobs/{job_id}` 轮询 `queued|running|done|error`。搜索结果存入问题的 `search_report`，含 `provider`、`query_plan`、`actual_queries`、`failed_queries`、`search_runs`、`candidates` 与 `notice`。候选只含来自真实搜索工具的 URL、标题、摘要与不确定的时间线索；不等于原文，也不进入分析上下文。

`GET/POST /api/search/settings`：默认 `dsh`，可选 `public`（Bing RSS）或用户自己提供 Key 的 `tavily`。`configured` 只表示凭据配置就绪，不保证搜索成功；前端永不读取 Key。DSH 搜索使用 DeepSeek 账户额度，AI 分析也用配置的模型。不会因为 DSH 失败而自动偷偷切到另一个付费服务。

`POST /api/questions/{id}/search-import` 接受 `{candidate_ids:[...], analyze?:boolean}`，只读取当前问题、当前搜索报告中的候选。逐条记录 `added|duplicate|failed`，成功的原文才进入 `source_ids`；拒绝抓取或验证码页不以摘要顶替正文。`GET /api/sources/{id}` 读取已保存正文和出处，原件下载由其 `file_url` 指向。`POST /api/questions/{id}/source` 用于手动补充来源。

## 分析、判断、比较

`POST /api/analyze` 可按已保存问题与来源生成分析；AI 输出必须对应真实 `source_id`，但引用存在不等于事实已核对。`POST /api/questions/{id}/judgment` 接受 `{text, source_ids, unresolved}`，保存用户确认的判断、关联资料、待核实点与版本历史。`POST /api/questions/{id}/compare` 将新增材料与当前判断比较，不静默覆盖旧判断；变更需用户再次保存。`GET /api/questions/{id}` 与 `GET /api/export/{id}` 提供重载和导出。每个问题同一时间只允许一个长任务；失败后已保存材料与旧判断仍保留。

## MCP / DSH

`backend/mcp_server.py` 是 stdio JSON-RPC MCP 桥，只向 stdout 写协议。`initialize`、`tools/list`、`tools/call` 与通知遵循 MCP；工具为 `zhixiang_search`、`zhixiang_list_questions`、`zhixiang_get_question`、`zhixiang_get_source`、`zhixiang_import_sources`、`zhixiang_add_source`、`zhixiang_analyze`、`zhixiang_save_judgment`、`zhixiang_compare`。长任务轮询同一个后端，数据不在 MCP 端复制。DSH Web 用官方 `dsh-mcp-client` 读取 `dsh/zhixiang.patch.yml` 配置；第三方客户端示例在 `MCP配置示例.json`。

`official_hint` 只是域名形式提示，不是网站归属或财报口径认证；`relevance` 是粗筛。对最新财报问题，时间改写只是搜索线索，最终发布日期和报告期必须回原文核对。虚构或未公开经营数据的问题不能因为有部分关键词匹配就给出数字。
