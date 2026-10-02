# -*- coding: utf-8 -*-
"""v3 deterministic fact extraction — the load-bearing layer.

Contract (ITERATE decision, section 2):
  Numbers, prices, quantities, dates, ratios, Incoterms and SKUs are parsed
  deterministically. The LLM may SELECT which candidate span plays which role;
  it may never be the source of a value.

Every candidate carries:
  id          stable handle (f01, f02, ...) the LLM refers to
  value       literal text copied from the email, never recomputed
  source_span exact substring + offsets
  type        amount | qty | date | duration | relative | sku | doc_id | ratio | incoterm ...
  status      supported | inferred | not_stated

Why candidates rather than final values: the benchmark's hard cases need
SELECTION (con03: pick "Dec 28" over "Dec 23 / Jan 5"; sim02: pick 5,500 over
the negated 5,000; neg02: pick "45 days" over "30 days"). Selection is
semantic — that is the LLM's job. Value production is not.

v2 (prototype/track_2b/src/parsers.py) is retained unmodified for reproducibility.
"""
import re

FIELDS = ["buyer", "products", "incoterm", "payment_terms", "deadline", "amounts"]

MONTHS = {"jan": "1", "feb": "2", "mar": "3", "apr": "4", "may": "5", "jun": "6",
          "jul": "7", "aug": "8", "sep": "9", "sept": "9", "oct": "10", "nov": "11", "dec": "12"}
MONTH_CANON = {"jan": "January", "feb": "February", "mar": "March", "apr": "April",
               "may": "May", "jun": "June", "jul": "July", "aug": "August",
               "sep": "September", "sept": "September", "oct": "October",
               "nov": "November", "dec": "December",
               "january": "January", "february": "February", "march": "March",
               "april": "April", "june": "June", "july": "July", "august": "August",
               "september": "September", "october": "October", "november": "November",
               "december": "December"}
# abbreviations must be tried before full names so "Dec" does not shadow "December"
MONTH_RE = "|".join(sorted(MONTH_CANON, key=len, reverse=True))

CURRENCIES = r"USD|EUR|GBP|CNY|RMB|HKD|JPY|CHF|AUD|CAD|SGD|€|£|\$|¥"
CJK_CURRENCY = r"美元|美金|欧元|英镑|人民币|港币|日元|瑞郎"
CUR_MAP = {"美元": "USD", "美金": "USD", "欧元": "EUR", "英镑": "GBP",
           "人民币": "CNY", "港币": "HKD", "日元": "JPY", "瑞郎": "CHF"}

# ------------------------------------------------------------------ patterns

# amount: "USD 2.10", "USD 2.00/pc", "$45", "USD 4,200", "3.20 美元"
AMOUNT_RE = re.compile(
    r"(?P<cur>" + CURRENCIES + r")\s*(?P<n1>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*/\s*(?P<u1>[A-Za-z]{1,6}|[一-鿿]{1,3}))?"
    r"|(?P<n2>\d[\d,]*(?:\.\d+)?)\s*(?P<cur2>" + CJK_CURRENCY + r")"
    # bare money with a 2-decimal tail and a thousands separator or >=3 decimals:
    # "4,417.00", "12,860.50". Weak but needed for "our PO says 4,417.00".
    r"|(?P<n4>\d[\d,]*\.\d{2}(?!\d))",
    re.I)

QTY_RE = re.compile(
    r"(?P<num>\d[\d,]*)\s*(?P<unit>pcs|pieces|units?|sets?|pc|piece|件|个|只|套|条|箱)(?![A-Za-z])", re.I)
QTY_BARE_RE = re.compile(
    r"(?P<num>\d[\d,]*)\s*(?P<unit>kg|kgs|carton|cartons|ctns?|box|boxes)(?![A-Za-z])", re.I)
# multiplication-style listing: "QY-11 x 800", "TS-101 x 2,000", "HD-330 × 1,500"
QTY_MUL_RE = re.compile(
    r"[x×@*]\s*(\d{1,3}(?:,\d{3})*|\d+)(?!\d)")

PCT_RE = re.compile(r"(?P<pct>\d+(?:\.\d+)?)\s*(?:%|％|percent|pct)")
RATIO_RE = re.compile(r"(?P<ratio>\d+\s*[:：]\s*\d+)")
CN_DISCOUNT_RE = re.compile(r"(八折|九折|七折|六折|五折|折让|打折)")

# Document identifiers. In this domain PO/PI/INV/SO numbers are routinely the
# product-line identifier (miss02, con04, multi04, noi01 all expect them as SKU),
# so they are identifier candidates rather than noise.
DOCID_RE = re.compile(
    r"\b(?:PO|PI|CI|INV|SO|INVOICE|QUOTE|OL)[- ]?(?:No\.?[- ]?)?[0-9][A-Za-z0-9\-]*"
    r"|(?:订单号|发票号|订单编号|订单明细|订单|装箱单|发票|明细)\s*[:：]?\s*"
    r"[A-Za-z]{0,4}[- ]?[0-9][A-Za-z0-9\-]*", re.I)
# A CJK label ("订单明细", "装箱单") is CONTEXT, not part of the identifier. Since
# \w matches CJK, a naive [\w\-]+ swallows the label into the value and the reply
# then quotes "订单明细 OL-3301" as a style code. Strip the label for the value.
DOCID_CJK_LABEL_RE = re.compile(
    r"^\s*(?:订单号|发票号|订单编号|订单明细|订单|装箱单|发票|明细)\s*[:：]?\s*")
