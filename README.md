# 知向 · 多客户端连接版（v3.1.1）

知向帮助你围绕一个商业问题**找公开依据、核对原文、保存自己的判断，再用新材料检验它**。可以只用独立网页；也可以在 DeepSeek Harness（DSH）对话中调用同一份知向资料与判断。

v3.1.1 新增“连接 AI 客户端”：Codex / WorkBuddy 可备份并合并本地 MCP 配置、移除本连接；已有 DSH 可加载独立连接层启动。客户端调用时按需启动知向；`zhixiang_open_workspace` 返回可在内置浏览器打开的本机网页。客户端界面未改造，资料与判断共用。支持情况与真实验证边界见 [连接验收](连接验收.md)。

## 给体验者

从 [Releases](https://github.com/Pan-Shufeng/zhixiang_v3.0.1/releases) 下载 **v3.1.1 多客户端连接版** 的 Windows x64 ZIP，完整解压，双击 `启动知向联网版.cmd`。已有 AI 客户端的同学可双击 `连接我的AI客户端.cmd`。浏览器中的主要入口是“开始一个问题”“我的判断”“可用资料”和“连接 AI 客户端”。`启动DSH对话.cmd` 是随包 DSH 的可选入口。先看 `先读我.txt` 和 `使用说明.md`；搜索流程的历史实测及局限见 [真实验收报告](验证报告.md)，本次连接实测见 [连接验收](连接验收.md)。

ZIP 内置 Python、Node.js、固定版本 DSH，以及作者明确授权的课堂试用 DeepSeek Key；源码仓库不存该 Key。试用额度耗尽或账户拒绝时，在线搜索与模型分析会停止，已有材料和判断仍可打开；使用者也能在页面里配置自己的 DeepSeek Key。开源不代表外部 API 免费，也不承诺账户绝不会发生费用。

## 三条真实入口，共用一份数据

- **独立网页**：自然语言问题调用 `@deepseek-ai/dsh-web-search-deepseek` 固定版本的原生搜索组件。它返回结构化 URL 候选；知向读取选中的网页原文、记录来源、组织证据与缺口，保存用户判断及版本，比较后来加入的新材料。
- **DSH 对话**：官方 DSH Web 配置 `@deepseek-ai/dsh-mcp-client`，通过本项目 MCP 工具读取和修改同一个知向后端。DSH 自己的 `web_search` 仍属于 DSH；知向工具负责来源入库、分析、判断版本和比较。两个网页是独立页面，不冒充嵌入式同一界面。
- **其他 MCP 客户端**：`启动知向MCP.cmd` 提供相同本地工具，包括搜索、列问题、读问题/来源、导入来源、分析、保存用户确认的判断和比较。连接示例在 `MCP配置示例.json`。

搜索结果只是候选，模型正文不会被当成搜索来源。网页无法读取时会明确失败；保存判断要用户确认，比较建议不会静默覆盖旧判断。来源域名、标题和摘要不等于事实核验。没有可核验的经营数据时，知向不能凭空给出营收。

## 源码、模型与数据

- `dsh/package.json` + `dsh/pnpm-lock.yaml`：DSH `0.1.7-rc.2`，其中独立网页使用官方原生搜索提供方，DSH 对话使用官方 MCP 客户端。固定版本可能因上游开发预览更新而需要迁移。
- `dsh/search.mjs`：调用官方 DSH 搜索提供方的薄适配层；当前原生搜索请求使用 `deepseek-v4-flash`，只读取结构化搜索结果，不抓取模型正文里的链接。知向资料分析的课堂试用配置为 `deepseek-v4-pro`；两个调用都使用同一 DeepSeek 账户额度，使用者改填个人 Key 后会沿用其账户。
- `backend/search_web.py`：候选格式、初步相关性和可选公共搜索/Tavily；`backend/server.py`：本地数据、原文读取、分析、判断与历史；`backend/mcp_server.py`：stdio MCP；`frontend/src`：React 网页。
- 数据在解压目录 `data/`，个人配置在 `config/`，日志在 `logs/`。搜索问题发往 DeepSeek 或用户主动选择的搜索服务；被选中的网页由本机读取；分析把原文片段与问题发往配置的模型服务。DSH 会在本机 `data/dsh-home/` 保存它自己的会话。没有把个人 `data/` 打进发布包。
- 内置案例在公开包中只有作者整理的来源目录与说明；完整第三方文章/PDF 不随包再次分发。阅读原件需打开发布者网址。

## 从源码构建

Windows x64、Node.js 24.19.0、Python 3.13.15、pnpm 11（或兼容版本）。按 [构建说明](packaging/构建说明.md) 准备内置 Python、Node 和固定版本 DSH 依赖，再构建前端；最后显式提供获授权的试用配置运行 `py -3 packaging/build_package.py --trial-env <配置文件>`。它生成新的 DSH 集成 ZIP，不覆盖旧联网版 ZIP。

本项目代码为 [MIT](LICENSE)。DSH 上游为 [MIT](https://github.com/deepseek-ai/deepseek-harness/blob/master/LICENSE)，其第三方说明随包保留在 `第三方许可/`。公开源码欢迎修改；重新发布体验包前，请自行确认素材版权和试用 Key 的授权范围。
