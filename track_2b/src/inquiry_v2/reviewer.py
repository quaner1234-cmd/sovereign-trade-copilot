"""Local-only human review prototype with a private, append-only event log.

This is an approval record, never a send operation or Company Context updater.
Study truth lives in a private case bank and is never returned to participants.
"""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import statistics
import uuid

from .message_plan import MessagePlan, encode
from .review_release import evaluate, check_edited_text, proposal_text

def now():
    return datetime.now(timezone.utc).isoformat()

def private_path(value):
    # Reuse the existing private-path validation, without opening its ledger.
    from .private_context import ContextStore
    return ContextStore(value).path

def pack(plan):
    return {'document_json':plan.document_json,'evidence_json':plan.evidence_json}

def unpack(value):
    return MessagePlan(**value)

def claim_expression(texts, fact):
    """Display exact matching paragraphs, never synthesize a claim or its proof."""
    from .reply_generation import _numeric_tokens
    from .message_gates import _payment_present
    paragraphs=[p.strip() for text in texts for p in re.split(r'\n+',text) if p.strip()]
    matches=[p for p in paragraphs if
             (isinstance(fact['value'],(int,float)) and fact['value'] in _numeric_tokens(p)) or
             ('payment' in fact['key'] and _payment_present(fact,p))]
    return '\n'.join(matches or texts)

def question_expression(texts, question):
    """Exact question fragments for display; ambiguity stays visible, not inferred."""
    from .message_gates import question_intent
    from .reply_generation import _EXTRA_QUESTION_FIELDS
    text='\n'.join(texts)
    if question['question'] in text:
        return question['question']
    fragments=[p.strip() for p in re.split(r'(?<=[?.!？。！])\s*|(?=¿)',text) if p.strip()]
    questions=[p for p in fragments if question_intent(p)]
    pattern=_EXTRA_QUESTION_FIELDS.get(question['field'])
    matched=[p for p in questions if pattern and re.search(pattern,p,re.I)]
    return '\n'.join(matched or questions or texts)

class ReviewConflict(ValueError):
    pass