# SHIPPING EQUIPMENT is not merchandise. A container number matches the SKU shape
# (4 letters + 7 digits, same as "TS-002" padded) and would otherwise claim the
# line's quantity ahead of the real style code. Anchored on the ISO 6346 owner
# code prefix so it cannot swallow a genuine product code.
SHIPPING_EQUIP_RE = re.compile(
    r"\s*(?:container|ctr|seaworth|seal)\b[^.;:!?]{0,24}?$"
    r"|\s*(?:CLHU|CMAU|TGHU|MSKU|CAIU|FSCU|FCIU|TCNU|TRHU|OOLU|EGHU|SUDU)[- ]?\d{5,8}\b",
    re.I)
# An "OL-nnnn"/"订单明细 OL-nnnn" token is an ORDER number, not a style code: the
# goods are named separately ("款号 SC-208"). Left as a plain sku it would claim
# the line's quantity ahead of the real style code.
# "quote 3,000 pcs" is the VERB "quote", not a QUOTE-number. Require the id to be
# glued to its prefix (PO-7701 / PO 7701) or be a real identifier shape.
DOCID_VERBALIAS_RE = re.compile(
    r"\b(?:QUOTE|INVOICE|INV|PO|PI|CI|SO)\s+(?:No\.?\s*)?\d[\w\-]*", re.I)
SKU_RE = re.compile(
    r"\b(?=[A-Z0-9\-]{4,12}(?![A-Za-z0-9]))(?=[A-Z0-9\-]*\d)[A-Z]{1,4}-?\d{2,6}[A-Z0-9\-]*\b")
SKU_SPACED_RE = re.compile(r"\b(?:CTN|CARTON|BOX|LOT|BATCH)[\s-]\d[\w\-]*\b", re.I)

INCOTERM_RE = re.compile(
    r"\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b"
    r"|(?P<zh>工厂交货|货交承运人|成本加运费|成本加保险费加运费|运费付至|目的地交货|完税后交货)")
INCOTERM_ZH_MAP = {"工厂交货": "EXW", "货交承运人": "FCA", "成本加运费": "CFR",
                   "成本加保险费加运费": "CIF", "运费付至": "CPT", "目的地交货": "DAP",
                   "完税后交货": "DDP"}

# Ranges first, then single dates, then bare months.
RANGE_RE = re.compile(
    rf"\b(?:{MONTH_RE})\.?\s+\d{{1,2}}\s*(?:-|–|—|to|至|到)\s*\d{{1,2}}\b", re.I)
DATE_PATS = [
    re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?"),
    re.compile(r"\d{4}-\d{1,2}-\d{1,2}"),
    re.compile(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?"),
    re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]?"),
    re.compile(rf"\b(?:{MONTH_RE})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b", re.I),
    re.compile(rf"\b(?:{MONTH_RE})\.?\s+\d{{4}}\b", re.I),
]
BARE_MONTH_RE = re.compile(rf"\b(?:{MONTH_RE})\b(?!\s*\d)", re.I)
CJK_BARE_MONTH_RE = re.compile(r"(\d{1,2})\s*月(?!\s*\d)")
# a bare month name qualified by a time word ("anytime in December", "sometime in March")
# is a real deadline; an unqualified stray month word is weaker but still a candidate
QUALIFIED_MONTH_RE = re.compile(
    rf"\b(?:anytime|sometime|some\s+time|by|before|in|during|within|until|no\s+rush\s+(?:on|in)?)\s+"
    rf"(?:{MONTH_RE})\b(?!\s*\d)", re.I)

RELATIVE_RE = re.compile(
    r"\b(today|tomorrow|yesterday|tonight|this\s+(?:week|month|morning|afternoon)"
    r"|next\s+(?:week|month|year)|ASAP|as soon as possible|soon|shortly|before\s+end\s+of\s+(?:day|week)"
    r"|EOD|COB|end\s+of\s+(?:day|week|month)|no\s+rush|anytime|whenever"
    r"|尽快|马上|今天|明天|后天|昨天|下周|下个月|近期|最近|立刻|立即|不急|随时|当天|今日|明日)",
    re.I)

DURATION_RE = re.compile(
    r"\d+(?:\s*[-–]\s*\d+)?\s*(?:个?工作日|工作天|天|周|个月|年|days?|weeks?|months?|business\s+days?|working\s+days?)",
    re.I)

PAYMENT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*%\s*(?:T/?T\s*)?(?:deposit|定金|预付|订金|首付|预付款)"
    r"|(?:T/?T|电汇|信汇)\s*\d+(?:\.\d+)?\s*%\s*(?:定金|预付|订金)?"
    r"|(?:LC\s*(?:at\s*sight)?|L/C(?:\s*at\s*sight)?|即期信用证|COD|C/?O/?D|货到付款|D/P|D/A)"
    r"|\d+\s*(?:天|days?)\s*(?:账期|付款|T/?T|credit|net)"
    r"|payment\s+terms?\s*(?:is|are|:)?\s*[^\n.;]{0,50}"
    r"|余款[^，。；\n]{0,20}|余额[^，。；\n]{0,20}", re.I)

NEGATION_RE = re.compile(
    r"(?:\bnot\b|\bwithout\b|\bexcept\b|\bexclude[ds]?\b|\bunless\b|\bnothing\b"
    r"|(?<![A-Za-z])no(?![A-Za-z.])"          # bare "no", NOT "No." in "PI No. 1122"
    r"|不要|不需要|不含|不包括|不需|除外|无需|取消)", re.I)

# A negation that governs a VERB, not the quantity/price/date that follows it.
# "Do not send the PI yet for the 1,500 pcs order" and "No rush on the 3,300 pcs
# TS-444" both negate an action; the number is the object of a DIFFERENT verb.
VERB_NEGATION_RE = re.compile(
    r"\b(?:do\s+not|don'?t|does\s+not|doesn'?t|no)\s+"
    r"(?:rush|need|send|ship|want|require|order|book|apply|use|make|do|proceed|wait|confirm|accept)\b"
    r"|\bplease\s+do\s+not\b",
    re.I)

