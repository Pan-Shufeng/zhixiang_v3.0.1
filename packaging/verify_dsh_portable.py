"""Smoke-check the actual DSH ZIP in a new Chinese/space directory.

This checks real network search and source reading, not answer correctness.
Semantic evaluation and DSH-agent tool calls are recorded separately.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--zip', type=Path, default=ROOT / '交付' / '知向_DSH集成版_Windows体验包.zip')
    parser.add_argument('--port', type=int, default=8191)
    args = parser.parse_args()
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', args.port)) == 0:
            raise RuntimeError('验收端口已占用；未触碰该服务。')
    folder = ROOT / '验收' / ('最终DSH解压 中文 空格 ' + time.strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(args.zip) as archive:
        for member in archive.namelist():
            if not (folder / member).resolve().is_relative_to(folder.resolve()):
                raise RuntimeError('ZIP 路径越过验收目录')
        archive.extractall(folder)
    app = folder / '知向_DSH集成版'
    assert (app / 'runtime' / 'python.exe').is_file()
    assert (app / 'runtime' / 'node' / 'node.exe').is_file()
    assert (app / 'dsh' / 'node_modules' / '@deepseek-ai' / 'dsh' / 'lib' / 'bin.js').is_file()
    assert not any((app / x).exists() for x in ('data/knowledge.sqlite3', 'config/local.json', 'data/dsh-home'))
    trial = json.loads((app / 'config' / 'trial.json').read_text(encoding='utf-8'))
    key = trial['api_key'].encode('utf-8')
    manifest = json.loads((app / 'packaging' / 'file_manifest.json').read_text(encoding='utf-8'))
    for relative, digest in manifest.items():
        item = app / relative
        assert hashlib.sha256(item.read_bytes()).hexdigest() == digest, relative
        assert key not in item.read_bytes(), f'试用 Key 出现在 {relative}'
    report = {'zip': str(args.zip), 'zip_sha256': hashlib.sha256(args.zip.read_bytes()).hexdigest(),
              'extracted': str(app), 'clean_initial_data': True, 'manifest_verified': len(manifest),
              'trial_key_only_in_config': True, 'all_passed': False}
    system_buffer = ctypes.create_unicode_buffer(32768)
    assert ctypes.windll.kernel32.GetWindowsDirectoryW(system_buffer, len(system_buffer))
    system = Path(system_buffer.value)
    env = os.environ.copy()
    env['SystemRoot'] = str(system)
    env['PATH'] = str(system / 'System32') + ';' + str(system)
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)
    command_processor = str(system / 'System32' / 'cmd.exe')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f'http://127.0.0.1:{args.port}'

    def command(action):
        name = '启动知向联网版.cmd' if action == 'start' else '停止知向联网版.cmd'
        cmd = f'"{command_processor}" /d /s /c ""{app / name}" --port {args.port} --no-browser"'
        result = subprocess.run(cmd, cwd=app, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, errors='replace', timeout=90)
        if result.returncode:
            raise RuntimeError(f'便携包 {action} 失败：{result.stdout[-300:]}')

    def request(path, body=None):
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(base + path, data=payload,
                                     headers={'Content-Type': 'application/json', 'Origin': base})
        with opener.open(req, timeout=25) as response:
            raw = response.read()
        assert key not in raw, '本地 API 泄露了试用 Key'
        return json.loads(raw)

    def job(action, timeout=200):
        finish = time.monotonic() + timeout
        while time.monotonic() < finish:
            value = request('/api/jobs/' + action['job_id'])
            if value['status'] == 'done':
                return value['result']
            if value['status'] == 'error':
                raise RuntimeError('真实任务失败：' + value.get('error', ''))
            time.sleep(0.5)
        raise TimeoutError('真实任务超过验收上限')

    started = False
    try:
        command('start')
        started = True
        health = request('/api/health')
        settings = request('/api/search/settings')
        assert health['app_id'] == 'zhixiang-web' and health['version'] == '3.1.0-dsh'
        assert settings['provider'] == 'dsh'
        assert request('/api/bootstrap')['questions'] == []
        report['first_process'] = health['process_id']
        report['build'] = request('/api/bootstrap')['runtime']['build']
        report['provider'] = settings['provider']
        node_version = subprocess.run([str(app / 'runtime' / 'node' / 'node.exe'), '--version'],
                                      env=env, capture_output=True, text=True, check=True)
        report['bundled_node'] = node_version.stdout.strip()
        question = job(request('/api/search', {'question': '微软2025财年营收和利润是多少？', 'focus': 'official'}))
        candidates = question['search_report']['candidates']
        assert candidates and question['search_report']['provider'] == 'dsh-deepseek-official'
        report['real_search'] = {'question_id': question['id'], 'candidate_count': len(candidates),
                                 'queries': question['search_report'].get('actual_queries', []),
                                 'first_urls': [c['url'] for c in candidates[:5]]}
        readable = None
        candidate_imports = []
        for candidate in candidates[:7]:
            if not any(host in candidate['url'] for host in ('microsoft.com', 'microsoft.gcs-web.com')):
                continue
            attempt = job(request('/api/questions/' + question['id'] + '/search-import',
                                  {'candidate_ids': [candidate['id']], 'analyze': False}))
            candidate_imports.extend(attempt.get('search_import_report', {}).get('items', []))
            if attempt['source_ids']:
                sid = attempt['source_ids'][0]
                source = request('/api/sources/' + sid)
                if len(source.get('text', '')) > 500 and '2025' in source['text']:
                    readable = {'id': sid, 'url': source['url'], 'characters': len(source['text']),
                                'route': 'selected_search_candidate'}
                    break
        report['candidate_imports'] = [{k: item.get(k) for k in ('url', 'status', 'message')}
                                       for item in candidate_imports]
        report['candidate_readable'] = bool(readable)
        if not readable:
            # Independent, known publisher URL. Record this as a manual repair,
            # never as if the native search had produced a readable source.
            repaired = job(request('/api/questions/' + question['id'] + '/source',
                                   {'url': 'https://www.microsoft.com/investor/reports/ar25/index.html'}))
            for sid in repaired['source_ids']:
                source = request('/api/sources/' + sid)
                if len(source.get('text', '')) > 500 and '2025' in source['text']:
                    readable = {'id': sid, 'url': source['url'], 'characters': len(source['text']),
                                'route': 'manual_publisher_url_after_candidate_failure'}
                    break
        assert readable, '候选与明确补源都没有读到微软 FY2025 原文'
        report['real_source'] = readable
        saved = request('/api/questions/' + question['id'] + '/judgment',
                        {'text': '验收记录：已读取微软官方原文；具体财务数值仍待核对报告中的口径。',
                         'source_ids': [readable['id']], 'unresolved': ['核对财年与计量单位']})
        assert saved['judgment'] and len(saved['history']) == 1
        command('stop')
        started = False
        command('start')
        started = True
        health2 = request('/api/health')
        assert health2['process_id'] != health['process_id']
        reloaded = request('/api/questions/' + question['id'])
        assert reloaded['judgment'] == saved['judgment']
        report['restart_persistence'] = True
        report['all_passed'] = True
    finally:
        if started:
            command('stop')
        with socket.socket() as sock:
            report['test_service_stopped'] = sock.connect_ex(('127.0.0.1', args.port)) != 0
        output = ROOT / '验收' / '最终便携包实测.json'
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    assert report['all_passed'] and report['test_service_stopped']
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
