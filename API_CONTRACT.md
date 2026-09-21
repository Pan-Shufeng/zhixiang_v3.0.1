# 知向联网版接口（1.1.0-web）

独立应用 `zhixiang-web`，默认地址 `http://127.0.0.1:8186`。原版不受影响。

`POST /api/search` 接受 `{question, period?, question_id?, query?, focus?}`。focus 为 `general`、`official`、`perspectives`，缺省 general。query 可覆盖问题生成的基础关键词；选择角度会追加对应关键词。时间范围仅加入查询，不保证强日期过滤。返回 HTTP 202 `{job_id,question_id}`。不需要本地资料即可建立新问题。显式 query 不调用模型；省略 query 且已配置模型时，最多调用1次模型将问题整理为最多2条短查询。模型只能提议查询词，不能生成URL、来源、搜索结果或问题答案。未配置模型、额度/网络/结构失败时直接使用原问题搜索。已有问题的标题、资料、判断保持原有内容，新查询独立保存。

轮询 `GET /api/jobs/{job_id}`：status 为 queued/running/done/error，message 是当前阶段。成功时 `job.result` 就是完整 question。失败时 `job.error` 是已去除底层请求细节的消息；重新 GET question 能取得保留状态。

搜索成功后 `question.search_report`：

```json
{"query":"实际查询词","provider":"bing_rss 或 tavily","searched_at":"UTC ISO时间","focus":"general","candidates":[{"id":"candidate_...","title":"搜索标题","url":"https://...","publisher":"来源域名","snippet":"搜索摘要","status":"candidate","provenance":"search_snippet","published_at":"可选：仅Tavily提供且未核对","search_index_date":"可选：RSS时间，不能视为发布日期","date_note":"搜索日期边界说明"}],"notice":"边界说明","scope":"实时联网搜索候选；尚未自动读取正文"}
```

候选不是正文，不进入 source_ids，不参与模型上下文。空结果保留空 candidates；不会用本地案例补充。成功的新搜索将旧 report 放入 search_history。失败保留上次成功 report，并记录 search_attempt 的 status=error、query、message。focus 只是查询方向，不认证来源官方性或观点平衡。

搜索报告另有 `query_plan={mode:'model'|'direct'|'fallback',queries:string[],notice:string}`、`actual_queries:string[]`（成功执行的查询）、`failed_queries:[{query,message}]`、`search_runs`（每条查询的服务与时间）。最多2次真实搜索合并去重到10个候选。候选 `relevance:'matched'|'partial'` 和 `relevance_notice` 为透明的关键词筛查，不能当成语义核验；登录/账号页和完全不匹配主题词的候选会排除。财报问题但只显示公司介绍的候选标 partial，不默认选取。计划中的主体英译未经过独立验证，用户可检查并修改查询。

`POST /api/questions/{id}/search-import` 接受 `{candidate_ids:[...],analyze:false}`，一次1至8个当前搜索候选 ID。旧搜索或其他问题 ID 拒绝；返回相同 job 格式。默认只读取，不调用模型。逐条读取公开 HTML/文本/PDF，并按原始字节 SHA-256 去重。拒绝或验证页面不绕过；失败摘要不替代原文。

每条结果立即保存到 `question.search_import_report.items`：`{candidate_id,title,url,status:'added'|'duplicate'|'failed',source_id?,message}`。对应候选 status 始终 candidate，另附 `import_status`、`source_id?`、`import_error?`、`imported_at`。只有成功原文进入 source_ids；未附加过的原文进入 pending_source_ids。读取失败可继续选其他候选、打开原链接或手动粘贴正文。

导入报告的 analysis_status 为 not_requested / skipped_saved_judgment / done / failed / no_sources，另有可选 analysis_error 和 notice。`analyze:true` 且已有 judgment 时不调用自动分析；用户可使用现有 compare。首次分析失败保留成功原文和逐条结果。所有正文读取失败时不调用模型。job.done 表示导入流程结束，是否成功读取请检查每条 items，不能仅凭 job.done 宣称有正文。

`GET /api/search/settings` 返回 `{provider:'public'|'tavily',configured:boolean,tavily_configured:boolean,notice:string}`。public 默认无需 Key，configured=true 只代表配置就绪，不保证网络可用。`POST /api/search/settings` 接受 `{provider?,api_key?,clear_api_key?:true}`。省略或空 api_key 保留原 Key；clear_api_key=true 明确删除且优先于 api_key。Key 仅保存于本机 config/search.json，永不回传前端、不进入任务记录；不与模型 Key 共用。

Tavily 只调用固定 `https://api.tavily.com/search`，basic 搜索、10条上限、include_answer=false、include_raw_content=false、auto_parameters=false。不自动切换付费供应商、不自动重试验证。依据 [Tavily 官方 Search 文档](https://docs.tavily.com/documentation/api-reference/endpoint/search) 实现，真实付费调用未在后端自动测试中执行。

同一个问题已有排队/运行任务时新任务返回 409。判断可以保存；分析保存只更新 analysis、不覆盖判断。程序退出中断后正在运行的 job 标为 error，已保存逐条资料保留。

模型调用有总等待时限：搜索词规划25秒且最多320个输出token，资料分析/比较150秒。请求的连接时间、持续空白/keepalive也受主任务等待上限约束。超时后任务结束、晚到模型结果丢弃，不自动重试；已读原文、旧分析与用户判断保留。最多2个未结束网络worker，超时但连接尚未释放的worker继续占位，后续请求快速提示等待而不无限创建后台请求。底层连接释放时间取决于HTTP库及远端行为，总时限不承诺撤回已发往服务商的请求或费用。