# A quantity that is a conditional/future figure is not the current commitment:
# "If approved, bulk will be 3,000 pcs" — the live ask is the 300 pcs sample.
CONDITIONAL_QTY_RE = re.compile(
    r"(if\s+(?:approved|ok|okay|accepted|confirmed)|should\s+(?:be\s+)?work"
    r"|bulk\s+will\s+be|will\s+be|would\s+be|next\s+time|future|后续|如果(?:批准|可以))", re.I)
# CONDITIONAL requires a real CONDITION, not merely the verb "would/will be".
# "Initial order would be around 300 pcs" is the customer's stated opening
# quantity — the order size is the SUBJECT of "would be". "If approved, bulk
# will be 3,000 pcs" is contingent on something else happening. Collapsing the
# two lost the only quantity in the email.
CONDITIONAL_CONJ_RE = re.compile(
    r"\b(?:if|when|once|should|upon|assuming|provided|pending)\b"
    r"|如果|一旦|等(?:批准|确认)后", re.I)

# A summary figure beats a per-item figure: "SC-208 白/灰各 2,500 件，合计 5,000 件"
TOTAL_QTY_RE = re.compile(r"(合计|总共|共计|总额|总量|\btotal\b|\bcombined\b|\bin\s+total\b|\bsum\b)", re.I)

# A defect/damage count is not the ordered quantity: "roughly 40 pcs damaged"
DEFECT_QTY_RE = re.compile(
    r"(damaged|broken|defective|missing|spoiled|rejected|loose|cracked|scuffed"
    r"|损坏|破损|不良|破包|短装)", re.I)

# A PAST order is not this order: "we ordered 12,000 pcs last year (PO-...)".
# Without this the historical count binds to the nearest style code and the
# current ask is dropped from the reply.
HISTORICAL_QTY_RE = re.compile(
    r"(\s*(?:pcs|pieces|件)?\s*,?\s*"
    r"(?:last\s+(?:year|season|month|time)"
    r"|previously|in\s+(?:19|20)\d\d|back\s+in|历史|去年|以往|上次))", re.I)

CUSTOMER_ASSERTION_RE = re.compile(
    r"(\bplease\b|\bcould you\b|\bcan you\b|\bwould you\b|\bwe need\b|\bwe want\b"
    r"|\bwe'd like\b|\bour budget is\b|\bwe can only\b|\bwe think\b|\bwe assume\b"
    r"|\bis it still\b|\bis it possible\b|\bcorrect\?|\bright\?|\byour (?:last|previous) email said\b"
    r"|\byou (?:said|offered|promised)\b|\bmeet us at\b|\bif yes\b|\btell me\b|\bsend us\b"
    r"|\bfor the next\b|\bnext batch\b|请|能否|可否|麻烦|我们需|我们想|我们的预算|是否|对吗|可以吗|下一批|下次)",
    re.I)

OWN_COMMITMENT_RE = re.compile(
    r"(\bwe (?:agreed|have agreed|confirm|commit|will ship|will deliver|take|quote)\b"
    r"|\bour (?:price|list price|terms|policy|standard terms|offer)\b"
    r"|\bis confirmed\b|\bare confirmed\b|\bplease process\b|\bper attachments?\b"
    r"|已确认|我方确认|我司确认|我们确认|我方报价|请回复确认)", re.I)
# NOTE: in an INBOUND customer email the first person is the CUSTOMER. This regex
# therefore marks the CUSTOMER's own stance, not ours. It is kept only so the
# existing v3 selector contract stays byte-identical; the semantic layer
# (semantics.py) re-derives party from pronouns and never promotes these to a
# company commitment.

# ------------------------------------------------------------ qualifiers (added v4)

# Hedges and bounds attached to a value. "around 300 pcs" is not the same claim
# as "300 pcs": echoing one as the other fabricates precision the customer never
# offered. The hedge is part of the value, so it is parsed alongside it.
APPROX_RE = re.compile(
    r"\b(about|around|approx\.?|approximately|roughly|circa|close\s+to|in\s+the\s+region\s+of)\b"
    r"|大约|大概|约|左右|上下|差不多|将近|接近", re.I)
# postposed hedge: "300 pcs or so"
APPROX_POST_RE = re.compile(r"^\s*(?:or\s+so|or\s+thereabouts)|^[，,]\s*左右|左右", re.I)
MIN_RE = re.compile(r"\b(at\s+least|minimum|min\.?|no\s+less\s+than|not\s+less\s+than)\b|至少|最少|不低于", re.I)
MAX_RE = re.compile(r"\b(at\s+most|maximum|max\.?|no\s+more\s+than|up\s+to)\b|最多|不超过|以内|以下", re.I)
EXACT_RE = re.compile(r"\b(exactly|precisely)\b|正好|刚好|整", re.I)

# Delivery relations. "before Dec 20" and "Dec 20" are different promises; the
# relation is part of the claim.
RELATION_RE = re.compile(r"\b(before|not\s+later\s+than|no\s+later\s+than|on\s+or\s+before)\b"
                         r"|\b(by|until|till)\b"
                         r"|\b(after)\b"
                         r"|之前|以前|以前交货|前交货|截止|之后", re.I)
RELATION_MAP = {"not later than": "before", "no later than": "before", "on or before": "before",
                "before": "before", "by": "by", "until": "by", "till": "by", "after": "after",
                "之前": "before", "以前": "before", "前交货": "before", "截止": "by", "之后": "after"}

