"""Mandatory actual-text gates. An advisory model verdict is never an input."""
import re
from .message_plan import customer_view
from .understand import PRODUCT_RE, PAYMENT_RE, QTY_RE, _number, canonical_product, canonical_payment, _cue_polarity, _sentence_bounds
from .guard_v2 import _source_valid, AMOUNT_RE
from .reply_generation import (_numeric_tokens, _value_in_text, _unit_and_basis_present, _external_scope_issues,
    _actual_count_binding, _source_assertion_issues, _QUESTION_FIELDS, _EXTRA_QUESTION_FIELDS, _ACTION_WORDS,
    _COMPANY_ASSERTION, _COMPANY_OWNERSHIP, _COURTESY)

CHECKS = ['authorization','provenance','scope','unit','ownership','polarity','attachment_state',
          'required_content','approved_questions','primary_advance','unsupported_commitment']

def verification_intent(text):
    return bool(re.search(r"\b(?:check|verify|review|assess|confirm)\b.{0,60}\b(?:whether|if|ability|options|possibility|availability)\b|核实|核查|确认(?:是否|能否)|检查|verificar|comprobar|revisar.{0,35}(?:si|opciones)", text, re.I))

def _commitment(text, company=()):
    for clause in re.split(r"[.;。；\n]|\b(?:but|then)\b", text, flags=re.I):
        if re.search(r"\b(?:we|I)\s+(?:(?:will|shall|can)\s+)?(?:ship|dispatch|deliver|produce|manufacture|guarantee|pay|accept|approve|release)\b|我们(?:将|会|可以)(?:发货|生产|付款)|保证|(?:enviamos|enviaremos|fabricaremos|garantizamos)\b", clause, re.I):
            stated_terms=(re.search(r'\bwe\s+accept\b',clause,re.I) and not re.search(r'order|quote|quotation',clause,re.I)
                and any('payment' in f['key'] and _payment_present(f,clause) for f in company))
            # Verification subordinate clauses do not license a separate promise.
            if not stated_terms and (not verification_intent(clause) or re.search(r"\b(?:we|I)\s+(?:will|shall)\s+(?:ship|dispatch|deliver|produce|pay|accept|approve|release)\b|我们(?:将|会)(?:发货|生产|付款)", clause, re.I)):
                return True
        if re.search(r"(?:order|shipment|production|quotation|payment).{0,15}(?:confirmed|approved|accepted)|(?:confirmed|approved).{0,15}(?:order|shipment|production)|订单已确认|已批准(?:生产|发货|报价)", clause, re.I):
            match = re.search(r"confirmed|approved|accepted|已确认|已批准", clause, re.I)
            if match and _cue_polarity(clause, match.start(), match.end()) == 'positive':
                return True
    return False

def _condition_present(condition, text):
    # Existing bounded domain translations; unsupported paraphrases stay reviewable.
    concepts = {"material": r"material|fabric|材料|面料", "standard": r"standard|normal|常规|标准|正常|estándar",
        "approved": r"approved|confirmed|批准|确认|aprobado", "colour": r"colou?r|颜色|色|color",
        "minimum": r"minimum|MOQ|最低|起订|mínim", "review": r"review|check|verify|核实|核查|审核|评估|revis|verific",
        "route": r"route|路线|方案|ruta", "sea": r"sea|ocean|海运|marítim", "air": r"air|空运|aéreo"}
    tokens = re.findall(r"[a-z]+", condition.lower())
    required = [v for k,v in concepts.items() if k in tokens]
    return all(re.search(p, text, re.I) for p in required) if required else condition.casefold() in text.casefold()

def _payment_present(fact, text):
    return any(canonical_payment(m.group()) == canonical_payment(fact['value']) for m in PAYMENT_RE.finditer(text))

def question_intent(text):
    return bool(re.search(r'[?？]|\b(?:please\s+(?:send|share|provide|confirm|tell)|could\s+you|can\s+you|would\s+you|let\s+(?:us|me)\s+know|tell\s+(?:us|me))\b|请(?:提供|发送|告知|确认)|por\s+favor|necesito\s+saber|ind[ií]c|dime',text,re.I))

