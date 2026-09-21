"""Prepare local web edition settings without printing or copying personal records."""
from pathlib import Path
import argparse
import json
import shutil
from build_package import load_trial, DEFAULT_TRIAL_ENV, DEFAULT_TRIAL_MODEL

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL = ROOT.parent / '知向'
assert ROOT.name == '知向联网版'
parser = argparse.ArgumentParser(description='Prepare only the independent web edition; never modify shared API configuration')
parser.add_argument('--trial-model', default=DEFAULT_TRIAL_MODEL)
args = parser.parse_args()
trial = load_trial(DEFAULT_TRIAL_ENV)
trial['model'] = args.trial_model
(ROOT / 'config').mkdir(exist_ok=True)
(ROOT / 'config' / 'trial.json').write_text(json.dumps(trial, ensure_ascii=False, indent=2), encoding='utf-8')
shutil.copy2(ORIGINAL / 'packaging' / 'runtime_manifest.json', ROOT / 'packaging' / 'runtime_manifest.json')
for action in ('启动', '停止'):
    # All copied launcher code resolves the new edition's root and default port.
    shutil.copy2(ORIGINAL / f'{action}知向.cmd', ROOT / f'{action}知向联网版.cmd')
print(json.dumps({'edition': ROOT.name, 'port': 8186, 'trial_configured': bool(trial.get('api_key')), 'model': trial.get('model'), 'original_modified': False}, ensure_ascii=False))
