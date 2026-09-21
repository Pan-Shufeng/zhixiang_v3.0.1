"""Isolated functional tests; models and public download use controlled fixtures.

These validate execution and persistence, not any educational/user effect.
"""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import requests
import server


class FixtureModel:
    def __init__(self):
        self.calls = []
        self.invalid = False

    def complete(self, system, prompt):
        data = json.loads(prompt)
        self.calls.append(data)
        sources = [s["id"] for s in data["sources"]]
        if "saved_judgment" in data:
            return {"summary": "新增材料为原判断补充了经营范围的限制，需要保留原判断并继续核对。", "changes": [{"kind": "qualify", "text": "新增公开说明讨论的范围更窄，不能推及全部业务。", "source_ids": data["new_source_ids"]}], "next_questions": ["进一步核对范围与发布日期。"]}
        return {"summary": "依据所选原文进行的测试分析。", "findings": [{"title": "材料内的发现", "text": "这一结论只涉及选中的材料范围。", "kind": "fact", "source_ids": ["NONEXISTENT" if self.invalid else sources[0]]}], "perspectives": [], "gaps": [{"title": "资料范围", "text": "当前材料不是全部公开资料。", "next_step": "继续核对原文。"}], "terms": []}


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.model = FixtureModel()
        self.app = server.Application(root / "data", root / "config", model=self.model, fallback=False)

    def tearDown(self):
        self.tmp.cleanup()

    def wait(self, result):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = self.app.store.get_job(result["job_id"])
            if job["status"] in ("done", "error"):
                return job
            time.sleep(0.02)
        self.fail("Job did not finish")

    def prepared(self):
        job = self.wait(self.app.analyze({"mode": "prepared", "example_id": "eastbuy"}))
        self.assertEqual(job["status"], "done")
        return job["result"]

    def test_clean_start_public_originals_and_prepared_no_model(self):
        boot = self.app.bootstrap()
        self.assertEqual(len(boot["sources"]), 12)
        self.assertEqual(boot["questions"], [])
        self.assertEqual(self.model.calls, [])
        q = self.prepared()
        self.assertEqual(q["analysis"]["mode"], "prepared")
        self.assertEqual(self.model.calls, [])
        self.assertIn("135.4", q["analysis"]["findings"][1]["text"])
        self.assertTrue(self.app.store.source_file("S006").is_file())
        self.assertTrue(self.app.store.get_source("S006")["text"])

    def test_unknown_question_retained_without_wrong_case_or_model(self):
        job = self.wait(self.app.analyze({"question": "我应该在校园开咖啡店吗？"}))
        self.assertEqual(job["status"], "error")
        self.assertIn("没有找到", job["error"])
        q = self.app.store.get_question(job["question_id"])
        self.assertEqual(q["source_ids"], [])
        self.assertIsNone(q["analysis"])
        self.assertEqual(self.model.calls, [])
        new_job = self.wait(self.app.add_source(q["id"], {"title": "校园咖啡调查原文", "text": "这是一份公开课堂练习提供的校园咖啡材料。午间学生需要便捷饮品，但这里只记录五次观察，无法推断长期需求或全校学生的购买意愿。"}))
        self.assertEqual(new_job["status"], "done")
        analyzed = self.wait(self.app.analyze({"question_id": q["id"]}))
        self.assertEqual(analyzed["status"], "done")
        self.assertEqual(len(self.model.calls), 1)
        self.assertTrue(all(s["id"].startswith("U_") for s in self.model.calls[0]["sources"]))

    def test_topics_do_not_mix_finance_and_recommendation(self):
        job = self.wait(self.app.analyze({"question": "东方甄选的经营表现如何？"}))
        self.assertEqual(job["status"], "done")
        self.assertTrue(set(job["result"]["source_ids"]).issubset({"S006", "S007", "S008", "S009"}))
        second = self.wait(self.app.analyze({"question": "TikTok推荐算法如何影响信息茧房？"}))
        self.assertEqual(second["status"], "done")
        self.assertNotIn("S006", second["result"]["source_ids"])

    def test_explicit_publication_cutoff(self):
        results = server.retrieve("东方甄选的经营规模如何？", self.app.store.all_sources(), "截至2024-08-24")
        self.assertNotIn("S006", [s["id"] for s in results])
        self.assertTrue(results)

    def test_financial_context_keeps_saved_text_and_reveals_truncation(self):
        selected = [self.app.store.get_source(sid) for sid in ("S006", "S007", "S008", "S009")]
        context = server.source_context(selected, "东方甄选FY2024至FY2025经营表现")
        self.assertTrue(all(not source["text_truncated"] for source in context))
        self.assertEqual(context[2]["original_text"], selected[2]["text"])
        self.assertLessEqual(sum(source["context_chars"] for source in context), 60000)
        papers = [self.app.store.get_source(sid) for sid in ("S003", "S004", "S005", "S010", "S011")]
        excerpts = server.source_context(papers, "推荐研究的研究设计与限制")
        self.assertTrue(all(source["text_truncated"] for source in excerpts))
        self.assertTrue(all(source["context_chars"] <= 30000 for source in excerpts))
        self.assertLessEqual(sum(source["context_chars"] for source in excerpts), 60000)

    def test_save_add_compare_never_overwrites_judgment_and_reopens(self):
        q = self.prepared()
        saved = self.app.save_judgment(q["id"], {"text": "当前判断：规模收缩，但不足以断言商业模式失效。", "unresolved": ["继续核对业务范围"]})
        previous = saved["judgment"].copy()
        text = "新增公开材料摘录：此处仅讨论指定渠道和特定期间的经营表现，不代表全部业务；其定义与其他渠道不可直接合并，后续仍需核对完整原文。"
        added = self.wait(self.app.add_source(q["id"], {"text": text, "title": "新增范围说明"}))["result"]
        self.assertEqual(len(added["pending_source_ids"]), 1)
        new_id = added["pending_source_ids"][0]
        self.assertNotIn(new_id, added["judgment"]["source_ids"])
        compared = self.wait(self.app.compare(q["id"]))
        self.assertEqual(compared["status"], "done")
        self.assertEqual(compared["result"]["judgment"], previous)
        self.assertEqual(compared["result"]["comparison"]["changes"][0]["kind"], "qualify")
        self.assertIn(new_id, compared["result"]["pending_source_ids"])
        self.app.save_judgment(q["id"], {"text": "更新后的判断，保留经营范围的限制。"})
        reopened = server.Store(self.app.store.directory).get_question(q["id"])
        self.assertEqual(len(reopened["history"]), 2)
        self.assertEqual(reopened["history"][0]["text"], previous["text"])
        self.assertEqual(reopened["pending_source_ids"], [])
        self.assertIn(new_id, reopened["judgment"]["source_ids"])
        self.assertIsNone(reopened["comparison"])
        self.assertEqual(len(reopened["comparison_history"]), 1)

    def test_duplicates_do_not_create_fake_new_material(self):
        q = self.prepared()
        text = "这是一段用于检测重复资料的公开测试文本。相同内容反复提交，不应被当成新的独立证据，也不应导致资料数量不断增加。"
        a = self.wait(self.app.add_source(q["id"], {"text": text}))["result"]
        b = self.wait(self.app.add_source(q["id"], {"text": text}))["result"]
        self.assertEqual(a["source_ids"], b["source_ids"])
        self.app.save_judgment(q["id"], {"text": "判断已经涵盖所有当前材料。"})
        self.wait(self.app.add_source(q["id"], {"text": text}))
        with self.assertRaisesRegex(server.UserError, "没有新增材料"):
            self.app.compare(q["id"])

    def test_refresh_preserves_immutable_original_and_versions(self):
        q = self.prepared()
        self.app.save_judgment(q["id"], {"text": "原判断基于已披露的历史经营数据。"})
        original = self.app.store.get_source("S006")["text"]
        self.app.fetch = lambda url: {"data": ("new:" + url).encode(), "text": "测试公开网站更新后的真实文本。" * 20, "suffix": ".txt", "title": "更新后的来源", "kind": "公开文本", "locator": "测试", "url": url}
        result = self.wait(self.app.analyze({"question_id": q["id"], "mode": "refresh"}))
        self.assertEqual(result["status"], "done")
        self.assertEqual(self.app.store.get_source("S006")["text"], original)
        self.assertEqual(len(result["result"]["pending_source_ids"]), 4)
        self.assertNotIn(result["result"]["pending_source_ids"][0], result["result"]["judgment"]["source_ids"])

    def test_invalid_citations_rejected_without_overwriting_guide(self):
        q = self.prepared()
        old = q["analysis"]
        self.model.invalid = True
        result = self.wait(self.app.analyze({"question_id": q["id"]}))
        self.assertEqual(result["status"], "error")
        self.assertIn("引用", result["error"])
        self.assertEqual(self.app.store.get_question(q["id"])["analysis"], old)

    def test_failed_refresh_preserves_prior_result_without_model(self):
        q = self.prepared()
        def unavailable(url):
            raise server.UserError("测试网站本次不可访问。")
        self.app.fetch = unavailable
        result = self.wait(self.app.analyze({"question_id": q["id"], "mode": "refresh"}))
        self.assertEqual(result["status"], "error")
        current = self.app.store.get_question(q["id"])
        self.assertEqual(current["analysis"], q["analysis"])
        self.assertTrue(all(item["status"] == "failed" for item in current["refresh_report"]["items"]))
        self.assertEqual(self.model.calls, [])

    def test_rejected_concurrent_analyze_does_not_mutate_question(self):
        q = self.prepared()
        entered, release = threading.Event(), threading.Event()
        real_fixture = self.model.complete
        def blocked(system, prompt):
            entered.set()
            release.wait(5)
            return real_fixture(system, prompt)
        self.model.complete = blocked
        task = self.app.analyze({"question_id": q["id"], "source_ids": ["S008"]})
        self.assertTrue(entered.wait(4))
        try:
            with self.assertRaises(server.UserError) as caught:
                self.app.analyze({"question_id": q["id"], "question": "不得写入的新问题", "source_ids": ["S001"]})
            self.assertEqual(caught.exception.status, 409)
            current = self.app.store.get_question(q["id"])
            self.assertEqual(current["title"], q["title"])
            self.assertEqual(current["source_ids"], ["S008"])
        finally:
            release.set()
        self.assertEqual(self.wait(task)["status"], "done")

    def test_same_second_judgment_save_invalidates_inflight_comparison(self):
        q = self.prepared()
        entered, release = threading.Event(), threading.Event()
        with patch.object(server, "now", lambda: "2026-09-14T12:00:00+00:00"):
            self.app.save_judgment(q["id"], {"text": "这一句判断在同一秒确认两次，仍应是不同版本。"})
            self.wait(self.app.add_source(q["id"], {"text": "这是一段用于核对判断版本处理的补充原文。新加入的内容尚需核对，不能在用户再次确认后沿用上一版比较。"}))
            real_fixture = self.model.complete
            def blocked(system, prompt):
                entered.set()
                release.wait(5)
                return real_fixture(system, prompt)
            self.model.complete = blocked
            task = self.app.compare(q["id"])
            self.assertTrue(entered.wait(4))
            self.app.save_judgment(q["id"], {"text": "这一句判断在同一秒确认两次，仍应是不同版本。"})
            release.set()
            result = self.wait(task)
            self.assertEqual(result["status"], "error")
            self.assertIn("更新判断", result["error"])

    def test_key_stays_backend_and_trial_switches(self):
        key = "test-secret-never-in-json"
        server.atomic_json(self.app.settings.directory / "trial.json", {"api_key": key, "model": "test-model", "base_url": "https://api.deepseek.com", "provider": "deepseek"})
        self.assertTrue(self.app.settings.public()["configured"])
        self.assertNotIn(key, json.dumps(self.app.bootstrap()))
        self.app.settings.update({"api_key": "different-test-secret", "model": "my-model"})
        self.assertFalse(self.app.settings.public()["trial"])
        self.app.settings.update({"use_trial": True})
        self.assertTrue(self.app.settings.public()["trial"])
        self.assertNotIn(key, json.dumps(self.app.settings.public()))

    def test_budget_failure_stops_future_calls(self):
        server.atomic_json(self.app.settings.directory / "trial.json", {"api_key": "fake-secret", "model": "test", "base_url": "https://api.deepseek.com"})
        class Response:
            ok = True
            status_code = 200
            def json(self):
                return {"is_available": False}
        class Session:
            count = 0
            def get(self, *args, **kwargs):
                Session.count += 1
                return Response()
            def post(self, *args, **kwargs):
                raise AssertionError("Should never call completions without balance")
            def close(self):
                pass
        model = server.Model(self.app.settings, self.app.store.directory)
        with patch.object(server.requests, "Session", Session):
            for _ in range(2):
                with self.assertRaises(server.UserError) as caught:
                    model.complete("s", "p")
                self.assertEqual(caught.exception.status, 402)
        self.assertEqual(Session.count, 1)

    def test_public_url_and_source_file_reject_local_access(self):
        for url in ("file:///C:/windows/win.ini", "http://127.0.0.1:5055", "http://localhost/"):
            with self.assertRaises(server.UserError):
                server.public_url(url)
        with self.assertRaises(server.UserError):
            self.app.store.source_file("../../config/local.json")

    def test_http_roundtrip_original_export_and_local_origin(self):
        srv = server.Server(("127.0.0.1", 0), self.app, Path(self.tmp.name))
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:" + str(srv.server_port)
        client = requests.Session()
        client.trust_env = False
        try:
            health = client.get(base + "/api/health").json()
            self.assertEqual(health["app_id"], "zhixiang-web")
            qid = self.prepared()["id"]
            save = client.post(base + f"/api/questions/{qid}/judgment", json={"text": "通过HTTP保存并重新打开的判断。"})
            self.assertEqual(save.status_code, 200)
            reopened = client.get(base + "/api/questions/" + qid).json()
            self.assertEqual(reopened["judgment"]["text"], "通过HTTP保存并重新打开的判断。")
            self.assertTrue(client.get(base + "/files/S006").content.startswith(b"%PDF"))
            export = client.get(base + "/api/export/" + qid)
            self.assertIn("通过HTTP", export.text)
            blocked = client.post(base + "/api/settings", json={"use_trial": True}, headers={"Origin": "https://untrusted.example"})
            self.assertEqual(blocked.status_code, 403)
            self.assertNotIn("api_key", client.get(base + "/api/settings").text)
        finally:
            client.close()
            srv.shutdown()
            srv.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
