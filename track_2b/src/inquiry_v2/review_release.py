"""Release for HUMAN review, not a natural-language safety certificate.

Exact integrity and narrow, positive contradictions block approval. Legacy
language heuristics and model audit remain advisory. Absence of a flag proves
neither semantic equivalence nor sendability.
"""
import re
from .message_gates import validate as strict_validate, verification_intent
from .understand import _cue_polarity, QTY_RE, PRODUCT_RE, canonical_product, _number

VERSION = 'human-review-1'
HARD_CODES = {
    'immutable_plan_binding_changed', 'invalid_message_slots', 'invalid_slot_binding',
    'repeated_content_binding', 'unsupported_amount_or_currency', 'unsupported_number',
    'company_payment_polarity_changed', 'moq_basis_expanded', 'line_quantity_mismatch',
    'line_product_mismatch', 'quantity_product_mismatch', 'quantity_purpose_changed'
}
LABELS = {
    'unsupported_courtesy': '致谢措辞可调整；不影响授权。',
    'condition_omitted': '核对适用条件是否完整表达，允许自然改写。',
    'unit_or_basis_changed': '核对数字的单位与适用范围。',
    'approved_question_omitted': '核对是否实际问了批准的问题；ID 绑定不代表内容已出现。',
    'required_answer_omitted': '核对已知答案是否实际表达。',
    'parallel_condition_lost': '核对并行动作仍有条件且可撤回。',
    'advance_object_lost': '核对下一步是否足够具体。',
    'advance_operation_lost': '核对原定下一步是否保留。',
    'unsupported_commitment': '核对这是核查意图还是对外承诺。',
    'unsupported_company_claim': '公司表述需要核对授权与适用边界。',
    'internal_operator_leakage': '改为客户语言，去掉内部表述。',
    'inquiry_or_interest_stated_as_order': '客户询盘/意向不能写成已确认订单。',
    'external_named_route_not_in_source': '核对外部参考的路线与运输方式。',
}

def proposal_text(proposal):
    if not proposal:
        return ''
    return '\n\n'.join(x for x in [proposal.get('courtesy','')] +
                       [s.get('text','') for s in proposal.get('slots',[])] if x)

def _positive(text, match):
    return _cue_polarity(text, match.start(), match.end()) == 'positive'

