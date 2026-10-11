"""Clean-checkout integration smoke; a live call is not a scored retry."""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from light_harness import VERSION

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:8000')
parser.add_argument('--mode', choices=['recorded_replay', 'live_apertus'], required=True)
parser.add_argument('--output', type=Path, help='Preserve complete synthetic first outputs, including failed attempts.')
args = parser.parse_args()


def request(path, body=None):
    payload = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(args.url + path, data=payload,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as response:
        data = response.read()
        return data.decode() if path == '/ui' else json.loads(data)


health = request('/health')
assert health['pipeline'] == VERSION and health['mode'] == args.mode
assert health['sending_enabled'] is False
assert 'Why this reply?' in request('/ui')
cases = request('/samples')['samples']
assert len(cases) == 3 and all('gold' not in case for case in cases)
frozen = json.loads((Path(__file__).resolve().parents[1] / 'data/light-demo/first-drafts.json').read_text(encoding='utf-8'))
summary = {'mode': args.mode, 'pipeline': health['pipeline'], 'health_ui': 'PASS', 'cases': []}
records = []
for case in cases if args.mode == 'recorded_replay' else cases[:1]:
    unconfirmed = {**case, 'context_authorized': False}
    assert request('/process', unconfirmed)['status'] == 'confirmation_required'
    result = request('/process', {**case, 'context_authorized': True})
    records.append({'case': case['id'], 'input': case, 'first_output': result})
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    assert result['status'] == 'draft_for_human_review' and result['raw_draft'] == result['draft']
    assert result['needs_human_approval'] is True
    if args.mode == 'recorded_replay':
        expected = next(r for r in frozen if r['case_id'] == case['id'])
        assert result['raw_draft'] == expected['raw_draft']
        assert result['meta']['new_model_calls'] == 0
    else:
        assert result['meta']['new_model_calls'] == 1
        assert result['meta'].get('model') == 'swiss-ai/Apertus-v1.5-70B'
    edited = result['draft'] + '\n\nOnce we review the priority design and material route, we can prepare a sample-cost basis and conditional preliminary costing.'
    approval = request('/approve', {'draft_id': result['draft_id'], 'actor': 'Integration test (scripted)',
                                   'reviewed': True, 'draft': edited})
    assert approval['status'] == 'human_approved' and approval['edited']
    assert approval['sending_enabled'] is False
    summary['cases'].append({'case': case['id'], 'status': 'PASS', 'warnings': len(result['warnings']),
                             'raw_sha256': hashlib.sha256(result['raw_draft'].encode()).hexdigest(),
                             'meta': result['meta'], 'approval': 'scripted version-binding test only'})
if args.mode == 'recorded_replay':
    changed = {**cases[0], 'inquiry': cases[0]['inquiry'] + '\nChanged input.'}
    assert request('/process', changed)['status'] == 'endpoint_required'
    summary['changed_input'] = 'PASS: no fake offline generation'
print(json.dumps(summary, indent=2))
