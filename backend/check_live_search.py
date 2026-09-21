"""Opt-in public search and page verification. Never invokes a model or paid search."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import server
from search_web import SearchClient, SearchSettings


def main():
    destination = Path(__file__).resolve().parent / 'checks' / 'web_search_final.json'
    with tempfile.TemporaryDirectory() as directory:
        client = SearchClient(SearchSettings(directory))
        queries = ['东方甄选 2025 年报', '瑞幸咖啡 2025 财报', '"Microsoft" "2025" "annual report"', 'site:python.org Python documentation']
        def search(query):
            try:
                return {'query': query, 'status': 'done', 'report': client.search(query)}
            except Exception as error:
                return {'query': query, 'status': 'error', 'message': str(error)}
        with ThreadPoolExecutor(max_workers=2) as pool:
            reports = list(pool.map(search, queries))
        verification = {'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'real_public_http': True, 'model_calls': 0, 'paid_search_calls': 0, 'searches': reports, 'reads': []}
        for result in reports:
            matched = [c for c in result.get('report', {}).get('candidates', []) if c.get('relevance') == 'matched']
            if not matched:
                verification['reads'].append({'query': result['query'], 'status': 'skipped', 'message': 'No candidate passed the lexical topic screen; no unrelated body substituted.'})
            for candidate in matched[:1]:
                # Read the first keyword-matching candidate, recording a failure
                # honestly rather than substituting search snippets.
                try:
                    source = server.fetch_source(candidate['url'])
                    verification['reads'].append({'query': result['query'], 'url': candidate['url'], 'final_url': source['url'], 'status': 'read', 'title': source['title'], 'characters': len(source['text']), 'kind': source['kind'], 'excerpt_for_manual_relevance_check': source['text'][:700]})
                except server.UserError as error:
                    verification['reads'].append({'query': result['query'], 'url': candidate['url'], 'status': 'failed', 'message': str(error)})
                break
        destination.parent.mkdir(exist_ok=True)
        destination.write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'report_file': str(destination), 'searches': [{'query': r['query'], 'status': r['status'], 'top_results': [{'title': c['title'], 'url': c['url']} for c in r.get('report', {}).get('candidates', [])[:4]]} for r in reports], 'reads': verification['reads']}, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