# ------------------------------------------------------- product common nouns (added v4)

# The v3 candidate set can only see IDENTIFIER SHAPES (SKU, PO/PI numbers). A
# merchandise line named with a common noun ("ski jackets") has no shape, so the
# product vanished from the store entirely. These are domain lexicons, not a list
# of phrases from any single email, and the acceptance suite exercises product
# names that never appear in the case that prompted them.
_GOODS_MOD = (r"ski|down|puffer|softshell|hard\s?shell|rain|winter|summer|baby|kids?|children'?s?|"
              r"men'?s?|women'?s?|ladies'?|unisex|yoga|running|hiking|outdoor|thermal|fleece|"
              r"padded|quilted|insulated|waterproof|windproof|camping|hiking|beach|kitchen|"
              r"cotton|canvas|leather|denim|polyester|nylon|knit|woven|plush|hooded|packable|"
              r"lightweight|heavy|cargo|fashion|casual|printed|solid|striped|plain|long\s?sleeve|"
              r"short\s?sleeve|sleeveless|zip|crew\s?neck|fleece-lined")
# longest-first within each cluster so "sleeping bag" wins over "bag"
_GOODS = (r"sleep\s?sacks?|sleeping\s?bags?|down\s?jackets?|puffer\s?jackets?|track\s?suits?|"
          r"t-?shirts?|polo\s?shirts?|sweat\s?shirts?|sleep\s?suits?|baby\s?sleep\s?sacks?|"
          r"jackets?|parkas?|anoraks?|coats?|fleeces?|hoodies?|sweaters?|jumpers?|cardigans?|"
          r"polos?|shirts?|tees?|blouses?|tops?|vests?|dresses?|skirts?|pants?|trousers?|shorts?|"
          r"joggers?|leggings?|jeans?|overalls?|rompers?|onesies?|bibs?|pyjamas?|pajamas?|"
          r"uniforms?|robes?|aprons?|coveralls?|socks?|gloves?|mittens?|beanies?|caps?|hats?|"
          r"scarves?|scarfs?|towels?|blankets?|quilts?|duvets?|pillows?|cushions?|mattresses?|"
          r"curtains?|rugs?|mats?|coasters?|bags?|totes?|backpacks?|pouches?|wallets?|belts?|"
          r"keychains?|lanyards?|straps?|cords?|ropes?|webbing|umbrellas?|toys?|tents?|tarps?")
PRODUCT_NAME_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<p>(?:(?:" + _GOODS_MOD + r")\s+){0,3}(?:" + _GOODS + r"))(?![A-Za-z0-9])",
    re.I)
_CJK_GOODS_MOD = r"婴儿|儿童|成人|男式|女式|加厚|防风|防水|抓绒|纯棉|加绒|夏季|冬季|长袖|短袖|连帽"
_CJK_GOODS = (r"婴儿睡袋|睡袋|冲锋衣|羽绒服|棉服|外套|夹克|卫衣|毛衫|连衣裙|瑜伽裤|工装裤|睡衣|围兜|哈衣|"
              r"裤子|裙子|袜子|手套|帽子|围巾|背包|手提袋|购物袋|束口袋|钥匙扣|挂绳|织带|窗帘|地毯|地垫|杯垫|"
              r"毛巾|毛毯|被子|枕头|靠垫|床垫|毛绒玩具|雨伞|制服|围裙|冲锋裤|T恤|Polo衫")
CJK_PRODUCT_NAME_RE = re.compile(
    r"(?P<p>(?:(?:" + _CJK_GOODS_MOD + r"){0,2})(?:" + _CJK_GOODS + r"))")
# A merchandise noun that is really described as packing/transport context is not
# a product line ("packed the cartons", "seal number", "container").
PRODUCT_NAME_BLOCK_RE = re.compile(
    r"(?:\b(?:container|carton|box|pallet|seal|shipping\s+mark|hs\s+code|fabric|lining|shell)\b"
    r"|箱子|纸箱|集装箱|封条|铅封|面料|里布)\s*$", re.I)


# ------------------------------------------------------------------- helpers

def _mk(email, start, end, kind, **extra):
    rec = {
        "value": email[start:end].strip(),
        "source_span": email[start:end],
        "span_start": start,
        "span_end": end,
        "type": kind,
        "status": "supported",
        "method": "parser:" + kind,
    }
    rec.update(extra)
    return rec


def _negated(email, start):
    """True when the ~45 chars before this span carry a negation/exception cue.

    Scoped to the current CLAUSE. A negation only binds the value it actually
    governs: in "Do not send the PI yet for the 1,500 pcs order" the "not"
    negates SENDING, not the quantity — the 1,500 is a stated fact. Same for
    "No rush on the 3,300 pcs TS-444" (negates urgency) and "unit price USD 4.00"
    after "quantity was 300 pcs not 3,000 pcs" (negates only the 3,000).

    So the window stops at a clause boundary — sentence end, or the conjunction
    that starts a new clause about a different predicate.
    """
    win = email[max(0, start - 45):start]
    # cut the window at the nearest clause boundary
    cut = max(win.rfind(x) for x in (";", ":", "。", "！", "？", "!", "?", "\n"))
    if cut != -1:
        win = win[cut + 1:]
    # also cut at a contrastive conjunction: everything after it is a new claim
    cut2 = max(win.rfind(x) for x in (", but", ", and", ", 然", "，但", "，而", " but ", " but"))
    if cut2 != -1:
        win = win[cut2 + 1:]
    # A negation that governs a VERB does not reach a number that is the OBJECT of
    # a different verb later in the same clause. "Do not send the PI yet for the
    # 1,500 pcs order" negates SENDING; "No rush on the 3,300 pcs TS-444" negates
    # URGENCY. In both the quantity is what was ordered and is a stated fact.
    # Require the negation to be in the same tight span as the value — after the
    # governing verb phrase — rather than anywhere in the preceding clause.
    if VERB_NEGATION_RE.search(win):
        return False
    # A negation binds only the value IMMEDIATELY following it. "quantity was 300 pcs
    # not 3,000 pcs, unit price USD 4.00" negates the 3,000; the 4.00 is introduced
    # by a fresh noun phrase after the comma and is a live figure. So: find the
    # negation cue, then check whether the text between it and this value contains
    # a clause boundary. If it does, the negation governs something else.
    m = NEGATION_RE.search(win)
    if not m:
        return False
    between = win[m.end():]
    if re.search(r"[,.;:，。；：、]|\b(?:but|and|while|whereas)\b", between):
        return False
    return True


