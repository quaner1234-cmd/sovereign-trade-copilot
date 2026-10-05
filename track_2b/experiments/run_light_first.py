"""Freeze inputs/prompts before exactly one generation per synthetic case."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import light_harness as H
import llm_client

folder = ROOT / 'data/light-demo'
output = folder / 'first-drafts.json'
if output.exists():
    raise SystemExit('First drafts already frozen; refusing to overwrite or select a new result.')
if llm_client.demo_mode() or llm_client.CONFIG['model'] != 'swiss-ai/Apertus-v1.5-70B':
    raise SystemExit('Real Apertus v1.5 70B configuration required. No offline substitute.')
cases = json.loads((folder / 'cases.json').read_text(encoding='utf-8'))['cases']
frozen = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'model_requested': llm_client.CONFIG['model'],
          'runs_per_case': 1, 'transport_attempts': 1, 'selection': 'first output, no retry',
          'case_file_sha256': hashlib.sha256((folder / 'cases.json').read_bytes()).hexdigest(),
          'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in (ROOT/'src/light_harness.py', ROOT/'src/light_skill.md', ROOT/'src/llm_client.py')},
          'prompts': {c['id']: H.messages(H.normalize(c)) for c in cases}}
(folder / 'freeze.json').write_text(json.dumps(frozen, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
records = []
for case in cases:
    result = H.process(case)
    records.append({'case_id': case['id'], 'input_hash': H.digest(H.normalize(case)), **result})
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'case': case['id'], 'status': result['status'], 'meta': result.get('meta'),
                      'warnings': result.get('warnings'), 'raw_draft': result.get('raw_draft')}, ensure_ascii=False), flush=True)