class Reviewer:
    def __init__(self, environ=None):
        env=os.environ if environ is None else environ
        if not env.get('REVIEW_DB') or not env.get('REVIEW_ACTOR'):
            raise ValueError('private review database and operator are not configured')
        self.path=private_path(env['REVIEW_DB'])
        self.actor=env['REVIEW_ACTOR']
        self.cases_path=private_path(env['REVIEW_CASES']) if env.get('REVIEW_CASES') else None

    @contextmanager
    def _db(self):
        if private_path(str(self.path))!=self.path:
            raise ValueError('private path changed')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(str(self.path),timeout=10)
        db.execute('CREATE TABLE IF NOT EXISTS review_events (seq INTEGER PRIMARY KEY, review_id TEXT NOT NULL, kind TEXT NOT NULL, at TEXT NOT NULL, data TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS review_lookup ON review_events(review_id,seq)')
        for operation in ('UPDATE','DELETE'):
            db.execute('CREATE TRIGGER IF NOT EXISTS review_no_'+operation.lower()+' BEFORE '+operation+' ON review_events BEGIN SELECT RAISE(ABORT,"append-only review log"); END')
        db.commit()
        try:
            with db:
                yield db
        finally:
            db.close()

    def _get(self, ident):
        with self._db() as db:
            row=db.execute('SELECT data FROM review_events WHERE review_id=? ORDER BY seq DESC LIMIT 1',(ident,)).fetchone()
        if not row:
            raise ValueError('review not found')
        return json.loads(row[0])['state']

    def _append(self, state, kind, detail=None, expected=None):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM review_events WHERE review_id=? ORDER BY seq DESC LIMIT 1',(state['id'],)).fetchone()
            previous=json.loads(row[0])['state'] if row else None
            if expected is not None and (previous is None or previous['revision']!=expected):
                raise ReviewConflict('draft changed; reload current review before approving')
            state=deepcopy(state)
            state['revision']=previous['revision']+1 if previous else 1
            state['updated_at']=now()
            event={'actor':self.actor,'detail':detail or {},'state':state}
            db.execute('INSERT INTO review_events(review_id,kind,at,data) VALUES(?,?,?,?)',
                       (state['id'],kind,state['updated_at'],encode(event)))
        return state

    def cases(self):
        if not self.cases_path:
            return {'cases':[],'study_available':False}
        path=private_path(str(self.cases_path))
        data=json.loads(path.read_text(encoding='utf-8'))
        return {'cases':[{'id':c['id'],'title':c.get('title','Private review task'),
                          'cohort':c['cohort']} for c in data['cases'] if c['mode']=='review'],
                'study_available':True}

    def _bank(self):
        if not self.cases_path:
            raise ValueError('study case bank is not configured')
        return json.loads(private_path(str(self.cases_path)).read_text(encoding='utf-8'))

    def start(self, body):
        kind=body.get('kind','practice')
        if kind not in ('practice','human_study'):
            raise ValueError('invalid review kind')
        bank=self._bank()
        if kind=='human_study':
            if body.get('consent') is not True:
                raise ValueError('explicit human study consent required')
            schedule=bank['schedule']
        else:
            chosen=body.get('case_id')
            schedule=[chosen] if chosen else [c['id'] for c in bank['cases'] if c['mode']=='review']
        valid={c['id'] for c in bank['cases']}
        if not schedule or not set(schedule)<=valid:
            raise ValueError('unknown review task')
        run={'id':str(uuid.uuid4()),'kind':kind,'schedule':schedule,'completed':[],
             'current_review':None,'questionnaire':None,'created_at':now()}
        run=self._append(run,'run_start',{'consent':body.get('consent') is True})
        return {'run_id':run['id'],'task_count':len(schedule)}

    def next_task(self, body):
        run=self._get(body['run_id'])
        if run['current_review']:
            state=self._get(run['current_review'])
            if state['decision'] is None:
                return self.view(state)
            run['completed'].append(state['id'])
            run['current_review']=None
        index=len(run['completed'])
        if index>=len(run['schedule']):
            self._append(run,'run_tasks_complete',expected=run['revision'])
            return {'complete':True,'run_id':run['id'],'task_count':index}
        case=next(c for c in self._bank()['cases'] if c['id']==run['schedule'][index])
        state={'id':str(uuid.uuid4()),'run_id':run['id'],'kind':run['kind'],
               'case_id':case['id'],'cohort':case['cohort'],'mode':case['mode'],
               'index':index+1,'total':len(run['schedule']),'request':case['request'],
               'plan':case.get('plan'),'proposal':case.get('proposal'),
               'audit':case.get('audit'),'result':case.get('result'),
               'draft':proposal_text(case.get('proposal')),'original_draft':proposal_text(case.get('proposal')),
               'false_positive_warnings':[],'decision':None,'approval':None,
               'started_at':now(),'edit_operations':0,'interaction_counts':{},'metrics':None}
        state=self._append(state,'task_start')
        run['current_review']=state['id']
        self._append(run,'run_next',expected=run['revision'])
        return self.view(state)

    def view(self, state):
        baseline=state['mode']=='baseline'
        plan=unpack(state['plan']) if state.get('plan') else None
        policy=evaluate(plan,state['proposal'],audit=state.get('audit')) if plan else None
        doc=plan.document if plan else None
        request=state['request']
        inquiry=request['inquiry']
        company_sources=(request.get('company_context') or {}).get('sources',[])
        claims=[]
        rendered_questions=[]
        if doc and not baseline:
            for question in doc['approved_questions']:
                expressions=[s['text'] for s in state['proposal']['slots'] if question['id'] in s['item_ids']]
                rendered_questions.append({**question,'expression':question_expression(expressions,question)})
            # Show claims bound to rendered content, with actual wording. A full
            # edited-text slot conservatively shows every required company claim.
            for answer in doc['required_answers']:
                for fact in answer['facts']:
                    if fact['role']!='company':continue
                    slots=[s['text'] for s in state['proposal']['slots'] if answer['id'] in s['item_ids']]
                    if slots:
                        claims.append({'label':answer['topic'],'expression':claim_expression(slots,fact),
                            'value':fact['value'],'unit':fact['unit'],'scope':fact['scope'],
                            'conditions':fact['conditions'],'source':fact['quote'],
                            'source_id':fact['source_id'],'item_id':answer['id']})
        evidence=[]
        if plan:
            evidence=plan.evidence_contract.get('source_context',[])
        return {'review_id':state['id'],'revision':state['revision'],'mode':state['mode'],
            'kind':state['kind'],'index':state.get('index',1),'total':state.get('total',1),
            'draft':state['draft'],'decision':state['decision'],'approval':state.get('approval'),
            'inquiry':inquiry,'company_sources':[{'text':s.get('text',''),'scope':s.get('scope')} for s in company_sources],
            'primary':doc['primary_advance'] if doc and not baseline else None,
            'parallel':doc['parallel_reversible_advances'] if doc and not baseline else [],
            'questions':rendered_questions,
            'company_claims':claims if not baseline else [],'source_state':doc['source_state'] if doc and not baseline else [],
            'policy':policy if not baseline else None,'evidence':evidence if not baseline else [],
            'false_positive_warnings':state['false_positive_warnings'],
            'warning_reviews':state.get('warning_reviews',[]),
            'technical':{'plan_hash':plan.hash,'message_plan':doc,'audit':state.get('audit')} if plan and not baseline else None,
            'model_latency_ms':state.get('model_latency_ms'),
            'timing_reloaded':state.get('metrics') is not None}

    def act(self, body):
        state=self._get(body['review_id'])
        if state['revision']!=body.get('revision'):
            raise ReviewConflict('review changed; reload before taking an action')
        if state['decision'] is not None:
            raise ReviewConflict('completed review is immutable; start a new practice review')
        old_revision=state['revision']
        action=body.get('action')
        if action=='edit':
            draft=body.get('draft')
            if not isinstance(draft,str) or not draft.strip() or len(draft)>20000:
                raise ValueError('bounded nonempty draft required')
            if state.get('plan'):
                proposal,_=check_edited_text(unpack(state['plan']),draft)
                state['proposal']=proposal
            state['draft']=draft.strip()
            state['edit_operations']+=int(state['draft']!=self._get(state['id'])['draft'])
            state['audit']=None
            state['false_positive_warnings']=[]
            state['warning_reviews']=[]
        elif action=='correct_plan':
            plan=unpack(state['plan']);doc=plan.document;contract=plan.evidence_contract
            target=body.get('target');replacement=body.get('text','').strip()
            if not replacement or len(replacement)>1500 or not body.get('reason','').strip():
                raise ValueError('a short correction and source/judgment reason are required')
            if target=='primary':
                item=doc['primary_advance']
                item['operation']=replacement
                contract['judgment']['primary_advance']['task']=replacement
            else:
                item=next((q for q in doc['approved_questions'] if q['id']==target),None)
                if not item:
                    raise ValueError('only the primary intent or an existing approved question can be corrected')
                item['question']=replacement
                for q in contract['permitted_questions']:
                    if q['id']==target:q['question']=replacement
            item['provenance']['authorization']={'kind':'explicit_human_plan_correction','actor':self.actor,
                'at':now(),'reason':body['reason'],'previous_plan_hash':plan.hash}
            # New immutable revision; old plan remains in the append-only log.
            new_plan=MessagePlan(encode(doc),encode(contract))
            state['plan']=pack(new_plan)
            state['proposal']['plan_hash']=new_plan.hash
            state['audit']=None;state['false_positive_warnings']=[]
            state['warning_reviews']=[]
            state['edit_operations']+=1
        elif action=='warning_fp':
            policy=evaluate(unpack(state['plan']),state['proposal'])
            if body.get('code') not in {f['code'] for f in policy['warnings']}:
                raise ValueError('only advisory warnings can be marked false positive')
            state['false_positive_warnings'].append({'code':body['code'],'note':body.get('note',''),'at':now()})
        elif action=='warning_review':
            policy=evaluate(unpack(state['plan']),state['proposal'])
            if body.get('code') not in {f['code'] for f in policy['warnings']} or body.get('outcome') not in {'helpful','irrelevant'}:
                raise ValueError('a located advisory warning and explicit assessment are required')
            state.setdefault('warning_reviews',[]).append({'code':body['code'],'outcome':body['outcome'],'at':now()})
        elif action=='interaction':
            key=body.get('section')
            if key not in {'inquiry','primary','parallel','questions','claims','evidence','sources','warnings','technical','pause'}:
                raise ValueError('unknown interaction section')
            state['interaction_counts'][key]=state['interaction_counts'].get(key,0)+1
        elif action in {'approve','reject'}:
            if action=='approve':
                if not state['draft'].strip():raise ValueError('cannot approve an empty draft')
                if state.get('plan') and not evaluate(unpack(state['plan']),state['proposal'])['passed']:
                    raise ReviewConflict('hard invariant unresolved; edit or reject, no approval recorded')
                state['approval']={'actor':self.actor,'at':now(),
                    'draft_sha256':hashlib.sha256(state['draft'].encode()).hexdigest(),
                    'plan_hash':unpack(state['plan']).hash if state.get('plan') else None,
                    'revision':old_revision,'execution_authorized':False,'sent':False}
            elif not body.get('note','').strip():
                raise ValueError('a rejection reason is required')
            metrics=body.get('metrics') or {}
            for key in ['active_ms','wall_ms','edit_input_events']:
                if type(metrics.get(key)) is not int or not 0<=metrics[key]<=86400000:
                    raise ValueError('valid client timing required')
            if metrics['active_ms']>metrics['wall_ms']+1000:
                raise ValueError('active time cannot exceed wall time')
            state['metrics']=metrics
            state['decision']=action;state['decision_note']=body.get('note','')
        else:
            raise ValueError('unknown review action')
        state=self._append(state,action,{k:body[k] for k in ['note','target','reason','section','code'] if k in body},expected=old_revision)
        return self.view(state)

    def regenerate(self, body):
        state=self._get(body['review_id'])
        if state['kind']=='human_study':
            raise ValueError('study uses frozen outputs; finish with Reject, then regenerate in practice')
        if state['revision']!=body.get('revision'):
            raise ReviewConflict('stale regeneration request')
        if not state.get('plan'):
            raise ValueError('baseline has no approved message plan')
        from .reply_renderer import render_plan
        plan=unpack(state['plan'])
        reply=render_plan(plan)
        if not reply.get('proposal'):
            raise ValueError('Apertus did not return a usable surface proposal')
        # Preserve rejected/approved records; regeneration creates a separate review.
        new=deepcopy(state);new['id']=str(uuid.uuid4());new['decision']=None;new['approval']=None
        new['proposal']=reply['proposal'];new['audit']=reply.get('advisory_audit')
        new['draft']=proposal_text(new['proposal']);new['original_draft']=new['draft']
        new['metrics']=None;new['started_at']=now();new['edit_operations']=0
        new['false_positive_warnings']=[];new['interaction_counts']={}
        new['warning_reviews']=[]
        return self.view(self._append(new,'regenerate',{'previous_review':state['id'],'same_plan_hash':plan.hash}))

    def live(self, body):
        text=body.get('text','')
        if not isinstance(text,str) or not text.strip() or len(text)>15000:
            raise ValueError('bounded inquiry text required')
        from . import analyze
        from .message_plan import build
        from .source_registry import build as sources_for
        from .context_service import PrivateContextAccess
        access=PrivateContextAccess()
        store=access._store({'Authorization':'Bearer '+access._token}) if access.ready else None
        request={'inquiry':{'primary':{'text':text},'attachments':body.get('attachments',[])},
                 'research':{'enabled':False},'use_model':True,'generate_reply':True}
        result=analyze(request,context_store=store)
        reply=result['reply']
        if not reply.get('proposal'):raise ValueError('Apertus unavailable; no substitute draft was fabricated')
        # The exact private validation contract can be reconstructed from the
        # registry enriched by the same scoped context used by analyze().
        from .context_runtime import load_context
        registry=sources_for(request)
        if store:load_context(request,registry,result['understanding'],store)
        plan=build(result,registry)
        if plan.hash!=reply['message_plan']['plan_hash']:
            raise ValueError('live plan reconstruction mismatch; review unavailable')
        state={'id':str(uuid.uuid4()),'run_id':None,'kind':'practice','case_id':None,'cohort':'live_private',
            'mode':'review','request':request,'plan':pack(plan),'proposal':reply['proposal'],
            'audit':reply.get('advisory_audit'),'result':result,'draft':proposal_text(reply['proposal']),
            'original_draft':proposal_text(reply['proposal']),'decision':None,'approval':None,
            'started_at':now(),'metrics':None,'false_positive_warnings':[], 'edit_operations':0,'interaction_counts':{},
            'model_latency_ms':sum(a.get('metadata',{}).get('latency_ms',0) for a in reply['attempts'])}
        return self.view(self._append(state,'live_prepare'))

    def finish(self, body):
        run=self._get(body['run_id'])
        if len(run['completed'])!=len(run['schedule']):raise ValueError('finish all tasks before questionnaire')
        q=body.get('questionnaire') or {}
        if q.get('daily_use') not in ('yes','maybe','no'):raise ValueError('daily-use response required')
        run['questionnaire']=q
        self._append(run,'questionnaire',expected=run['revision'])
        return self.summary(run['id'])

    def summary(self, ident):
        run=self._get(ident)
        states=[self._get(v) for v in run['completed']]
        measured=[s for s in states if s['kind']=='human_study' and s.get('metrics')]
        timed=[s for s in measured if not s['metrics'].get('reloaded') and s['metrics'].get('additional_tools')!='general_llm']
        times={mode:[s['metrics']['active_ms']/1000 for s in timed if s['mode']==mode and s['cohort']=='synthetic_matched'] for mode in ['review','baseline']}
        reviews=[s for s in measured if s['mode']=='review']
        median=lambda a:statistics.median(a) if a else None
        edits=[]
        for s in reviews:
            edits.append(sum(max(b-a,d-c) for tag,a,b,c,d in SequenceMatcher(None,s['original_draft'],s['draft']).get_opcodes() if tag!='equal'))
        return {'human_completed':len(measured),'practice_excluded':len(states)-len(measured),
            'median_review_seconds':median(times['review']),'median_baseline_seconds':median(times['baseline']),
            'matched_task_counts':{k:len(v) for k,v in times.items()},
            'reloaded_tasks_excluded_from_timing':len(measured)-len(timed),
            'timing_exclusions':{'reload':sum(bool(s['metrics'].get('reloaded')) for s in measured),
                'external_llm':sum(s['metrics'].get('additional_tools')=='general_llm' for s in measured)},
            'approve_without_edit':sum(s['decision']=='approve' and s['draft']==s['original_draft'] and s['edit_operations']==0 for s in reviews),
            'approve_with_edit':sum(s['decision']=='approve' and (s['draft']!=s['original_draft'] or s['edit_operations']>0) for s in reviews),
            'reject':sum(s['decision']=='reject' for s in reviews),
            'average_edit_operations':statistics.mean([s['edit_operations'] for s in reviews]) if reviews else None,
            'average_changed_characters':statistics.mean(edits) if edits else None,
            'opened_sections':{key:sum(s['interaction_counts'].get(key,0) for s in reviews) for key in ['claims','evidence','sources','warnings','technical']},
            'warning_fp_marks':sum(len(s['false_positive_warnings']) for s in reviews),
            'warning_assessments':[a for s in reviews for a in s.get('warning_reviews',[])],
            'critical_detection_rate':None,'missed_risk_count':None,'hard_gate_fp_rate':None,'hard_gate_fn_rate':None,
            'business_grading':'Independent source-based grading required; clicks and gate PASS are not detection ground truth.',
            'questionnaire':run.get('questionnaire'),
            'mvp_verdict':'NOT_ESTABLISHED' if not run.get('questionnaire') else 'PENDING_BUSINESS_REVIEW',
            'timing_scope':'Active human review/writing, excludes hidden/paused intervals and precomputation. Private unmatched tasks kept separate.'}
