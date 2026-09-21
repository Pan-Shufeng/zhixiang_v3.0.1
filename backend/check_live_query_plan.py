"""One explicitly authorized live model planning call; two public searches at most."""
import json
from pathlib import Path
import tempfile
import time
import server


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        settings = server.Settings(server.ROOT / 'config')
        if not settings.public()['configured']:
            raise RuntimeError('Model is not configured; no call made.')
        model = server.Model(settings, root)
        calls = []
        original = model.complete
        def one_call(system, prompt, **options):
            if calls:
                raise RuntimeError('One-call verification cap reached')
            calls.append(server.now())
            return original(system, prompt, **options)
        model.complete = one_call
        app = server.Application(root / 'data', root / 'search_config', model=model, fallback=False)
        app.settings = settings
        queued = app.search({'question': '东方甄选 FY2025 的营收和利润相比上一财年如何变化？', 'period': 'FY2025'})
        deadline = time.monotonic() + 220
        while time.monotonic() < deadline:
            job = app.store.get_job(queued['job_id'])
            if job['status'] in ('done', 'error'):
                break
            time.sleep(.25)
        q = app.store.get_question(queued['question_id'])
        result = {'checked_at': server.now(), 'verification_status': 'completed' if job['status'] in ('done', 'error') else 'incomplete_within_220_seconds', 'model_calls': len(calls), 'model_role': 'query planning only', 'paid_search_calls': 0, 'job_status': job['status'], 'error': job.get('error'), 'source_ids': q['source_ids'], 'search_report': q.get('search_report'), 'search_attempt': q.get('search_attempt')}
        path = Path(__file__).resolve().parent / 'checks' / 'web_query_plan_live.json'
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
