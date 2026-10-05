"""Independent P5.2 held-out plan evaluation. Failures are never remapped to PASS.

This evaluator performs no network calls. Customer-language live evaluation is
separate. The fixture is synthetic and its expectations are evaluation truth,
not production rules or new human confirmation.
"""
import json
from pathlib import Path
from inquiry_v2 import analyze
from inquiry_v2.source_registry import build as registry_for
from inquiry_v2.message_plan import build


def evaluate(case):
    request,expected=case['request'],case['expected']
    result=analyze(request)
    plan=build(result,registry_for(request)).document
    lines=plan['line_item_scope']
    axes={'judgment':result['advance']['action']==expected['action'],
          'quantities':[l['quantity'] for l in lines]==expected['quantity'],
          'approved_questions':[q['field'] for q in plan['approved_questions']]==expected['questions'],
          'construction':not plan['construction_issues']}
    if 'purpose' in expected:axes['quantity_purpose']=[l['quantity_purpose'] for l in lines]==expected['purpose']
    if expected.get('source_first'):axes['source_first']=bool(plan['primary_advance']['source_preconditions'])
    if expected.get('parallel'):axes['parallel']=bool(plan['parallel_reversible_advances'])
    if 'language' in expected:axes['language']=plan['language']==expected['language']
    return {'id':case['id'],'passed':all(axes.values()),'axes':axes,
            'failure_layer':'upstream' if not all(axes.values()) else None}


if __name__=='__main__':
    fixture=Path(__file__).resolve().parents[1]/'data/inquiry_v2_message_plan_acceptance.json'
    results=[evaluate(c) for c in json.loads(fixture.read_text(encoding='utf-8'))['cases']]
    for result in results:print(json.dumps(result,ensure_ascii=False))
    raise SystemExit(0 if all(r['passed'] for r in results) else 1)
