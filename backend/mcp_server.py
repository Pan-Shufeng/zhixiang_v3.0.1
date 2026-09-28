"""stdio MCP bridge to the same local data service as the Zhixiang web UI.

Only JSON-RPC is written to stdout. The shared HTTP backend owns all data and
model work; this bridge never invents sources or silently confirms a judgment.
"""
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8", newline="\n")
BASE = "http://127.0.0.1:" + os.environ.get("ZHIXIANG_PORT", "8186")
CLIENT_NAME = ""
OPENER = build_opener(ProxyHandler({}))


def connection_event(stage, tool=""):
    try:
        api("POST", "/api/connections/event", {"client": os.environ.get("ZHIXIANG_CLIENT", "other"), "client_name": CLIENT_NAME, "stage": stage, "tool": tool})
    except Exception:
        pass  # Optional telemetry must never break the actual tool operation.


def api(method, path, payload=None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(BASE + path, data=body, method=method,
                      headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with OPENER.open(request, timeout=35) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("error", "")
        except (ValueError, UnicodeError):
            detail = ""
        raise ValueError(detail or f"知向服务返回 HTTP {error.code}") from None
    except URLError:
        raise ValueError("知向本地服务未启动，请先打开知向。") from None


def wait_job(start, timeout=145):
    jid = start.get("job_id")
    if not isinstance(jid, str):
        raise ValueError("知向没有创建后台任务。")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = api("GET", "/api/jobs/" + jid)
        if state.get("status") == "done":
            return state.get("result", {})
        if state.get("status") == "error":
            raise ValueError(state.get("error") or "知向任务失败。")
        time.sleep(0.7)
    raise ValueError("知向仍在处理；进度已保存，请稍后用问题 ID 读取。")


def tool(name, description, props, required=()):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": props,
                            "required": list(required), "additionalProperties": False}}


def string(desc):
    return {"type": "string", "description": desc}


def strings(desc):
    return {"type": "array", "items": {"type": "string"}, "description": desc}


TOOLS = [
    tool("zhixiang_open_workspace", "获取知向网页入口。在用户要求查看界面时，可用客户端内置浏览器打开该地址；无浏览器时展示链接。", {}),
    tool("zhixiang_search", "用固定版本 DSH 原生搜索寻找真实网页来源；返回候选和 question_id。摘要不是原文。",
         {"question": string("要判断的问题"), "period": string("时间范围"),
          "focus": {"type": "string", "enum": ["general", "official", "perspectives"]},
          "query": string("可选手动搜索词"), "question_id": string("继续已有问题时填写；否则创建新问题")}, ["question"]),
    tool("zhixiang_list_questions", "列出本机保存的问题及判断状态。", {}),
    tool("zhixiang_get_question", "读取搜索、已读来源、分析、判断历史与比较状态。",
         {"question_id": string("知向问题 ID")}, ["question_id"]),
    tool("zhixiang_get_source", "读取已保存来源的 URL、抓取时间、发布日期状态和至多 12000 字的真实正文；超过部分到网页查看原件。",
         {"source_id": string("已读来源 ID")}, ["source_id"]),
    tool("zhixiang_import_sources", "按候选 ID 读取网页原文并保存；失败时不能用摘要顶替。",
         {"question_id": string("知向问题 ID"), "candidate_ids": strings("本次搜索中的 1-8 个候选 ID"),
          "analyze": {"type": "boolean", "description": "是否额外调用知向模型分析；默认 false"}},
         ["question_id", "candidate_ids"]),
    tool("zhixiang_add_source", "将 DSH 找到的真实公开 URL 交给知向读取并保存。",
         {"question_id": string("知向问题 ID"), "url": string("真实公开 URL")}, ["question_id", "url"]),
    tool("zhixiang_analyze", "分析成功读取的原文，输出有来源 ID 的发现和缺口。",
         {"question_id": string("知向问题 ID")}, ["question_id"]),
    tool("zhixiang_save_judgment", "只有用户明确确认保存时才调用；保存判断、关联来源及未决问题的新版本。",
         {"question_id": string("知向问题 ID"), "text": string("用户确认的判断"),
          "source_ids": strings("已读来源 ID"), "unresolved": strings("仍待核实的问题")},
         ["question_id", "text"]),
    tool("zhixiang_compare", "新增原文后比较旧判断；仅返回建议，不覆盖旧判断。",
         {"question_id": string("知向问题 ID")}, ["question_id"]),
]