def validate(plan, proposal):
    doc, contract = plan.document, plan.evidence_contract
    items = {i['id']:i for i in doc['required_answers'] + doc['approved_questions'] + [doc['primary_advance']] + doc['parallel_reversible_advances']}
    all_facts = doc['allowed_customer_facts'] + doc['allowed_company_claims'] + doc['allowed_external_references']
    sources = {s['id']:s for s in contract['_validation']['registry']['sources']}
    problems=[]
    def issue(code, slot=None, layer='renderer'):
        problems.append({'code':code,'slot':slot,'layer':layer})
    for code in doc['construction_issues']:
        issue(code, layer='upstream_review')
    for fact in all_facts:
        if not _source_valid(fact,sources):
            issue('invalid_fact_provenance:'+fact['id'],layer='plan')
    if proposal.get('plan_hash') != plan.hash:
        issue('immutable_plan_binding_changed',layer='plan')
    if not isinstance(proposal.get('slots'),list) or not proposal['slots']:
        issue('invalid_message_slots'); return _result(problems)
    seen=[]
    for index,slot in enumerate(proposal['slots']):
        ids,text=slot.get('item_ids'),slot.get('text')
        if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or not set(ids)<=items.keys() or not isinstance(text,str) or not text.strip():
            issue('invalid_slot_binding',index);continue
        seen+=ids
        linked=[items[i] for i in ids]
        fact_scope={lid for i in linked for lid in i.get('line_ids',[])}
        support=[f for f in all_facts if not f['line_ids'] or set(f['line_ids']) & fact_scope]
        values={n for f in support for n in _numeric_tokens(str(f['value']))}
        if any(n not in values for n in _numeric_tokens(text)):
            issue('unsupported_number',index)
        for match in AMOUNT_RE.finditer(text):
            currency=re.match(r'USD|EUR|GBP|[$€£]',match.group(),re.I).group().upper()
            if not any(str(f.get('unit','')).upper()==currency and _value_in_text(f,match.group()) for f in support):
                issue('unsupported_amount_or_currency',index)
        company=[f for i in linked if i['kind']=='answer' for f in i['facts'] if f['role']=='company']
        if _commitment(text,company): issue('unsupported_commitment',index)
        if re.search(r'\b(?:your|the|this)\s+(?:(?:bulk|production)\s+)?order\b',text,re.I):
            issue('inquiry_or_interest_stated_as_order',index)
        for clause in re.split(r'[.;。；]|\band\s+(?=we|our|I)\b',text,flags=re.I):
            assertion=(_COMPANY_ASSERTION.search(clause) or _COMPANY_OWNERSHIP.search(clause) or re.search(r"we (?:do not|don't|cannot|can't) (?:accept|produce|manufacture|offer)|we have no|我们(?:不支持|没有库存)",clause,re.I))
            if assertion and not verification_intent(clause):
                if not company: issue('unsupported_company_claim',index)
                for pattern,key in [(r'\bstock\b|库存','stock'), (r'certifi|认证','certification'),
                    (r'we\s+(?:can\s+)?(?:produce|make|manufacture)|我们可以生产','capability'),
                    (r'we\s+(?:can\s+)?accept|payment\s+terms|付款条件','payment')]:
                    if re.search(pattern,clause,re.I) and not any(key in f['key'] for f in company):
                        issue('unsupported_company_'+key,index)
        for item in linked:
            if item['kind']=='answer':
                for fact in item['facts']:
                    present=_payment_present(fact,text) if 'payment' in fact['key'] else _value_in_text(fact,text)
                    if not present: issue('required_answer_omitted:'+item['id'],index)
                    if not _unit_and_basis_present(fact,text): issue('unit_or_basis_changed:'+item['id'],index)
                    if 'moq' in fact['key'] and 'style' in str(fact['unit']) and not re.search(r'colou?r',str(fact['unit']),re.I) and re.search(r'per\s+colou?r|each\s+colou?r|每(?:款)?(?:颜色|色|材质)',text,re.I):
                        issue('moq_basis_expanded:'+item['id'],index)
                    for condition in fact['conditions']:
                        if not _condition_present(condition,text): issue('condition_omitted:'+item['id'],index)
                    if fact['role']=='external':
                        for code in _external_scope_issues(fact,text): issue(code,index)
                    if 'payment' in fact['key'] and re.search(r'not\s+accept|do\s+not|不支持|不接受',text,re.I): issue('company_payment_polarity_changed',index)
            elif item['kind']=='question':
                pattern=_QUESTION_FIELDS.get(item['field'],r'(?!)')
                if not re.search(pattern,text,re.I) or not question_intent(text): issue('approved_question_omitted:'+item['id'],index)
            elif item['kind']=='advance':
                if re.search(r'\b(?:I|we)\s+(?:(?:have|had)\s+(?:already\s+)?|already\s+)(?:reviewed|verified|completed|approved|costed)|(?:已经|已完成|已核实).{0,15}(?:核价|成本|可行性)',text,re.I) and re.search(r'cost|feasib|development|核价|成本|可行性',text,re.I):
                    issue('advance_stated_as_completed',index)
                if not re.search(_ACTION_WORDS[item['action']],text,re.I): issue('advance_operation_lost:'+item['id'],index)
                if not re.search(r'cost|material|construction|sample|quantity|minimum|MOQ|small.lot|small.run|route|brief|drawing|reference|development|rights|价格|核价|成本|材料|样品|数量|起订|小批量|路线|资料|图纸|coste|costo|muestra|cantidad|modelo|material|ruta',text,re.I):
                    issue('advance_object_lost:'+item['id'],index)
                if item['source_preconditions'] and not re.search(r'attach|brief|drawing|reference|material|附件|资料|图纸|adjunt|dibujo',text,re.I):
                    issue('source_first_advance_lost',index)
                if item['id'].startswith('parallel-') and not re.search(r'subject\s+to|conditional|provisional|pending|depend|以.{0,20}为前提|有条件|待.{0,20}确认|sujeto|condicional|supedit',text,re.I):
                    issue('parallel_condition_lost',index)
        approved_fields={i['field'] for i in linked if i['kind']=='question'}
        request=question_intent(text)
        if request and not approved_fields: issue('extra_customer_question',index)
        if request:
            for field,pat in _EXTRA_QUESTION_FIELDS.items():
                if field not in approved_fields and re.search(pat,text,re.I): issue('extra_question_field:'+field,index)
        for code in _source_assertion_issues(text,contract):issue(code,index)
        if any(s['state']!='read' for s in doc['source_state']) and re.search(r"(?:you\s+(?:have\s+)?not\s+provided|missing\s+(?:attachment|brief)|no\s+(?:attachment|drawing)|未提供|没有提供)",text,re.I):
            issue('unread_source_stated_as_absent',index)
        if re.search(r"\b(?:you\s+(?:have\s+)?(?:provided|sent|supplied)|your\s+(?:provided|supplied))\b",text,re.I):
            readable=' '.join(s['text'] for s in sources.values() if s['party']=='customer' and s['status']=='read')
            actual=[]
            for m in re.finditer(r'provided|sent|supplied|attached|enclosed|已提供|已发送',readable,re.I):
                a,b=_sentence_bounds(readable,*m.span())
                if _cue_polarity(readable[a:b],m.start()-a,m.end()-a)=='positive':actual.append(m.group())
            if not actual and not any(s['kind']=='attachment' for s in doc['source_state']):issue('unsupported_customer_provided_material',index)
        for p in doc['polarity_constraints']:
            if p['polarity']=='positive':continue
            term=r'logo|logotipo|标志' if 'logo' in p['text'].lower() else re.escape(p['text'])
            for m in re.finditer(term,text,re.I):
                a,b=_sentence_bounds(text,*m.span())
                if _cue_polarity(text[a:b],m.start()-a,m.end()-a)=='positive' and not verification_intent(text[a:b]):issue('critical_polarity_drift',index)
        for code in _actual_count_binding(text,contract):issue(code,index)
        for count in QTY_RE.finditer(text):
            value=_number(count.group('first'))
            matching=[f for f in support if f['key']=='quantity' and f['value']==value]
            if matching and re.search(r'sample|prototype|样品|原型|muestra',count.group(),re.I) and all(f['purpose'] not in {'prototype','evaluation_sample'} for f in matching):
                issue('quantity_purpose_changed',index)
        if re.search(r'COMPANY_CONFIRMED|PUBLIC_REFERENCE|WORKING_VALUE|decision.barrier|hard.blocker|business_owner|sample_coordinator|source.preconditions|operator|客户应|公司应该',text,re.I):issue('internal_operator_leakage',index)
        allowed_products={canonical_product(l['product_ref']) for l in doc['line_item_scope']}
        for m in PRODUCT_RE.finditer(text):
            name=canonical_product(m.group())
            if not any(name==p or name.endswith(' '+p) or p.endswith(' '+name) for p in allowed_products):issue('unsupported_product',index)
    for s in doc['ordered_message_slots']:
        for ident in s['item_ids']:
            if s['required'] and ident not in seen:issue('required_item_missing:'+ident)
    if len(seen)!=len(set(seen)):issue('repeated_content_binding')
    draft='\n\n'.join(s.get('text','') for s in proposal['slots'])
    language=doc['language']
    patterns={'zh':r'[\u4e00-\u9fff]', 'th':r'[\u0e00-\u0e7f]',
        'es':r'\b(?:el|la|los|las|para|cantidad|podemos|revisar|precio|modelo|gracias)\b|[¿áéíóúñ]',
        'pl':r'[ąćęłńóśźż]|\b(?:proszę|ilość|cena|materiał|próbka|sprawdzimy|dziękujemy)\b',
        'sl':r'\b(?:prosim|količina|cena|vzorec|material|preverimo|hvala)\b|[čšž]'}
    if language in patterns and not re.search(patterns[language],draft,re.I):issue('wrong_customer_language')
    if language=='en' and len(re.findall(r'[\u4e00-\u9fff\u0e00-\u0e7f]',draft))>max(7,len(re.findall(r'[A-Za-z]',draft))/3):issue('wrong_customer_language')
    if draft.count('?')+draft.count('？')>3:issue('too_many_questions')
    courtesy=proposal.get('courtesy','')
    if courtesy and not _COURTESY.fullmatch(courtesy.strip(' .!。！')):issue('unsupported_courtesy',-1)
    return _result(problems)

def _result(problems):
    unique=[]
    for p in problems:
        if p not in unique:unique.append(p)
    return {'passed':not unique,'issues':[p['code'] for p in unique], 'findings':unique,'checked':CHECKS,
        'limitations':['Bounded actual-text entailment checks; open vocabulary and human sendability need independent review. Advisory audit cannot grant authority.']}