def _asserted(email, start):
    """Cue words immediately before this span -> the customer is asserting/asking."""
    return bool(CUSTOMER_ASSERTION_RE.search(email[max(0, start - 60):start]))


def _clause_before(email, start, width=32):
    """Text immediately before `start`, cut at the nearest clause boundary.

    A qualifier only binds the value it actually modifies. Scoping the window
    keeps "Initial order would be around 300 pcs" intact while stopping a hedge
    attached to an EARLIER number from leaking onto a later one.
    """
    win = email[max(0, start - width):start]
    cut = max(win.rfind(x) for x in (";", ":", "。", "！", "？", "!", "?", "\n", ",", "，"))
    if cut != -1:
        win = win[cut + 1:]
    return win


def _qualifier(email, start, end):
    """Capture how firmly the value is stated: around / at least / at most / exact.

    Returns {"kind": ...|None, "raw": literal hedge text, "approx": bool}.
    The hedge keeps the NUMBER from being quoted with precision the customer
    never claimed: "around 300 pcs" is (300, approx), never a flat 300.
    """
    win = _clause_before(email, start)
    for kind, rx in (("max", MAX_RE), ("min", MIN_RE), ("approx", APPROX_RE), ("exact", EXACT_RE)):
        m = rx.search(win)
        if m:
            return {"kind": kind, "raw": (m.group(0) or "").strip(), "approx": kind == "approx"}
    # postposed hedge: "300 pcs or so"
    tail = email[end:end + 16]
    if APPROX_POST_RE.match(tail):
        return {"kind": "approx", "raw": "or so", "approx": True}
    return {"kind": None, "raw": None, "approx": False}


def _relation(email, start):
    """Delivery relation attached to a date: before | by | after | on | None.

    "before Dec 20" and "Dec 20" are different promises. Dropping the relation
    turns the customer's requirement into a flat — and false — date claim.
    """
    win = _clause_before(email, start, 34)
    m = RELATION_RE.search(win)
    if not m:
        return None
    raw = (m.group(1) or m.group(2) or m.group(0) or "").strip().lower()
    return RELATION_MAP.get(raw, "on")


def _own_commitment(email, start):
    """Cue words immediately before this span -> the sender asserts it as OUR term."""
    return bool(OWN_COMMITMENT_RE.search(email[max(0, start - 60):start]))


# A value the customer is NEGOTIATING, not stating. "Our budget is USD 2.00/pc",
# "meet us at 2.00", "is the price still 2.40?" are positions to be answered, not
# agreed facts. Echoing one back in a reply is how a system accidentally accepts
# the customer's number. A price merely REFERENCED as fact ("your list price is
# USD 2.40") is not contested — the two are different speech acts.
CONTESTED_RE = re.compile(
    r"(?:our|the|my)\s+(?:budget|target|offer|price\s+cap|cap)\b"
    r"|meet\s+us\s+at\b"
    r"|we\s+(?:can\s+)?(?:pay|offer|accept|do)\s+(?:at\s+)?(?:usd|eur|cny|rmb|\$|€|¥)?\s*\d"
    r"|is\s+the\s+(?:unit\s+)?price\s+(?:still|now)\b"
    r"|still\s+(?:at|usd|eur)\s*[\d$€¥]"
    r"|(?:budget|target|cap)\s+(?:is|of)\s+(?:usd|eur|cny|rmb|\$|€|¥)?\s*\d"
    # "Please accept 20%", "please resolve and confirm Nov 1", "correct?",
    # "you offered the usual 5% discount" — the customer is asking US to agree
    # to a number. Restating it adopts their number as ours.
    r"|please\s+(?:[^.;:!?]{0,24}?)?(?:accept|approve|confirm|apply|use|proceed|resolve|advise|reply|tell|let)\b"
    r"|(?:and\s+)?(?:correct|right|is\s+that\s+right)\s*\??\s*$"
    r"|(?:did|did\s+you)\s+you\s+offer\b"
    r"|you\s+(?:said|offered|quoted|promised)\b"
    r"|can\s+only\s+release\b"
    r"|with\s+the\s+\w+\s+applied\b",
    re.I)


def _contested(email, start):
    """True when this value is the customer's negotiating position, not a stated
    fact. Scoped to NEGOTIABLE values only (amount, ratio, date/deadline): a
    product code, a quantity they ordered or their own signature are not things
    anyone negotiates, and treating them as contested would strip real facts.

    The cue must sit IMMEDIATELY before this value and must not cross another
    numeric literal — "meet us at 2.00" marks the 2.00, not the 2.40 quoted
    earlier in the same sentence. Window ends at this span's own start.
    """
    return bool(CONTESTED_RE.search(email[max(0, start - 70):start]))


# ----------------------------------------------------------------- extractors