def call_tool(name, args):
    if name == "zhixiang_open_workspace":
        health = api("GET", "/api/health")
        return {"url": BASE + "/", "version": health.get("version"), "message": "可在本机客户端的内置浏览器打开知向。网页与本组工具共用资料和判断。"}
    if name == "zhixiang_search":
        q = wait_job(api("POST", "/api/search", {k: args[k] for k in ("question", "period", "focus", "query", "question_id") if k in args}))
        return {"question_id": q["id"], "title": q["title"], "search_report": q.get("search_report"), "search_attempt": q.get("search_attempt")}
    if name == "zhixiang_list_questions":
        return {"questions": [{"id": q["id"], "title": q["title"], "period": q.get("period"),
                               "source_count": len(q.get("source_ids", [])),
                               "judgment_saved_at": (q.get("judgment") or {}).get("saved_at")}
                              for q in api("GET", "/api/bootstrap").get("questions", [])]}
    if name == "zhixiang_get_source":
        sid = args.get("source_id", "")
        if not isinstance(sid, str) or not sid.startswith(("U_", "S")):
            raise ValueError("需要有效的已读来源 ID。")
        source = api("GET", "/api/sources/" + sid)
        text = source.get("text", "")
        return {k: source.get(k) for k in ("id", "title", "url", "publisher", "fetched_at", "published_at", "locator", "scope_limit") } | {"text": text[:12000], "text_truncated_for_mcp": len(text) > 12000, "full_chars": len(text)}
    qid = args.get("question_id", "")
    if not isinstance(qid, str) or not qid.startswith("q_"):
        raise ValueError("需要有效的知向问题 ID。")
    path = "/api/questions/" + qid
    if name == "zhixiang_get_question":
        q = api("GET", path)
        return {k: q.get(k) for k in ("id", "title", "period", "source_ids", "search_report",
                                      "search_import_report", "analysis", "judgment", "history", "comparison")}
    if name == "zhixiang_import_sources":
        return wait_job(api("POST", path + "/search-import", {"candidate_ids": args.get("candidate_ids", []), "analyze": args.get("analyze", False)}))
    if name == "zhixiang_add_source":
        return wait_job(api("POST", path + "/source", {"url": args.get("url", "")}))
    if name == "zhixiang_analyze":
        return wait_job(api("POST", "/api/analyze", {"question_id": qid, "mode": "local"}))
    if name == "zhixiang_save_judgment":
        return api("POST", path + "/judgment", {k: args[k] for k in ("text", "source_ids", "unresolved") if k in args})
    if name == "zhixiang_compare":
        return wait_job(api("POST", path + "/compare", {}))
    raise KeyError(name)


def respond(ident, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": ident}
    message["error" if error is not None else "result"] = error if error is not None else result
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def handle(req):
    global CLIENT_NAME
    if not isinstance(req, dict) or req.get("jsonrpc") != "2.0" or not isinstance(req.get("method"), str):
        return respond(req.get("id") if isinstance(req, dict) else None,
                       error={"code": -32600, "message": "Invalid Request"})
    if "id" not in req:  # JSON-RPC notification: never reply.
        return
    ident, method, params = req["id"], req["method"], req.get("params") or {}
    if not isinstance(params, dict):
        return respond(ident, error={"code": -32602, "message": "Invalid params"})
    if method == "initialize":
        info = params.get("clientInfo") or {}
        CLIENT_NAME = str(info.get("name", ""))[:80] if isinstance(info, dict) else ""
        connection_event("initialized")
        requested = params.get("protocolVersion", "2025-03-26")
        version = requested if requested in ("2024-11-05", "2025-03-26", "2025-06-18", "2026-07-28") else "2025-03-26"
        return respond(ident, {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                               "serverInfo": {"name": "zhixiang", "version": "3.1.1"},
                               "instructions": "知向保存本机的问题、原文和判断。用户要求打开知向时先调用 zhixiang_open_workspace，并在可用的内置浏览器打开返回网址。只有用户明确确认时才保存判断；网页摘要不是已读原文。"})
    if method == "ping":
        return respond(ident, {})
    if method == "tools/list":
        return respond(ident, {"tools": TOOLS})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in {item["name"] for item in TOOLS}:
            return respond(ident, error={"code": -32602, "message": "Unknown tool"})
        if not isinstance(args, dict):
            return respond(ident, error={"code": -32602, "message": "Invalid tool arguments"})
        try:
            value = call_tool(name, args)
            connection_event("tool_called", name)
            return respond(ident, {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "isError": False})
        except (ValueError, KeyError, TypeError) as error:
            return respond(ident, {"content": [{"type": "text", "text": str(error)}], "isError": True})
        except Exception:
            return respond(ident, {"content": [{"type": "text", "text": "知向本次操作失败，请检查网页端状态。"}], "isError": True})
    return respond(ident, error={"code": -32601, "message": "Method not found"})


for raw in sys.stdin:
    try:
        handle(json.loads(raw))
    except json.JSONDecodeError:
        respond(None, error={"code": -32700, "message": "Parse error"})
