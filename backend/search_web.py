"""Live search adapters. A search snippet is never an imported source body."""
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading
from urllib.parse import urlparse, urlunparse
import uuid
import xml.etree.ElementTree as ET

import requests


class SearchError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value, limit=1800):
    parser = PlainText()
    parser.feed(value if isinstance(value, str) else "")
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()[:limit]


def clean_url(value):
    if not isinstance(value, str) or len(value) > 4000:
        return ""
    try:
        parsed = urlparse(value.strip())
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 80, 443):
            return ""
        return urlunparse(parsed._replace(fragment=""))
    except ValueError:
        return ""


def relevance(query, item, allow_uncertain=False):
    """A transparent lexical screen, not a claim of semantic verification."""
    text = " ".join(str(item.get(k, "")) for k in ("title", "snippet", "url")).lower()
    parsed = urlparse(item["url"])
    title = item["title"].lower()
    if parsed.hostname and (parsed.hostname.startswith(("account.", "myaccount.", "login.", "signup.", "outlook.")) or re.search(r"(?:^|/)(?:login|signin|sign-in|signup)(?:/|$)", parsed.path.lower())):
        return "excluded", "登录或账号页面，未作为资料候选"
    if re.search(r"^(?:sign in|create your .* account|my account|登录|注册)", title):
        return "excluded", "登录或账号页面，未作为资料候选"
    stop = {'what', 'how', 'does', 'can', 'the', 'and', 'with', 'for', 'from', 'are', 'was', 'will', 'this', 'that', 'into', 'official', 'original', 'source', 'research', 'debate', 'limitations'}
    latin = [word for word in re.findall(r"[a-z][a-z0-9_-]+", query.lower()) if word not in stop]
    chinese = []
    for run in re.findall(r"[\u4e00-\u9fff]+", query):
        chinese.extend(run[i:i+2] for i in range(len(run)-1))
    chinese = [term for term in chinese if term not in {'如何', '什么', '我们', '可以', '公司', '情况', '官方', '原文', '研究', '争议', '局限', '是否', '哪些', '以及', '影响'}]
    terms = list(dict.fromkeys(latin + chinese))
    matches = [term for term in terms if term in text]
    requested_years = set(re.findall(r"(?<!\d)20\d{2}(?!\d)", query))
    result_years = set(re.findall(r"(?<!\d)20\d{2}(?!\d)", text))
    if requested_years and result_years and not (requested_years & result_years):
        return "partial", "标题与摘要显示的年份和所问年份不同；只能作为对照线索，不能直接回答。"
    if terms and not matches:
        if allow_uncertain:
            return "partial", "标题与摘要未匹配查询词；可能是跨语言结果，请先核对原文。"
        return "excluded", "标题与摘要没有匹配主题关键词"
    financial = bool(re.search(r"annual\s+report|financial\s+(?:results|report)|年报|财报|财务|营收|利润", query, re.I))
    finance_match = bool(re.search(r"annual|financial|(?:quarter|year).{0,20}results|revenue|profit|earnings|10-k|/ar\d{2}(?:/|\b)|年报|财报|财务|营收|利润|业绩", text, re.I))
    enough = not terms or len(matches) >= max(1, min(3, (len(terms) + 1) // 2))
    if financial and not finance_match:
        return "partial", "匹配了部分主题词，但标题与摘要未显示财报或经营指标，可能只是公司介绍。"
    if not enough:
        return "partial", "只匹配部分关键词，尚未确认能回答当前问题。"
    return "matched", "标题或摘要匹配多个查询词；相关性仍需阅读原文确认。"


class SearchSettings:
    """The default DSH provider reuses the configured DeepSeek model credential."""
    def __init__(self, directory, model_settings=None):
        self.path = Path(directory).resolve() / "search.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.model_settings = model_settings

    def config(self):
        with self.lock:
            try:
                value = json.loads(self.path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                value = {}
            return {"provider": value.get("provider", "dsh"), "api_key": value.get("api_key", "")}

    def public(self):
        config = self.config()
        model = self.model_settings.config() if self.model_settings else {}
        dsh_ready = bool(model.get("api_key")) and model.get("provider") == "deepseek"
        configured = dsh_ready if config["provider"] == "dsh" else config["provider"] == "public" or bool(config["api_key"])
        return {"provider": config["provider"], "configured": configured, "dsh_configured": dsh_ready, "tavily_configured": bool(config["api_key"]), "notice": "默认搜索调用固定版本 DSH 的 DeepSeek 原生搜索，使用模型账户额度。搜索结果只是线索，读取原文成功后才能用于分析；公共 Bing RSS 和 Tavily 可手动选择。"}

    def update(self, payload):
        with self.lock:
            config = self.config()
            provider = payload.get("provider", config["provider"])
            if provider not in ("dsh", "public", "tavily"):
                raise SearchError("请选择 DeepSeek 原生搜索、公共搜索或 Tavily。")
            supplied = payload.get("api_key", "")
            if not isinstance(supplied, str) or len(supplied) > 1000:
                raise SearchError("搜索 Key 格式不正确。")
            supplied = supplied.strip()
            if payload.get("clear_api_key") is True:
                config["api_key"] = ""
            elif supplied:
                if any(c.isspace() for c in supplied):
                    raise SearchError("搜索 Key 不能含空白字符。")
                config["api_key"] = supplied
            config["provider"] = provider
            temporary = self.path.with_name(self.path.name + ".tmp")
            temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
            return self.public()


def build_query(question, period="", query="", focus="general"):
    if focus not in ("general", "official", "perspectives"):
        raise SearchError("搜索角度须为常规、官方原文或补充角度。")
    # This transparent query expansion does not classify results as authoritative
    # or certify that viewpoints are balanced.
    result = query.strip() if query else " ".join(part.strip() for part in (question, period) if part.strip())
    chinese = bool(re.search(r"[\u4e00-\u9fff]", result))
    suffix = {"general": "", "official": "官方 原文" if chinese else "official original source", "perspectives": "研究 争议 局限" if chinese else "research debate limitations"}[focus]
    if suffix:
        result += " " + suffix
    return result[:1200]


class SearchClient:
    def __init__(self, settings, model_settings=None):
        self.settings = settings
        self.model_settings = model_settings

    def search(self, query, focus="general"):
        config = self.settings.config()
        if config["provider"] == "dsh":
            items = self.dsh_native(query)
            provider = "dsh-deepseek-official"
            notice = "由固定版本 DSH DeepSeek 原生搜索返回结构化线索；搜索使用 DeepSeek 账户额度，摘要和日期仍需核对原文。"
        elif config["provider"] == "tavily":
            items = self.tavily(query, config["api_key"])
            provider = "tavily"
            notice = "Tavily 返回的摘要仅是搜索线索；日期来自搜索服务，尚未在原文中核对。"
        else:
            items = self.bing_rss(query)
            provider = "bing_rss"
            notice = "Bing RSS 公共搜索结果，范围可能有限或不完全相关；摘要尚未读取和核验。RSS 日期不视为原文发布日期。"
        candidates, seen, filtered_count = [], set(), 0
        for item in items:
            url = clean_url(item.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            candidate = {"id": "candidate_" + uuid.uuid4().hex[:16], "title": plain(item.get("title"), 250) or urlparse(url).hostname, "url": url, "publisher": urlparse(url).hostname, "snippet": plain(item.get("snippet")), "status": "candidate", "provenance": "search_snippet", "date_note": "搜索服务提供的日期未核对原文"}
            quality, reason = relevance(query, candidate, allow_uncertain=provider == "dsh-deepseek-official")
            if quality == "excluded":
                filtered_count += 1
                continue
            candidate.update(relevance=quality, relevance_notice=reason, search_query=query)
            domain = urlparse(url).hostname or ""
            candidate["official_hint"] = bool(re.search(r"(?:^|\.)(?:investor|ir|gov|edu)\.", domain) or domain.endswith((".gov.cn", ".gov", ".edu.cn")) or "hkexnews.hk" in domain)
            if item.get("published_at"):
                candidate["published_at"] = plain(item["published_at"], 100)
            if item.get("search_index_date"):
                candidate["search_index_date"] = plain(item["search_index_date"], 100)
            candidates.append(candidate)
            if len(candidates) >= 10:
                break
        if not candidates:
            notice += " 本次未返回可用候选，可缩短关键词或换一个搜索角度；未使用本地案例填充结果。"
        elif not any(item["relevance"] == "matched" for item in candidates):
            notice += " 本次候选只匹配部分关键词，可能不足以回答问题；建议调整关键词后再搜。"
        if filtered_count:
            notice += f" 已排除{filtered_count}条登录页或未匹配主题词的结果。"
        return {"query": query, "provider": provider, "searched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "candidates": candidates, "notice": notice, "filtered_count": filtered_count, "scope": "实时联网搜索候选；尚未自动读取正文"}

    def merge_reports(self, reports, focus="general"):
        candidates, seen = [], set()
        for report in reports:
            for item in report["candidates"]:
                if item["url"] not in seen:
                    seen.add(item["url"])
                    candidates.append(item)
        if focus == "official":
            candidates.sort(key=lambda c: (not c.get("official_hint", False), c.get("relevance") != "matched"))
        else:
            candidates.sort(key=lambda c: (c.get("relevance") != "matched", not c.get("official_hint", False)))
        return {**reports[0], "candidates": candidates[:10], "actual_queries": [r["query"] for r in reports], "search_runs": [{k: r.get(k) for k in ("query", "provider", "searched_at", "notice", "filtered_count")} for r in reports], "notice": " ".join(dict.fromkeys(r.get("notice", "") for r in reports)), "filtered_count": sum(r.get("filtered_count", 0) for r in reports)}

    def _request(self, method, url, **kwargs):
        session = requests.Session()
        session.trust_env = False
        try:
            # Only the fixed search endpoints below are called. Never send a
            # credential across a redirect and never retry captcha challenges.
            response = session.request(method, url, timeout=(10, 35), allow_redirects=False, stream=True, **kwargs)
            with response:
                if response.status_code in (401, 403, 429, 432, 433):
                    raise SearchError("搜索服务拒绝访问、达到限额或需要验证。没有绕过验证；可稍后重试或在设置中切换搜索服务。")
                if not response.ok or response.is_redirect:
                    raise SearchError("搜索服务这次未提供结果，请稍后重试或切换搜索服务。")
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 2_000_000:
                        raise SearchError("搜索响应过大，本次没有采用结果。")
                    chunks.append(chunk)
                return b"".join(chunks)
        except requests.RequestException:
            raise SearchError("暂时无法连接搜索服务，请检查网络或稍后重试。已有资料与判断仍保留。") from None
        finally:
            session.close()

    def dsh_native(self, query):
        model = self.model_settings.config() if self.model_settings else {}
        if model.get("provider") != "deepseek" or not model.get("api_key"):
            raise SearchError("DeepSeek 原生搜索需要 DeepSeek 试用或个人 API 设置；当前未配置。")
        root = Path(__file__).resolve().parent.parent
        node = root / "runtime" / "node" / "node.exe"
        if not node.is_file():
            node = shutil.which("node")
        bridge = root / "dsh" / "search.mjs"
        if not node or not bridge.is_file():
            raise SearchError("DSH 搜索组件尚未安装完整，请使用完整体验包或按开发说明安装。")
        try:
            run = subprocess.run(
                [str(node), str(bridge)],
                input=json.dumps({"query": query, "apiKey": model["api_key"]}, ensure_ascii=False),
                text=True, encoding="utf-8", capture_output=True, timeout=55,
                cwd=str(root / "dsh"), check=False,
            )
            result = json.loads(run.stdout)
        except subprocess.TimeoutExpired:
            raise SearchError("DSH 搜索超时；本次没有采用不完整结果。") from None
        except (OSError, ValueError, UnicodeError):
            raise SearchError("DSH 搜索组件未返回可读结果；请检查完整包和网络。") from None
        if not result.get("ok"):
            code = result.get("code")
            if code == "authentication":
                raise SearchError("DeepSeek 搜索认证失败，请检查试用额度或在设置中填写自己的 Key。")
            if code == "quota":
                raise SearchError("DeepSeek 搜索额度不足或受到限流，本次没有自动换账户。")
            if code == "timeout":
                raise SearchError("DeepSeek 搜索超时，本次没有采用不完整结果。")
            raise SearchError("DSH DeepSeek 搜索服务本次未提供可用结果；没有采用模型正文或模拟结果。")
        sources = result.get("result", {}).get("sources", [])
        if not isinstance(sources, list):
            raise SearchError("DSH 搜索响应缺少结构化来源。")
        return [{"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("snippet", ""), "published_at": item.get("publishedAt", "")} for item in sources if isinstance(item, dict)]

    def bing_rss(self, query):
        data = self._request("GET", "https://www.bing.com/search", params={"q": query, "format": "rss"}, headers={"User-Agent": "ZhixiangWeb/1.1 PublicSearch"})
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            raise SearchError("公共搜索未返回可读结果，可能需要浏览器验证或暂时限制访问。没有绕过验证；可手动打开搜索或配置 Tavily。") from None
        if root.tag != "rss" or root.find("channel") is None:
            raise SearchError("公共搜索返回了非 RSS 页面，本次没有采用；可稍后重试或切换搜索服务。")
        return [{"title": item.findtext("title", ""), "url": item.findtext("link", ""), "snippet": item.findtext("description", ""), "search_index_date": item.findtext("pubDate", "")} for item in root.findall("./channel/item")]

    def tavily(self, query, api_key):
        if not api_key:
            raise SearchError("尚未配置 Tavily 搜索 Key，可在设置中填写，或切换无需 Key 的公共搜索。")
        data = self._request("POST", "https://api.tavily.com/search", headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}, json={"query": query, "search_depth": "basic", "topic": "general", "max_results": 10, "include_answer": False, "include_raw_content": False, "include_published_date": True, "auto_parameters": False})
        try:
            result = json.loads(data)
            items = result["results"]
            if not isinstance(items, list):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise SearchError("搜索服务返回格式不完整，本次没有采用结果。") from None
        return [{"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("content", ""), "published_at": item.get("published_date", "")} for item in items if isinstance(item, dict)]
