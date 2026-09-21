"""Small stdio MCP adapter for the local Zhixiang web service.

The adapter deliberately delegates to the same HTTP API used by the web UI;
it never duplicates search or model logic.
"""
import json, sys, time
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8186"

def api(method, path, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = Request(BASE + path, data=data, method=method, headers={"Content-Type":"application/json"})
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def search(args):
    start = api("POST", "/api/search", {"question": args.get("question",""), "period": args.get("period",""), "focus": args.get("focus","general"), **({"query":args["query"]} if args.get("query") else {})})
    job = start.get("job_id")
    for _ in range(90):
        state = api("GET", "/api/jobs/" + job)
        if state.get("status") == "done":
            return state.get("result", {})
        if state.get("status") == "error":
            return {"error": state.get("error", "搜索失败")}
        time.sleep(1)
    return {"error":"知向搜索超过等待时间，请查看网页端任务状态。"}

TOOLS = [{"name":"zhixiang_search","description":"使用知向联网搜索，返回搜索计划、候选来源和透明的结果边界。候选摘要不是原文。","inputSchema":{"type":"object","properties":{"question":{"type":"string"},"period":{"type":"string"},"focus":{"type":"string","enum":["general","official","perspectives"]},"query":{"type":"string"}},"required":["question"]}}]

def reply(req):
    method, ident, params = req.get("method"), req.get("id"), req.get("params", {})
    if method == "initialize":
        return {"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"zhixiang","version":"1.0.0"}}
    if method == "notifications/initialized": return None
    if method == "tools/list": return {"tools":TOOLS}
    if method == "tools/call" and params.get("name") == "zhixiang_search":
        result = search(params.get("arguments", {}))
        return {"content":[{"type":"text","text":json.dumps(result,ensure_ascii=False,indent=2)}],"isError":"error" in result}
    return {"error":{"code":-32601,"message":"方法或工具不存在"}}

for line in sys.stdin:
    try:
        result = reply(json.loads(line))
        if result is not None:
            print(json.dumps({"jsonrpc":"2.0","id":json.loads(line).get("id"),"result":result},ensure_ascii=False), flush=True)
    except Exception as e:
        print(json.dumps({"jsonrpc":"2.0","id":None,"error":{"code":-32000,"message":str(e)}},ensure_ascii=False), flush=True)