def evaluate(plan, proposal, *, audit=None):
    doc = plan.document
    draft = proposal_text(proposal)
    blockers, warnings = [], []
    if not proposal:
        return {'version':VERSION,'passed':False,'issues':['missing_draft'],
                'findings':[],'blockers':[],'warnings':[], 'checked':['draft_availability'],
                'certifies_safety':False,'needs_human_approval':True}
    strict = strict_validate(plan, proposal)
    segments = []
    cursor = 0
    for slot, value in [(-1,proposal.get('courtesy',''))] + list(enumerate(s.get('text','') for s in proposal.get('slots',[]))):
        if value:
            start = draft.find(value, cursor)
            segments.append((slot, value, start))
            cursor = start + len(value)

    def add(code, slot, *, hard=False, phrase=None, message=None, evidence=None):
        seg = next((s for s in segments if s[0]==slot), None)
        if seg:
            value, start = seg[1],seg[2]
            phrase = phrase if phrase and phrase in value else value
            begin = start + value.find(phrase)
            end = begin + len(phrase)
        else:
            phrase,begin,end = '',len(draft),len(draft)
        prefix = code.split(':')[0]
        entry = {'code':code,'slot':slot,'layer':'plan' if slot is None else 'renderer',
                 'message':message or LABELS.get(prefix,'请对照来源确认这段表述。'),
                 'phrase':phrase,'span':[begin,end],
                 'utf16_span':[len(draft[:begin].encode('utf-16-le'))//2,len(draft[:end].encode('utf-16-le'))//2],
                 'evidence':evidence or [],'severity':'blocker' if hard else 'advisory'}
        target = blockers if hard else warnings
        if not any(v['code']==code and v['span']==entry['span'] for v in target):
            target.append(entry)

    for f in strict.get('findings',[]):
        code, slot = f['code'],f.get('slot')
        prefix = code.split(':')[0]
        hard = (prefix in HARD_CODES or prefix.startswith(('invalid_fact_provenance','upstream_','required_item_missing')))
        # Semantic wording heuristics are not promoted merely because an old
        # detector called them mandatory. Specific positive proof is below.
        add(code,slot,hard=hard)

    company = doc['allowed_company_claims']
    customer = doc['allowed_customer_facts']
    approved_fields={q['field'] for q in doc['approved_questions']}
    proof = [f['quote'] for f in company]
    has = lambda term: any(term in f['key'] for f in company)
    for slot,value,_ in segments:
        # All customer-facing text, including courtesy, is inspected. A greeting
        # slot is not a bypass for commercial assertions.
        if slot == -1:
            from .reply_generation import _numeric_tokens
            allowed_numbers={n for f in company+customer+doc['allowed_external_references'] for n in _numeric_tokens(str(f['value']))}
            if any(n not in allowed_numbers for n in _numeric_tokens(value)):
                add('unsupported_courtesy_number',slot,hard=True,
                    message='致谢段中的业务数字也必须有来源，不能绕过 value 检查。')
        for clause in re.split(r'(?<=[.!?。！？])\s+|[;；\n]',value):
            if not clause.strip():
                continue
            from .message_gates import question_intent
            if question_intent(clause):
                patterns={'delivery_destination':r'(?:delivery|shipping|postal|pickup)\s+address|ship.to\s+address|收货地址|direcci[oó]n',
                          'quantity':r'how\s+many|what\s+(?:is\s+the\s+)?quantity|需要多少|数量是多少|cu[aá]nt[oa]s?'}
                for field,pattern in patterns.items():
                    if field not in approved_fields and re.search(pattern,clause,re.I):
                        add('unapproved_question:'+field,slot,hard=True,phrase=clause,
                            message='这项明确的问题变量不在批准的 question plan 中。')
            order = re.search(r'\b(?:the|your|this)\s+(?:\d[\d,]*(?:[ -](?:piece|unit))?\s+)?(?:(?:bulk|production)\s+)?order\b|(?:本次|您的|这笔)(?:生产)?订单',clause,re.I)
            order_variable=bool(order and re.match(r'\s+(?:quantity|requirements?|inquiry|plan)\b',clause[order.end():],re.I))
            conditional_order=bool(order and re.search(r'\b(?:if|once|when)\s+(?:the|your|this)\s+order\s+(?:is\s+)?confirmed\b',clause,re.I))
            if order and _positive(clause,order) and not order_variable and not conditional_order:
                add('unconfirmed_order_claim',slot,hard=True,phrase=clause,
                    message='询盘没有订单确认授权；请恢复询盘/计划数量表述。',
                    evidence=['First-reply plan forbids interest becoming a confirmed order.'])
            transaction = re.search(r'\b(?:we|I)\s+confirm\b.{0,85}\bpayment\b.{0,45}\b(?:will\s+be|is|has\s+been)\s+(?:handled|settled|confirmed|approved)|\b(?:this|your|the)\s+payment\s+(?:is|has\s+been)\s+(?:confirmed|approved)|(?:本次|这笔)付款.{0,12}(?:已确认|已批准)',clause,re.I)
            if transaction and _positive(clause,transaction) and not verification_intent(clause):
                add('transaction_authorization_missing',slot,hard=True,phrase=clause,
                    message='公司可接受付款方式，不等于这笔交易已确认付款条件。',evidence=proof)
            direct = re.search(r'^\s*(?:we|I)\s+(?:will|shall)\s+(?:ship|dispatch|deliver|produce|manufacture|pay|guarantee|release|approve)\b|^\s*我们(?:将|会)(?:发货|投产|付款|保证|批准)',clause,re.I)
            if direct and _positive(clause,direct):
                add('execution_authorization_missing',slot,hard=True,phrase=clause,
                    message='此 plan 仅授权可撤回的内部动作，没有执行/商业批准权限。')
            for topic,pattern in [('moq',r'\bour\s+(?:standard\s+)?(?:MOQ|minimum\s+order)\b.{0,35}\b(?:is|are)\b'),
                                  ('lead_time',r'\bour\s+(?:normal\s+|production\s+)?lead\s*time\s+is\b'),
                                  ('certification',r'\bwe\s+are\s+(?:certified|accredited)\b'),
                                  ('stock',r'\bwe\s+have\b.{0,30}\bin\s+stock\b'),
                                  ('capability',r'\bwe\s+(?:can\s+)?(?:manufacture|produce|make)\b|我们可以生产'),
                                  ('payment',r'\bwe\s+(?:can\s+)?accept\s+(?:an?\s+)?(?:L/C|letter\s+of\s+credit|T/T|bank\s+transfer)\b|我们(?:接受|支持)(?:信用证|电汇)')]:
                assertion = re.search(pattern,clause,re.I)
                if assertion and _positive(clause,assertion) and not has(topic) and not verification_intent(clause):
                    add('company_authorization_missing:'+topic,slot,hard=True,phrase=clause,
                        message='没有适用的公司授权来源支持这项陈述。')
                if assertion and _positive(clause,assertion) and has(topic) and topic in ('moq','lead_time') and not verification_intent(clause):
                    from .reply_generation import _numeric_tokens
                    authorized_numbers={n for f in company if topic in f['key'] for n in _numeric_tokens(str(f['value']))}
                    stated=re.match(r'\s*(?:(?:about|approximately)\s+)?\d[\d,]*(?:\.\d+)?',clause[assertion.end():],re.I)
                    if stated and any(n not in authorized_numbers for n in _numeric_tokens(stated.group())):
                        add('company_value_authorization_mismatch:'+topic,slot,hard=True,phrase=clause,
                            message='这项明确的公司条件数字与授权来源不符。',evidence=proof)
            for fact in company:
                from .reply_generation import _numeric_tokens
                if isinstance(fact['value'],(int,float)) and fact['value'] in _numeric_tokens(clause):
                    if fact.get('unit')=='days' and re.search(r'\b'+re.escape(str(fact['value']))+r'\s*(?:weeks?|months?)\b|'+re.escape(str(fact['value']))+r'\s*(?:周|个月)',clause,re.I):
                        add('explicit_unit_conflict',slot,hard=True,phrase=clause,
                            message='来源的 days 被明确改成 weeks/months。',evidence=[fact['quote']])
                    if fact.get('conditions') and re.search(r'\b(?:any|all)\s+(?:materials?|routes?|markets?)\b|所有(?:材料|路线|市场)|任意(?:材料|路线|市场)',clause,re.I):
                        add('explicit_scope_expansion',slot,hard=True,phrase=clause,
                            message='有限适用条件被明确扩大为所有材料/路线/市场。',evidence=[fact['quote']])
                if 'moq' not in fact['key'] or 'style' not in str(fact.get('unit')):
                    continue
                basis = re.search(r'(?:颜色|材质|面料)(?:和|与|及)(?:颜色|材质|面料).{0,16}(?:起订量|最低数量).{0,8}(?:为|是)\s*[\d,]+|(?:起订量|MOQ).{0,12}(?:每色|每种材料)|\b(?:MOQ|minimum)\b.{0,25}\bper\s+(?:colou?r|material)\b',clause,re.I)
                if basis and _positive(clause,basis):
                    add('company_basis_conflict',slot,hard=True,phrase=clause,
                        message='来源授权的是每款 minimum，不能扩大为颜色/材料 minimum。',evidence=[fact['quote']])
            unread = [s for s in doc['source_state'] if s['state']!='read']
            read_claim = re.search(r'\b(?:we|I)\s+(?:have\s+)?(?:already\s+)?(?:read|reviewed)\b.{0,35}\b(?:attached|attachment|brief|drawing)\b|(?:已经|已)(?:阅读|审阅|看过).{0,12}(?:附件|图纸|资料)',clause,re.I)
            if unread and read_claim and _positive(clause,read_claim):
                add('source_state_conflict',slot,hard=True,phrase=clause,
                    message='现有资料尚未读取，不能声称已阅读。',evidence=[s['state'] for s in unread])
            absent_claim=re.search(r'\byou\s+(?:have\s+)?not\s+provided\s+(?:the\s+)?(?:attached\s+)?(?:brief|drawing|material|design)|\bno\s+(?:attachment|drawing)\b|(?:您|你)(?:没有|未)提供(?:附件|图纸|资料)',clause,re.I)
            if unread and absent_claim:
                add('source_state_fabricated_absence',slot,hard=True,phrase=clause,
                    message='已提及的资料尚未读取，不能改写为客户未提供。',evidence=[s['state'] for s in unread])
            # An explicit count+product noun can be checked; an inferred nearest
            # noun in a merged paragraph stays advisory.
            if not re.search(r'MOQ|minimum|起订|最低',clause,re.I):
                for count in QTY_RE.finditer(clause):
                    product=PRODUCT_RE.search(count.group())
                    if not product or count.group('second'):continue
                    name=canonical_product(product.group())
                    value_number=_number(count.group('first'))
                    line_ids={l['id'] for l in doc['line_item_scope'] if canonical_product(l['product_ref'])==name}
                    if line_ids and not any(f['key']=='quantity' and f['value']==value_number and line_ids.intersection(f['line_ids']) for f in customer):
                        add('explicit_quantity_ownership_conflict',slot,hard=True,phrase=count.group(),
                            message='这个明确的数量/产品组合与来源中的 line item 不符。',
                            evidence=[f['quote'] for f in customer if f['key']=='quantity'])
            # The literal value can be mechanically preserved even though its
            # full semantic applicability may still require human verification.
        for item in doc['required_answers']:
            if item['id'] not in next((s['item_ids'] for i,s in enumerate(proposal['slots']) if i==slot),[]):
                continue
            for fact in item['facts']:
                if isinstance(fact['value'],(int,float)) and not isinstance(fact['value'],bool):
                    from .reply_generation import _numeric_tokens
                    if fact['value'] not in _numeric_tokens(value):
                        add('required_value_missing:'+item['id'],slot,hard=True,
                            message='必须回答的已授权数值完全缺失。',evidence=[fact['quote']])
                elif 'payment' in fact['key']:
                    from .message_gates import _payment_present
                    if not _payment_present(fact,value):
                        add('required_value_missing:'+item['id'],slot,hard=True,
                            message='必须回答的已授权付款方式完全缺失。',evidence=[fact['quote']])
        from .reply_generation import _COURTESY
        if slot>=0 and _COURTESY.fullmatch(value.strip(' .!。！')):
            add('required_business_item_absent',slot,hard=True,
                message='业务 slot 只剩致谢，required 内容完全缺失；这不是措辞风格限制。')
    # Audit cannot remove blockers, edit provenance or veto review access.
    if audit:
        # Only each finding's own check is bound to its exact quotation.
        # Unlocated/global codes remain technical, not fabricated phrase flags.
        for f in audit.get('findings',[]):
            phrase = f.get('text') or f.get('quote')
            code='semantic_'+f.get('check','expression')
            for slot,value,_ in segments:
                if phrase and phrase in value:
                    add('audit:'+code,slot,phrase=phrase,message='模型建议复核此表达；它不是事实或授权来源。')
    findings = blockers
    return {'version':VERSION,'passed':not blockers,'issues':[v['code'] for v in blockers],
            'findings':findings,'blockers':blockers,'warnings':warnings,
            'checked':['plan_integrity','source_proof','narrow_explicit_contradictions'],
            'certifies_safety':False,'needs_human_approval':True,
            'review_state':'needs_correction' if blockers else 'pending_human_approval',
            'limitations':['No flag does not establish semantic correctness. Every draft needs human approval.'],
            'strict_diagnostics':strict,'audit_issues_unlocated':(audit or {}).get('issues',[])}

def check_edited_text(plan, draft):
    """A human text edit never supplies authority or mutates plan content."""
    if not isinstance(draft,str) or not draft.strip() or len(draft)>20000:
        raise ValueError('a nonempty bounded draft is required')
    doc = plan.document
    ids = [s['item_ids'][0] for s in doc['ordered_message_slots'] if s['required']]
    proposal = {'plan_hash':plan.hash,'courtesy':'','slots':[{'item_ids':ids,'text':draft.strip()}]}
    policy = evaluate(plan,proposal)
    # Detect actual explicit question functions, not punctuation counts alone.
    approved = {q['field'] for q in doc['approved_questions']}
    from .reply_generation import _EXTRA_QUESTION_FIELDS
    from .message_gates import question_intent
    for clause in re.split(r'(?<=[?？])\s*|\n',draft):
        if not question_intent(clause):
            continue
        for field,pattern in _EXTRA_QUESTION_FIELDS.items():
            if field not in approved and re.search(pattern,clause,re.I):
                start=draft.find(clause)
                policy['blockers'].append({'code':'unapproved_question:'+field,'slot':0,'layer':'renderer',
                    'message':'这个问题不在当前批准的 question plan 中；请纠正问题或明确修改 plan。',
                    'phrase':clause,'span':[start,start+len(clause)],'utf16_span':[len(draft[:start].encode('utf-16-le'))//2,len(draft[:start+len(clause)].encode('utf-16-le'))//2],
                    'severity':'blocker','evidence':[]})
    policy['passed']=not policy['blockers']
    policy['issues']=[v['code'] for v in policy['blockers']]
    policy['review_state']='pending_human_approval' if policy['passed'] else 'needs_correction'
    return proposal,policy
