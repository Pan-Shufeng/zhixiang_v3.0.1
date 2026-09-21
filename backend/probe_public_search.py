"""Bounded ordinary public-request diagnosis; does not solve or retry challenges."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET
import requests


def main():
    directory = Path(__file__).resolve().parent / 'checks' / 'search_probe'
    directory.mkdir(exist_ok=True)
    cases = {
        'bing_quoted': 'https://www.bing.com/search?format=rss&q=' + quote('"Microsoft" "2025" "annual report"'),
        'bing_exact_cn': 'https://www.bing.com/search?format=rss&mkt=zh-CN&q=' + quote('"东方甄选" "2025" "年报"'),
        'bing_html': 'https://www.bing.com/search?q=' + quote('Microsoft 2025 annual report revenue'),
        'ddg_html': 'https://html.duckduckgo.com/html/?q=' + quote('Microsoft 2025 annual report revenue'),
        'ddg_lite': 'https://lite.duckduckgo.com/lite/?q=' + quote('东方甄选 2025 年报'),
        'bing_news': 'https://www.bing.com/news/search?format=rss&q=' + quote('Microsoft 2025 annual report revenue'),
    }
    def run(case):
        name, url = case
        session = requests.Session()
        session.trust_env = False
        try:
            response = session.get(url, headers={'User-Agent': 'ZhixiangWeb/1.1 PublicSearch'}, allow_redirects=False, timeout=(10, 25))
            (directory / (name + '.html')).write_bytes(response.content)
            value = {'name': name, 'status': response.status_code, 'type': response.headers.get('content-type'), 'bytes': len(response.content)}
            if 'xml' in response.headers.get('content-type', ''):
                try:
                    root = ET.fromstring(response.content)
                    value['top'] = [(item.findtext('title'), item.findtext('link')) for item in root.findall('./channel/item')[:4]]
                except ET.ParseError:
                    value['xml_error'] = True
            else:
                value['prefix'] = response.text[:1000]
            return value
        except Exception as error:
            return {'name': name, 'error': type(error).__name__}
        finally:
            session.close()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run, cases.items()))
    (directory / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
