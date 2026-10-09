// Fixtures simulate Agent output. The renderer and actions do not infer trade facts.
export const KEY = 'stc.synthetic-inquiry-card.v1';
export const CASES = {
  development: {
    title: '定制开发 · 已有资料', customer: 'Avery · Northline Studio',
    country: '挪威（虚构）', email: 'avery@northline.example',
    product: 'weatherproof cycling jacket', quantity: null,
    inquiry: 'Hello, we want to develop a weatherproof cycling jacket using our own design. Our design notes are attached. What is your usual MOQ? We have not settled the first production quantity yet.',
    source: 'design-notes.txt',
    sourceText: 'SYNTHETIC DESIGN NOTES\nCustom cycling jacket; relaxed cut; hood and reflective trim. Waterproofness remains a target, not a verified material result.',
    company: '虚构授权条件：可评估定制骑行夹克；常规 MOQ 基准 240 pcs，未授权 per style / per color。没有本项目价格或性能承诺。',
    nextUnread: '先看客户已给的设计资料；无需等待数量确认才能开始评估。',
    nextRead: '评估设计和可用材料路线，再准备有条件的初步核价。',
    opening: 'We can review your custom cycling jacket project. Our usual MOQ baseline is 240 pcs; the style and color allocation needs project review.',
    requestQuantity: true,
  },
  known: {
    title: '数量已知 · 不重复询问', customer: 'Morgan · Waypoint Workshop',
    country: '芬兰（虚构）', email: 'morgan@waypoint.example',
    product: 'commuter vest', quantity: 480,
    inquiry: 'Hello, we are considering 480 commuter vests in total, split across two colors. The attached sketch shows our design. Please explain how you would start.',
    source: 'vest-sketch-notes.txt',
    sourceText: 'SYNTHETIC SKETCH NOTES\nTwo-color commuter vest with zipped pockets. The 480 pcs is a total estimate, not a confirmed order. No requested certification.',
    company: '虚构授权条件：可评估通勤背心类别。480 pcs 是客户预计总量，不是已确认订单；未授权价格或量产日期。',
    nextUnread: '先看现有款式资料，再评估材料和工艺；不要再次问已知总量。',
    nextRead: '根据资料评估材料和工艺，准备有条件的初步核价。',
    opening: 'We can review your commuter vest design and the current estimated total of {quantity} pcs across two colors.',
    requestQuantity: false,
  },
  protection: {
    title: '防护目标 · 保留能力边界', customer: 'Riley · Summit Field Lab',
    country: '荷兰（虚构）', email: 'riley@summitfield.example',
    product: 'winter workwear', quantity: null,
    inquiry: 'Hello, we are exploring durable winter workwear for electrical maintenance. We have attached concept notes. Could you review the concept and explain the next step?',
    source: 'concept-notes.txt',
    sourceText: 'SYNTHETIC CONCEPT NOTES\nWinter comfort and durability are desired. Electrical protection performance and the applicable testing basis are not specified.',
    company: '虚构授权条件：可评估工装概念。没有电气防护或认证能力授权；防护性能需要先核实。',
    nextUnread: '先看概念资料，再确认是否涉及电气防护和相关测试要求。',
    nextRead: '先确认防护用途与测试依据，再做技术可行性核实。',
    opening: 'We can review your winter workwear concept. Electrical protection performance would need technical verification before any commitment.',
    requestQuantity: false,
  },
};

export function createState() {
  return {schema: 1, revision: 0, selected: 'development', cards: Object.fromEntries(
    Object.entries(CASES).map(([id, f]) => [id, {quantity: f.quantity, sourceRead: false,
      contextRevision: 0, draft: '', draftRevision: 0, draftContext: null,
      approval: null, rejected: false, history: []}]))};
}

export function validateState(s) {
  const integer = n => Number.isSafeInteger(n) && n >= 0;
  if (!s || s.schema !== 1 || !integer(s.revision) || !Object.hasOwn(CASES, s.selected) || !s.cards)
    throw Error('演示存储格式无效。');
  for (const id of Object.keys(CASES)) {
    const c = s.cards[id];
    if (!c || (c.quantity !== null && (!integer(c.quantity) || c.quantity < 1 || c.quantity > 999999)) ||
        typeof c.sourceRead !== 'boolean' || !integer(c.contextRevision) || !integer(c.draftRevision) ||
        typeof c.draft !== 'string' || c.draft.length > 8000 ||
        (c.draftContext !== null && !integer(c.draftContext)) || typeof c.rejected !== 'boolean' ||
        !Array.isArray(c.history) || c.history.length > 30 ||
        !c.history.every(x => typeof x === 'string' && x.length <= 200)) throw Error('演示卡片存储无效。');
    if (c.approval !== null && (!c.draft.trim() || c.rejected ||
        c.draftContext !== c.contextRevision || c.approval.draftRevision !== c.draftRevision ||
        c.approval.contextRevision !== c.contextRevision)) throw Error('批准版本与草稿不一致。');
  }
  return s;
}