def _amounts(email):
    out = []
    for m in AMOUNT_RE.finditer(email):
        cur = m.group("cur") or m.group("cur2")
        num = m.group("n1") or m.group("n2") or m.group("n4")
        bare = bool(m.group("n4"))
        if cur in CUR_MAP:
            cur = CUR_MAP[cur]
        if not num:
            continue
        out.append(_mk(email, m.start(), m.end(), "amount", currency=cur, number=num,
                       weak=bare,
                       qualifier=_qualifier(email, m.start(), m.end()),
                       negated=_negated(email, m.start())))
    return out


def _qty_role(email, start, end):
    """Classify a quantity so the store can pick the operative one.

    Roles, in the order the store prefers them:
      total        "合计 5,000 件" — the figure that summarises the line
      primary      the plain ordered amount
      conditional  "if approved, bulk will be 3,000" — not yet committed
      defect       "roughly 40 pcs damaged" — a defect count, not an order
      historical   "we ordered 12,000 pcs last year" — a past order, not this one

    The historical cue is scoped to the 40 characters AFTER the number, never the
    whole email: in "is the unit price still USD 2.40 like last season? ... we take
    10,000 pcs" the "last season" describes the PRICE and the 10,000 is the live
    ask, so a document-wide cue would wrongly demote it.
    """
    before = email[max(0, start - 60):start]
    after = email[end:end + 40]
    if TOTAL_QTY_RE.search(before[-24:]) or TOTAL_QTY_RE.match(after[:14]):
        return "total"
    if DEFECT_QTY_RE.match(after) or DEFECT_QTY_RE.search(after[:24]):
        return "defect"
    if HISTORICAL_QTY_RE.search(after[:40]):
        return "historical"
    if CONDITIONAL_QTY_RE.search(before[-40:]) and CONDITIONAL_CONJ_RE.search(before):
        return "conditional"
    return "primary"


def _quantities(email):
    out = []
    for rx in (QTY_RE, QTY_BARE_RE):
        for m in rx.finditer(email):
            out.append(_mk(email, m.start(), m.end(), "qty", number=m.group("num"),
                           unit=m.group("unit"), role=_qty_role(email, m.start(), m.end()),
                           qualifier=_qualifier(email, m.start(), m.end()),
                           negated=_negated(email, m.start())))
    # multiplication listing: capture the number and, when present, the SKU to its left
    for m in QTY_MUL_RE.finditer(email):
        num = m.group(1)
        head = email[max(0, m.start() - 24):m.start()]
        sid = re.search(r"([A-Z]{1,4}-?\d[\w\-]*)\s*[x×@*]\s*$", head)
        out.append(_mk(email, m.start(), m.end(), "qty", number=num, unit=None,
                       listing_sku=sid.group(1) if sid else None,
                       qualifier=_qualifier(email, m.start(), m.end()),
                       negated=_negated(email, m.start())))
    return out


# A relative time word is a real deadline only when the customer is asking us to
# do something by then ("请 today 告诉我", "advise by tomorrow"). When it merely
# describes the customer's own schedule ("we sign today"), it is not a deadline.
REQUEST_CUE_RE = re.compile(
    r"(please\s+(?:advise|confirm|reply|let\s+us\s+know|tell|send|provide)|advise\s+(?:us\s+)?by"
    r"|reply\s+by|confirm\s+by|let\s+us\s+know\s+by|tell\s+us\s+by|need\s+(?:it\s+)?by"
    # a bare "by <date>" is a delivery deadline: "in Hamburg by Oct 3". The cue
    # is the preposition, and it can sit well before the date once the product
    # code and quantity are in between.
    r"|\bby\s*$|\bbefore\s*$|\bdue\s*$|\bno\s+later\s+than\s*$"
    r"|\b(?:need|require|want|ship|deliver|arrive)\b[^.;:!?]{0,40}\bby\s*$"
    r"|请|告诉我|回复|告知|答复|确认|反馈|核实)", re.I)


def _deadline_hint(email, start):
    """True when a request cue sits just before this date/time word.

    The window is generous (60 chars) because a real business sentence puts the
    product code and quantity between the request and the date:
    "We need the 3,000 pcs TS-901 in Hamburg by Oct 3".
    """
    return bool(REQUEST_CUE_RE.search(email[max(0, start - 60):start]))


def _ratios(email):
    out = []
    for m in PCT_RE.finditer(email):
        out.append(_mk(email, m.start(), m.end(), "ratio", value_pct=m.group("pct"),
                       negated=_negated(email, m.start())))
    for m in RATIO_RE.finditer(email):
        out.append(_mk(email, m.start(), m.end(), "ratio"))
    for m in CN_DISCOUNT_RE.finditer(email):
        out.append(_mk(email, m.start(), m.end(), "ratio_cn_idiom",
                       note="Chinese discount idiom — never convert to a number"))
    return out


def _docid_value(email, m):
    """The identifier itself, without any CJK label that introduced it.

    The span stays as matched (it is the evidence), but the VALUE must be the
    ASCII token: quoting "订单明细 OL-3301" as a style code is a fabricated
    identifier.
    """
    s = m.group(0)
    stripped = DOCID_CJK_LABEL_RE.sub("", s)
    toks = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", stripped)
    return toks[-1] if toks else stripped.strip()


