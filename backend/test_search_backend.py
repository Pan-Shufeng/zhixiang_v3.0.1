"""Offline contract and state tests. Network fixtures are labeled; no paid API calls."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import requests
import server
from search_web import SearchClient, SearchError, SearchSettings, relevance
from test_backend import FixtureModel


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.model = FixtureModel()
        self.app = server.Application(self.root / 'data', self.root / 'config', model=self.model, fallback=False)
        self.report = {'query': 'fixture only', 'provider': 'fixture_only', 'searched_at': server.now(), 'candidates': [
            {'id': 'c1', 'title': 'Fixture first', 'url': 'https://example.com/one', 'snippet': 'SEARCH SNIPPET MUST NOT BECOME SOURCE', 'status': 'candidate'},
            {'id': 'c2', 'title': 'Fixture blocked', 'url': 'https://example.com/two', 'snippet': 'BLOCKED SEARCH SNIPPET', 'status': 'candidate'}]}
        self.app.search_client.search = lambda query: json.loads(json.dumps({**self.report, 'query': query}))

    def tearDown(self):
        self.tmp.cleanup()

    def wait(self, queued):
        for _ in range(500):
            job = self.app.store.get_job(queued['job_id'])
            if job['status'] in ('done', 'error'):
                return job
            time.sleep(.02)
        self.fail('job timeout')

    def question(self):
        return self.wait(self.app.search({'question': '校园咖啡店的经营需要关注什么？'}))['result']

    def fetch(self, url):
        if url.endswith('/two'):
            raise server.UserError('网站拒绝正文访问；fixture failure')
        body = 'Fixture original text, independently fetched and not the search snippet. ' * 3
        return {'data': body.encode(), 'text': body, 'title': 'Original title', 'url': url, 'kind': '公开网页', 'locator': 'fixture original', 'suffix': '.html'}

    def test_new_question_search_has_no_sources_or_model(self):
        q = self.question()
        self.assertEqual(q['source_ids'], [])
        self.assertIsNone(q['analysis'])
        self.assertEqual(self.model.calls, [])
        self.assertEqual(len(q['search_report']['candidates']), 2)

    def test_empty_results_never_substitute_local_case(self):
        self.app.search_client.search = lambda query: {'query': query, 'provider': 'fixture_empty', 'searched_at': server.now(), 'candidates': []}
        q = self.wait(self.app.search({'question': '东方甄选并不存在的独有问法'}))['result']
        self.assertEqual(q['search_report']['candidates'], [])
        self.assertEqual(q['source_ids'], [])
        self.assertEqual(self.model.calls, [])

    def test_partial_import_and_analysis_only_uses_fetched_original(self):
        q = self.question()
        self.app.fetch = self.fetch
        job = self.wait(self.app.search_import(q['id'], {'candidate_ids': ['c1', 'c2'], 'analyze': True}))
        self.assertEqual(job['status'], 'done')
        q = job['result']
        self.assertEqual([i['status'] for i in q['search_import_report']['items']], ['added', 'failed'])
        self.assertEqual(q['search_import_report']['analysis_status'], 'done')
        self.assertEqual(len(q['source_ids']), 1)
        self.assertEqual(q['source_ids'], q['pending_source_ids'])
        self.assertNotIn('SEARCH SNIPPET', json.dumps(self.model.calls))
        self.assertIn('independently fetched', json.dumps(self.model.calls))
        self.assertEqual(q['search_report']['candidates'][1]['import_status'], 'failed')

    def test_duplicates_and_saved_judgment_preserved(self):
        q = self.question()
        self.app.fetch = self.fetch
        first = self.wait(self.app.search_import(q['id'], {'candidate_ids': ['c1']}))['result']
        judgment = self.app.save_judgment(q['id'], {'text': 'This is the user judgment.'})['judgment']
        after = self.wait(self.app.search_import(q['id'], {'candidate_ids': ['c1'], 'analyze': True}))['result']
        self.assertEqual(after['source_ids'], first['source_ids'])
        self.assertEqual(after['judgment'], judgment)
        self.assertEqual(after['pending_source_ids'], [])
        self.assertEqual(after['search_import_report']['analysis_status'], 'skipped_saved_judgment')
        self.assertEqual(after['search_import_report']['items'][0]['status'], 'duplicate')
        self.assertEqual(self.model.calls, [])

    def test_all_failed_originals_do_not_call_model(self):
        q = self.question()
        self.app.fetch = self.fetch
        after = self.wait(self.app.search_import(q['id'], {'candidate_ids': ['c2'], 'analyze': True}))['result']
        self.assertEqual(after['source_ids'], [])
        self.assertEqual(after['search_import_report']['analysis_status'], 'no_sources')
        self.assertEqual(self.model.calls, [])

    def test_model_failure_preserves_original_and_import_results(self):
        q = self.question()
        self.app.fetch = self.fetch
        self.model.complete = lambda *_: (_ for _ in ()).throw(server.UserError('Fixture missing model key'))
        after = self.wait(self.app.search_import(q['id'], {'candidate_ids': ['c1'], 'analyze': True}))['result']
        self.assertTrue(after['source_ids'])
        self.assertEqual(after['search_import_report']['analysis_status'], 'failed')
        self.assertIsNone(after['analysis'])
        self.assertTrue(self.app.store.source_file(after['source_ids'][0]).exists())

    def test_selection_must_belong_to_current_report(self):
        q = self.question()
        for ids in ([], ['unknown'], ['c1', 'other-question-candidate'], ['c1'] * 9, 'c1'):
            with self.assertRaises(server.UserError):
                self.app.search_import(q['id'], {'candidate_ids': ids})
        self.assertEqual(self.app.store.get_question(q['id'])['source_ids'], [])

    def test_failed_search_preserves_last_report_and_judgment(self):
        q = self.question()
        saved = self.app.save_judgment(q['id'], {'text': 'Saved before failed search'})
        self.app.search_client.search = lambda *_: (_ for _ in ()).throw(SearchError('Fixture search unavailable'))
        failed = self.wait(self.app.search({'question_id': q['id'], 'query': 'new query'}))
        self.assertEqual(failed['status'], 'error')
        current = self.app.store.get_question(q['id'])
        self.assertEqual(current['search_report'], saved['search_report'])
        self.assertEqual(current['judgment'], saved['judgment'])
        self.assertEqual(current['search_attempt']['status'], 'error')

    def test_concurrent_search_cannot_mutate_active_question(self):
        q = self.question()
        started, release = threading.Event(), threading.Event()
        def blocked(query):
            started.set()
            release.wait(3)
            return {**self.report, 'query': query}
        self.app.search_client.search = blocked
        queued = self.app.search({'question_id': q['id'], 'query': 'first query'})
        self.assertTrue(started.wait(2))
        try:
            with self.assertRaises(server.UserError) as error:
                self.app.search({'question_id': q['id'], 'question': 'overwrite attempt', 'query': 'second query'})
            self.assertEqual(error.exception.status, 409)
            with self.assertRaises(server.UserError):
                self.app.search_import(q['id'], {'candidate_ids': ['c1']})
        finally:
            release.set()
        result = self.wait(queued)['result']
        self.assertEqual(result['title'], q['title'])
        self.assertEqual(result['search_report']['query'], 'first query')

    def test_restart_persists_search_import_and_marks_interruption(self):
        q = self.question()
        self.app.fetch = self.fetch
        q = self.wait(self.app.search_import(q['id'], {'candidate_ids': ['c1', 'c2']}))['result']
        self.app.store.save_job({'id': 'interrupted-fixture', 'question_id': q['id'], 'status': 'running'})
        reopened = server.Application(self.root / 'data', self.root / 'config', model=self.model, fallback=False)
        self.assertEqual(reopened.store.get_question(q['id']), q)
        self.assertEqual(reopened.store.get_job('interrupted-fixture')['status'], 'error')
        self.assertTrue(reopened.store.get_source(q['source_ids'][0])['text'])

    def test_settings_secret_never_returned_and_clear_is_explicit(self):
        settings = self.app.search_settings
        self.assertTrue(settings.public()['configured'])
        secret = 'fixture-tavily-secret-not-real'
        public = settings.update({'provider': 'tavily', 'api_key': secret})
        self.assertNotIn(secret, json.dumps(public))
        self.assertNotIn('api_key', public)
        settings.update({'api_key': ''})
        self.assertEqual(settings.config()['api_key'], secret)
        self.assertNotIn(secret, json.dumps(self.app.bootstrap()))
        settings.update({'clear_api_key': True})
        self.assertFalse(settings.public()['configured'])
        self.assertEqual(settings.config()['api_key'], '')

    def test_rss_date_stays_index_date_and_tavily_disables_generated_answer(self):
        client = SearchClient(self.app.search_settings)
        xml = b'<rss><channel><item><title>Fixture</title><link>https://example.com/doc</link><description>Snippet only</description><pubDate>Mon, 14 Sep 2026 00:00:00 GMT</pubDate></item></channel></rss>'
        with patch.object(client, '_request', return_value=xml):
            report = client.search('fixture query')
        self.assertNotIn('published_at', report['candidates'][0])
        self.assertIn('search_index_date', report['candidates'][0])
        self.app.search_settings.update({'provider': 'tavily', 'api_key': 'fixture-key'})
        with patch.object(client, '_request', return_value=b'{"results":[]}') as request:
            client.search('fixture query')
            payload = request.call_args.kwargs['json']
            self.assertFalse(payload['include_answer'])
            self.assertFalse(payload['include_raw_content'])
            self.assertFalse(payload['auto_parameters'])

    def test_search_captcha_response_is_error_not_empty_success(self):
        client = SearchClient(self.app.search_settings)
        with patch.object(client, '_request', return_value=b'<html><title>Verify you are human</title></html>'):
            with self.assertRaises(SearchError):
                client.search('fixture captcha')

    def test_blocked_http200_page_is_not_imported_as_body(self):
        from types import SimpleNamespace
        body = b'<html><title>Your request has been blocked. This could be due to several reasons.</title><p>' + b'Navigation and access restrictions. ' * 10 + b'</p></html>'
        response = SimpleNamespace(status_code=200, ok=True, headers={'Content-Type': 'text/html'}, encoding='utf-8', iter_content=lambda size: [body], close=lambda: None)
        with patch('server.public_url'), patch('server.requests.Session') as session:
            session.return_value.get.return_value = response
            with self.assertRaises(server.UserError) as error:
                server.fetch_source('https://example.com/blocked')
        self.assertIn('验证页面', str(error.exception))

    def test_quality_screen_filters_login_and_flags_nonfinancial_homepage(self):
        self.assertEqual(relevance('Microsoft annual report', {'title': 'Sign in', 'url': 'https://account.microsoft.com/', 'snippet': 'Microsoft account'})[0], 'excluded')
        self.assertEqual(relevance('东方甄选 年报', {'title': 'Unrelated shoes', 'url': 'https://example.com', 'snippet': 'Fashion only'})[0], 'excluded')
        self.assertEqual(relevance('瑞幸咖啡 2025 财报', {'title': '瑞幸咖啡官网', 'url': 'https://example.com', 'snippet': '品牌介绍和门店加盟'})[0], 'partial')
        self.assertEqual(relevance('Microsoft 2025 annual report', {'title': 'Microsoft 2025 Annual Report', 'url': 'https://example.com', 'snippet': 'Annual revenue and profit'})[0], 'matched')

    def test_planner_only_makes_two_real_searches_and_never_creates_sources(self):
        self.app.settings.public = lambda: {'configured': True}
        calls = []
        self.model.complete = lambda system, prompt: calls.append(json.loads(prompt)) or {'queries': ['first short query', 'second short query', 'third ignored']}
        queries = []
        self.app.search_client.search = lambda query: queries.append(query) or {**self.report, 'query': query}
        q = self.question()
        self.assertEqual(len(calls), 1)
        self.assertEqual(queries, ['first short query', 'second short query'])
        self.assertEqual(q['search_report']['query_plan']['mode'], 'model')
        self.assertEqual(len(q['search_report']['candidates']), 2)
        self.assertEqual(q['source_ids'], [])

    def test_explicit_query_skips_model_and_failed_planner_falls_back(self):
        self.app.settings.public = lambda: {'configured': True}
        calls = []
        def fail(*args):
            calls.append(1)
            raise server.UserError('Fixture unavailable model')
        self.model.complete = fail
        direct = self.wait(self.app.search({'question': 'Explicit search fixture', 'query': 'chosen exact query'}))['result']
        self.assertEqual(calls, [])
        self.assertEqual(direct['search_report']['query_plan']['mode'], 'direct')
        fallback = self.question()
        self.assertEqual(calls, [1])
        self.assertEqual(fallback['search_report']['query_plan']['mode'], 'fallback')
        self.assertEqual(fallback['source_ids'], [])

    def test_identical_original_deduplication_across_parallel_questions(self):
        q1, q2 = self.question(), self.question()
        barrier = threading.Barrier(2)
        def fetch(url):
            barrier.wait(3)
            return self.fetch(url)
        self.app.fetch = fetch
        j1 = self.app.search_import(q1['id'], {'candidate_ids': ['c1']})
        j2 = self.app.search_import(q2['id'], {'candidate_ids': ['c1']})
        a, b = self.wait(j1)['result'], self.wait(j2)['result']
        self.assertEqual(a['source_ids'], b['source_ids'])
        self.assertEqual(len([s for s in self.app.store.all_sources() if s['origin'] == 'web']), 1)

    def test_model_wall_timeout_keeps_two_outstanding_workers_and_drops_late_results(self):
        model = server.Model(self.app.settings, self.root)
        release = threading.Event()
        calls = []
        def stuck(*args, **kwargs):
            calls.append(1)
            release.wait(2)
            return {'late': True}
        model._complete_request = stuck
        started = time.monotonic()
        try:
            for _ in range(2):
                with self.assertRaises(server.UserError) as error:
                    model.complete('fixture', 'fixture', request_timeout=.05)
                self.assertIn('时限', str(error.exception))
            with self.assertRaises(server.UserError) as error:
                model.complete('fixture', 'fixture', request_timeout=.05)
            self.assertIn('没有发起新请求', str(error.exception))
            self.assertEqual(len(calls), 2)
            self.assertLess(time.monotonic() - started, .6)
        finally:
            release.set()

    def test_analysis_timeout_does_not_later_overwrite_saved_state(self):
        q = self.question()
        self.app.fetch = self.fetch
        model = server.Model(self.app.settings, self.root)
        release = threading.Event()
        def late(*args, **kwargs):
            release.wait(2)
            return {'summary': 'Late answer must never be saved', 'findings': [], 'perspectives': [], 'gaps': [], 'terms': []}
        model._complete_request = late
        bounded = model.complete
        model.complete = lambda system, prompt: bounded(system, prompt, request_timeout=.05)
        self.app.model = model
        try:
            result = self.wait(self.app.search_import(q['id'], {'candidate_ids': ['c1'], 'analyze': True}))['result']
            self.assertEqual(result['search_import_report']['analysis_status'], 'failed')
            self.assertTrue(result['source_ids'])
            self.assertIsNone(result['analysis'])
        finally:
            release.set()
        time.sleep(.05)
        self.assertIsNone(self.app.store.get_question(q['id'])['analysis'])

    def test_model_stream_response_and_planning_limits_are_bounded(self):
        model = server.Model(self.app.settings, self.root)
        self.app.settings.config = lambda: {'api_key': 'fixture-only', 'base_url': 'https://example.com', 'model': 'fixture'}
        class Response:
            status_code, ok = 200, True
            def iter_content(self, size):
                yield b' \n'
                yield json.dumps({'choices': [{'message': {'content': '{"queries":["fixture query"]}'}}]}).encode()
            def close(self):
                pass
        with patch('server.requests.Session') as session:
            session.return_value.post.return_value = Response()
            result = model.complete('fixture', 'fixture', max_tokens=320, request_timeout=1)
            self.assertEqual(result['queries'], ['fixture query'])
            self.assertTrue(session.return_value.post.call_args.kwargs['stream'])
            self.assertEqual(session.return_value.post.call_args.kwargs['json']['max_tokens'], 320)

    def test_http_search_routes_and_settings_no_secret(self):
        httpd = server.Server(('127.0.0.1', 0), self.app, self.root)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        client = requests.Session()
        client.trust_env = False
        base = 'http://127.0.0.1:' + str(httpd.server_port)
        try:
            result = client.post(base + '/api/search', json={'question': 'HTTP fixture outside seed topics'})
            self.assertEqual(result.status_code, 202)
            q = self.wait(result.json())['result']
            self.app.fetch = self.fetch
            result = client.post(base + '/api/questions/' + q['id'] + '/search-import', json={'candidate_ids': ['c1', 'c2']})
            self.assertEqual(result.status_code, 202)
            self.wait(result.json())
            public = client.post(base + '/api/search/settings', json={'provider': 'tavily', 'api_key': 'fixture-key-hidden'}).json()
            self.assertNotIn('fixture-key-hidden', json.dumps(public))
            self.assertNotIn('api_key', client.get(base + '/api/search/settings').json())
        finally:
            client.close()
            httpd.shutdown()
            httpd.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