export function fixtureDraft(id, c) {
  const f = CASES[id];
  const parts = ['Hello,', 'Thank you for your inquiry.', f.opening.replace('{quantity}', String(c.quantity))];
  parts.push(c.sourceRead ? 'We will assess the design and material route based on your notes before preparing conditional preliminary costing.' :
    'We will first review the design notes you have provided, then assess the design and material route.');
  if (id === 'protection') {
    parts[parts.length - 1] = c.sourceRead ?
      'Could you clarify whether electrical protection is required and, if so, the applicable testing basis? We can then check technical feasibility.' :
      'We will first review your concept notes, then clarify the protective use and testing basis before checking technical feasibility.';
  } else if (f.requestQuantity && c.quantity === null) {
    parts.push('What is your estimated quantity for the first production run?');
  } else if (f.requestQuantity) {
    parts.push(`We will use your estimated total of ${c.quantity} pcs for the preliminary costing review; it is not a confirmed order.`);
  }
  parts.push('Best regards,\nDemo Team');
  return parts.join('\n\n');
}

export function cardView(s) {
  validateState(s);
  const id = s.selected, c = s.cards[id], f = CASES[id];
  const stale = !!c.draft && c.draftContext !== c.contextRevision;
  const status = c.approval ? '已模拟批准 · 未发送' : c.rejected ? '已退回 · 草稿保留' :
    stale ? '上下文已变 · 需重新准备' : c.draft ? '草稿待人工审核' : c.sourceRead ? '可开始内部评估' : '先审阅已有资料';
  const blockers = [c.sourceRead ? '正式报价仍需材料路线和成本核实；初步评估可继续。' :
    '设计资料尚未审阅：阻止正式报价，不阻止当前首回复。'];
  if (id === 'protection') blockers.push('没有防护性能或认证授权：不得确认相应能力。');
  return {type: 'InquiryCard', id, customer: {name: f.customer, country: f.country, email: f.email},
    status, blockers, next_action: c.sourceRead ? f.nextRead : f.nextUnread,
    quantity: c.quantity, quantity_purpose: '预计首批总量，不代表已确认订单',
    source_state: c.sourceRead ? '已显式模拟审阅（纯文本）' : '已提供，未审阅',
    draft: c.draft, stale, can_approve: !!c.draft.trim() && !stale && !c.rejected && !c.approval,
    actions: ['REVIEW_SOURCE', 'SET_QUANTITY', 'PREPARE_DRAFT', 'EDIT_DRAFT', 'REJECT_DRAFT', 'APPROVE_DRAFT']};
}

export function applyAction(previous, action) {
  validateState(previous);
  if (!action || action.expected_revision !== previous.revision) throw Error('状态已更新，请查看最新卡片后再操作。');
  const s = structuredClone(previous);
  if (action.type === 'SELECT_CASE') {
    if (!Object.hasOwn(CASES, action.case_id)) throw Error('未知演示案例。');
    s.selected = action.case_id;
  } else {
    if (action.case_id !== s.selected || !Object.hasOwn(CASES, action.case_id)) throw Error('卡片目标不匹配。');
    const c = s.cards[action.case_id];
    let event = '';
    const contextChange = () => {c.contextRevision++; c.approval = null; c.rejected = false;};
    switch (action.type) {
      case 'REVIEW_SOURCE':
        if (action.confirmed !== true) throw Error('需要明确确认已模拟审阅资料。');
        if (c.sourceRead) throw Error('资料已模拟审阅。');
        c.sourceRead = true; contextChange(); event = '已显式模拟审阅资料'; break;
      case 'SET_QUANTITY':
        if (!Number.isSafeInteger(action.value) || action.value < 1 || action.value > 999999) throw Error('数量应为 1–999999 的整数。');
        if (c.quantity === action.value) throw Error('数量未改变。');
        c.quantity = action.value; contextChange(); event = `模拟首批预计总量更新为 ${action.value} pcs`; break;
      case 'PREPARE_DRAFT':
        c.draft = fixtureDraft(action.case_id, c); c.draftRevision++; c.draftContext = c.contextRevision;
        c.approval = null; c.rejected = false; event = '已准备模拟草稿（没有模型调用）'; break;
      case 'EDIT_DRAFT':
        if (!c.draft || c.draftContext !== c.contextRevision) throw Error('请先基于当前上下文准备草稿。');
        if (typeof action.value !== 'string' || !action.value.trim() || action.value.length > 8000) throw Error('草稿应为 1–8000 字符的非空文本。');
        c.draft = action.value; c.draftRevision++; c.approval = null; c.rejected = false;
        event = '模拟草稿已修改，旧批准失效'; break;
      case 'REJECT_DRAFT':
        if (!c.draft) throw Error('没有可退回的草稿。');
        c.rejected = true; c.approval = null; event = '草稿已模拟退回，事实和文字均保留'; break;
      case 'APPROVE_DRAFT':
        if (action.reviewed !== true || !cardView(s).can_approve) throw Error('必须审阅当前版本，且草稿不能过期或已退回。');
        c.approval = {draftRevision: c.draftRevision, contextRevision: c.contextRevision};
        event = '仅批准当前模拟版本，未发送'; break;
      default: throw Error('不允许此操作。');
    }
    c.history = [...c.history, event].slice(-30);
  }
  s.revision++;
  return validateState(s);
}

export function readStorage(storage) {
  const raw = storage.getItem(KEY);
  return raw === null ? createState() : validateState(JSON.parse(raw));
}

export function persistAction(storage, state, action) {
  // Re-read before writing: do not silently overwrite a newer tab's state.
  const current = readStorage(storage);
  if (current.revision !== state.revision) throw Error('另一标签页已更新状态，请刷新后再操作。');
  const next = applyAction(state, action);
  storage.setItem(KEY, JSON.stringify(next));
  return next;
}