def _idents(email):
    out = []
    for m in DOCID_RE.finditer(email):
        # "please quote 3,000 pcs" — the verb, not an identifier
        alias = DOCID_VERBALIAS_RE.match(email[m.start():m.start() + 24])
        if alias and email[m.start():m.start() + alias.end()].lower().startswith("quote"):
            continue
        out.append(_mk(email, m.start(), m.end(), "doc_id",
                       value=_docid_value(email, m),
                       role="product_identifier_candidate"))
    for rx in (SKU_RE, SKU_SPACED_RE):
        for m in rx.finditer(email):
            if any(m.start() < f["span_end"] and f["span_start"] < m.end() for f in out):
                continue
            if SHIPPING_EQUIP_RE.match(email, m.start()):
                continue
            out.append(_mk(email, m.start(), m.end(), "sku"))
    out.sort(key=lambda f: f["span_start"])
    return out


def _incoterms(email):
    out = []
    for m in INCOTERM_RE.finditer(email):
        raw = m.group(0)
        norm = (m.groupdict().get("zh") or raw).upper().strip()
        if raw in INCOTERM_ZH_MAP:
            norm = INCOTERM_ZH_MAP[raw]
        tail = email[m.end():m.end() + 40]
        pm = re.match(r"\s+([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)*)", tail)
        out.append(_mk(email, m.start(), m.end(), "incoterm", normalized=norm,
                       place=pm.group(1) if pm else None,
                       named_place=pm.group(1) if pm else None,
                       negated=_negated(email, m.start())))
    return out


