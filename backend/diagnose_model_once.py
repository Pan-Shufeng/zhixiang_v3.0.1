"""Explicit one-shot live diagnostic. No key, raw response, or model text is saved."""
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlparse

import requests
import server


def main():
    config = server.Settings(server.ROOT / 'config').config()
    key = config.get('api_key', '')
    destination = Path(__file__).resolve().parent / 'checks' / 'model_http_diagnostic.json'
    record = {'started_at': server.now(), 'maximum_chat_requests': 1, 'chat_requests_started': 0, 'max_tokens': 128, 'wall_limit_seconds': 25, 'model': config.get('model'), 'service_host': urlparse(config.get('base_url', '')).hostname, 'raw_response_saved': False, 'raw_model_content_saved': False}
    stopped = server.load_json(server.ROOT / 'data' / 'model_budget_stop.json', {})
    if not key or stopped.get('key_hash') == hashlib.sha256(key.encode()).hexdigest():
        record['outcome'] = 'skipped_missing_key_or_budget_stop'
        server.atomic_json(destination, record)
        print(json.dumps(record, ensure_ascii=True))
        return
    finished = threading.Event()
    cancelled = threading.Event()
    state = {}
    def safe_code(value):
        if isinstance(value, int):
            return value
        if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', value) and key not in value:
            return value
        return 'present_unclassified' if value is not None else None
    def request():
        session = requests.Session()
        session.trust_env = False
        state['session'] = session
        try:
            record['chat_requests_started'] += 1
            response = session.post(config['base_url'].rstrip('/') + '/chat/completions', headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, json={'model': config['model'], 'messages': [{'role': 'system', 'content': 'Return a JSON object only.'}, {'role': 'user', 'content': 'Return {"ok":true} as JSON.'}], 'temperature': .2, 'max_tokens': 128, 'stream': False, 'response_format': {'type': 'json_object'}, 'thinking': {'type': 'disabled'}}, timeout=(8, 20), stream=True, allow_redirects=False)
            state['response'] = response
            record['http_status'] = response.status_code
            record['response_content_type'] = response.headers.get('Content-Type', '').split(';')[0]
            chunks, size = [], 0
            for chunk in response.iter_content(1024):
                if cancelled.is_set():
                    return
                size += len(chunk)
                if size > 65536:
                    record['outcome'] = 'response_body_exceeds_diagnostic_limit'
                    return
                chunks.append(chunk)
            record['response_bytes'] = size
            try:
                body = json.loads(b''.join(chunks))
            except ValueError:
                record['outcome'] = 'non_json_response'
                return
            error = body.get('error') if isinstance(body, dict) else None
            if isinstance(error, dict):
                record['error_code'] = safe_code(error.get('code'))
                record['error_type'] = safe_code(error.get('type'))
                record['error_param'] = safe_code(error.get('param'))
                message = str(error.get('message', '')).lower()
                record['message_class'] = next((kind for terms, kind in [(('unsupported', 'not supported'), 'unsupported_parameter_or_feature'), (('invalid', 'validation'), 'invalid_request'), (('overloaded', 'busy'), 'service_busy'), (('internal', 'server error'), 'server_error'), (('balance', 'insufficient', 'quota'), 'balance_or_quota'), (('authentication', 'unauthorized', 'api key'), 'authentication')] if any(term in message for term in terms)), 'unclassified_service_error')
                record['outcome'] = 'service_error'
            else:
                record['outcome'] = 'http_success' if response.ok else 'http_error_without_structured_error'
                record['choices_present'] = bool(isinstance(body, dict) and body.get('choices'))
                try:
                    content = body['choices'][0]['message']['content']
                    record['json_object_completed'] = isinstance(json.loads(content), dict)
                except (TypeError, KeyError, IndexError, ValueError):
                    record['json_object_completed'] = False
        except requests.Timeout:
            record['outcome'] = 'network_timeout'
        except requests.RequestException:
            record['outcome'] = 'network_request_error'
        finally:
            finished.set()
            if state.get('response') is not None:
                state['response'].close()
            session.close()
    start = time.monotonic()
    threading.Thread(target=request, daemon=True, name='one-model-diagnostic').start()
    if not finished.wait(25):
        cancelled.set()
        record['outcome'] = 'wall_deadline_exceeded'
        # Process exit terminates this single daemon worker; no retry is made.
    record['elapsed_seconds'] = round(time.monotonic() - start, 3)
    record['completed_at'] = server.now()
    server.atomic_json(destination, record)
    print(json.dumps(record, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