def _product_names(email):
    """Merchandise named with a COMMON NOUN rather than an identifier.

    v3 could only read identifier shapes, so a line like "ski jackets" never
    entered the fact store at all and the reply had nothing to confirm back.
    These candidates live outside `_facts` on purpose: adding them to the
    selector's candidate list would change what the model sees and therefore
    every recorded selection, so they are surfaced by the semantic layer
    instead. Every match is still a verbatim substring of the source.
    """
    out, spans = [], []
    for rx in (PRODUCT_NAME_RE, CJK_PRODUCT_NAME_RE):
        for m in rx.finditer(email):
            head = email[max(0, m.start() - 24):m.start()]
            if PRODUCT_NAME_BLOCK_RE.search(head):
                continue
            s, e = m.start("p"), m.end("p")
            if any(s < te and ts < e for ts, te in spans):
                continue
            spans.append((s, e))
            rec = _mk(email, s, e, "product_name", method="parser:product_name")
            rec["value"] = email[s:e].strip()
            out.append(rec)
    out.sort(key=lambda f: f["span_start"])
    # one line may repeat the noun; keep the first occurrence of each phrase
    seen, uniq = set(), []
    for f in out:
        k = _norm_key(f["value"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(f)
    return uniq


def _norm_key(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _dates(email):
    out, taken = [], []
    for m in RANGE_RE.finditer(email):
        out.append(_mk(email, m.start(), m.end(), "date_range",
                       relation=_relation(email, m.start())))
        taken.append((m.start(), m.end()))
    for rx in DATE_PATS:
        for m in rx.finditer(email):
            if any(m.start() < te and ts < m.end() for ts, te in taken):
                continue
            # A concrete date is only a DEADLINE when the customer ties it to a
            # delivery/request cue ("samples received Oct 3" is history; "we need
            # it by Oct 3" is a deadline). Recording the hint lets the store
            # recall a deadline the selector omitted without promoting every
            # date in the email.
            out.append(_mk(email, m.start(), m.end(), "date",
                           relation=_relation(email, m.start()),
                           deadline_hint=_deadline_hint(email, m.start())))
    for m in BARE_MONTH_RE.finditer(email):
        if any(m.start() < te and ts < m.end() for ts, te in taken):
            continue
        q = QUALIFIED_MONTH_RE.search(email[max(0, m.start() - 20):m.end()])
        out.append(_mk(email, m.start(), m.end(), "date_bare_month",
                       month=MONTH_CANON[m.group(0).lower().rstrip(".")],
                       relation=_relation(email, m.start()),
                       qualified=bool(q)))
    for m in CJK_BARE_MONTH_RE.finditer(email):
        if any(m.start() < te and ts < m.end() for ts, te in taken):
            continue
        out.append(_mk(email, m.start(), m.end(), "date_bare_month", month=m.group(1) + "月",
                       relation=_relation(email, m.start())))
    out.sort(key=lambda f: f["span_start"])
    return out


def _relative(email):
    """Relative-time words. deadline_hint=True means the customer asked us to act
    by then ('please advise by tomorrow'); False means it describes their own
    schedule ('we sign today') and must not become our deadline."""
    out = []
    for m in RELATIVE_RE.finditer(email):
        hint = _deadline_hint(email, m.start())
        out.append(_mk(email, m.start(), m.end(), "relative_time",
                       deadline_hint=hint,
                       note=("customer asks us to respond by this time"
                             if hint else "customer's own schedule — not our deadline")))
    return out


def _durations(email):
    return [_mk(email, m.start(), m.end(), "duration") for m in DURATION_RE.finditer(email)]


def _payment(email):
    out = []
    for m in PAYMENT_RE.finditer(email):
        v = m.group(0).strip()
        if len(v) < 2:
            continue
        out.append(_mk(email, m.start(), m.end(), "payment_terms",
                       negated=_negated(email, m.start())))
    return out


def _buyer(email):
    """Trailing signature. Shapes seen in this domain:
         "Anna Berg"                      Latin personal name
         "Daniel Ross, Meridian Textiles Ltd"   name + company
         "Michael Chen, Pacific Trade Co"
         "Mr. Tanaka"                     honorific + name
         "Jean-Pierre Laurent"            hyphenated
         "青岛海联 王强" / "宁波盛丰 吴迪"   CJK company + name
         "陈立"                            CJK personal name
    Strategy: take the last line; if it is long (single-paragraph email), take the
    trailing run of name-like tokens. Never return a candidate that carries a
    verb, quantity or trade term.
    """
    lines = [l.strip() for l in email.strip().splitlines() if l.strip()]
    if not lines:
        return []
    tail = lines[-1]
    out = []

    # a final line that is entirely name-like
    if _name_like(tail) and len(tail) <= 60:
        s = email.rfind(tail)
        out.append(_mk(email, s, s + len(tail), "buyer_signature"))

    # The signature is the trailing name-like run. Walk back over candidate
    # boundaries from the end and keep the LONGEST run that is name-like — this
    # handles "…ship? Anna Berg", "…We need 3,000 pcs. Daniel Ross, Meridian
    # Textiles Ltd" and the valediction case "Regards, Hans Mueller"
    # (a comma boundary, not a sentence boundary).
    ends = [m.end() for m in re.finditer(r"[.。!！?？]", email)]
    ends += [m.end() for m in re.finditer(r",\s+(?=[A-Z一-鿿])", email)]
    ends.append(len(email))
    starts = {0} | set(ends)
    best = None
    for st in sorted(starts):
        s = st
        while s < len(email) and email[s] in ",，、;； \t":
            s += 1
        cand = email[s:]
        if not cand or len(cand) > 60 or "\n" in cand.strip():
            continue
        if _name_like(cand):
            span = (s, s + len(cand.rstrip()))
            if best is None or (span[1] - span[0]) > (best[1] - best[0]):
                best = span
    if best:
        out.append(_mk(email, best[0], best[1], "buyer_signature"))

    # dedupe by span
    seen, uniq = set(), []
    for f in out:
        k = (f["span_start"], f["span_end"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(f)
    if not uniq:
        return []

    # prefer the longest (name + company beats bare surname)
    uniq.sort(key=lambda f: (len(f["value"]), -f["span_start"]), reverse=True)
    return uniq[:1]


_NAME_WORD_RE = re.compile(r"^[A-Z][A-Za-z'’\-]*$")
_NAME_HONORIFIC_RE = re.compile(r"^(Mr|Mrs|Ms|Miss|Dr|Prof)\.?$", re.I)
_NAME_STOP_RE = re.compile(
    r"^(pcs?|pieces?|units?|sets?|kg|cartons?|boxes?|usd|eur|cny|gbp|fob|cif|cfr|exw|cpt|cip|dap|ddp|dpu"
    r"|lc|l/c|po|pi|inv|so|etd|eta|pi|packing|list|total|order|shipment|delivery|please|thank|thanks"
    r"|regards|best|sincerely|hi|hello|dear|sir|madam)$", re.I)


def _name_like(s):
    """Conservative: does this string look like a person/company signature?"""
    s = (s or "").strip()
    if not s or len(s) > 60:
        return False
    if re.search(r"\d", s.replace("'", "")):          # digits -> not a name
        return False
    if re.search(r"[.。!！?？:：;；]", s):             # sentence punctuation
        return False
    # CJK: company + name or a bare CJK name
    if re.search(r"[一-鿿]", s):
        return bool(re.fullmatch(r"[一-鿿][一-鿿\s]{0,14}", s.strip()))
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if not parts or len(parts) > 2:
        return False
    if len(parts) == 2:
        # "Name, Company" — company may carry suffixes
        company_ok = bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9&.\-' ]{1,28}(?:Ltd|Inc|Co|LLC|GmbH|AB|BV|S\.A\.|Group|Holdings)?",
                                       parts[1].strip()))
        return _latin_name(parts[0]) and company_ok
    return _latin_name(parts[0])


def _latin_name(p):
    p = p.strip()
    if not p:
        return False
    words = p.split()
    if not (1 <= len(words) <= 4):
        return False
    if _NAME_STOP_RE.match(words[-1]):
        return False
    return all(_NAME_WORD_RE.match(w) or _NAME_HONORIFIC_RE.match(w) for w in words)


def collect(email):
    """Run every deterministic extractor; return candidates with stable ids."""
    parsed = {
        "amounts": _amounts(email),
        "quantities": _quantities(email),
        "dates": _dates(email),
        "durations": _durations(email),
        "relative_time": _relative(email),
        "ratios": _ratios(email),
        "identifiers": _idents(email),
        "incoterms": _incoterms(email),
        "payment_terms": _payment(email),
        "buyer": _buyer(email),
    }
    facts = []
    for k in ("buyer", "incoterms", "payment_terms", "dates", "durations",
              "relative_time", "quantities", "amounts", "ratios", "identifiers"):
        facts.extend(parsed.get(k) or [])
    facts.sort(key=lambda f: (f["span_start"], f["span_end"]))
    for i, f in enumerate(facts, 1):
        f["id"] = f"f{i:03d}"
        f["customer_asserted"] = _asserted(email, f["span_start"])
        f["own_commitment"] = _own_commitment(email, f["span_start"])
        f["contested"] = _contested(email, f["span_start"]) \
            if f["type"] in ("amount", "ratio", "date", "duration") else False
    idx = {}
    for f in facts:
        idx.setdefault(f["type"], []).append(f["id"])
    parsed["_facts"] = facts
    parsed["_index"] = idx
    # Merchandise named with a common noun. Deliberately NOT part of `_facts`:
    # adding it would change the selector's candidate list and therefore every
    # recorded selection. The semantic layer consumes it directly.
    parsed["_product_names"] = _product_names(email)
    return parsed


if __name__ == "__main__":
    import sys
    for em in sys.argv[1:]:
        p = collect(em)
        print("EMAIL:", em)
        for f in p["_facts"]:
            print(f"  {f['id']} {f['type']:16s} {f['value']!r:30s} "
                  f"neg={f.get('negated')} asserted={f.get('customer_asserted')}")
        print("-" * 70)