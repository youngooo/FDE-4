"""青禾（QH）CRM 导出的剖析：逐字段统计、异常取证、与字典 v2.3 的差异。

统计部分是通用的；异常和字典差异的检查条件按青禾字典 v2.3 的声明写死，
换客户、换样本都要按对方的字典重写，不能照搬到梧桐例题或公开预检样本。
"""
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

MISSING = ('', 'NULL', '-', '无')
MAX_SAMPLE = 20
DISTINCT_LIMIT = 30

MEMBER_FILE = 'crm_member_export.csv'
ORDER_FILE = 'crm_order_export.csv'
CARD_FILE = 'crm_card_export.csv'
SHOP_FILE = 'crm_shop.csv'

MONEY_FIELDS = frozenset({'amt_total', 'amt_pay', 'amt_rfd', 'pay_amt'})
DATE_FIELDS = frozenset({'join_dt', 'birth', 'st_dt', 'ed_dt', 'stop_dt', 'open_dt'})

ISO_DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}$')
INTEGER = re.compile(r'-?[0-9]+$')
DECIMAL = re.compile(r'-?[0-9]+\.[0-9]+$')
TAG_SPLIT = re.compile(r'[,，;；、|/]+')
BLANK = re.compile(r'\s+')
NOTE_SHAPE = re.compile(r'[-。]')
SECTION = re.compile(r'^#{1,6}\s*(.+?)（([^）]+)）\s*$')

# 字典 v2.3 附录标签表
DICTIONARY_TAGS = frozenset({
    '高价值', '价格敏感', '宠物', '生鲜偏好', '母婴-0到3岁', '母婴-3到6岁',
    '周末家庭', '学生', '企业团购', '流失预警', '积分达人', '门店偏好',
})

# 字典 v2.3 已声明的枚举取值：数据里出现声明之外的取值，就是字典落后或字段用错
DECLARED_VALUES = {
    (MEMBER_FILE, 'stat'): frozenset({'1', '2', '3'}),
    (MEMBER_FILE, 'lv'): frozenset({'1', '2', '3'}),
    (MEMBER_FILE, 'src_ch'): frozenset({'门店', '小程序', '商城'}),
    (SHOP_FILE, 'area'): frozenset({'华东', '华南', '华北'}),
    (SHOP_FILE, 'shop_stat'): frozenset({'营业', '闭店'}),
    (CARD_FILE, 'card_kind'): frozenset({'悦享卡（年）', '家庭季卡', '异业联名卡', '体验卡'}),
    (ORDER_FILE, 'ord_stat'): frozenset({'已支付', '已完成', '部分退款', '全额退款', '已取消'}),
    (ORDER_FILE, 'ch'): frozenset({'门店', '小程序', '商城'}),
}

ENUM_IMPACT = {
    (MEMBER_FILE, 'stat'): '会员状态少一类会让会员总盘与流失口径不全，口径里到底算不算这一类要请老周确认',
    (MEMBER_FILE, 'lv'): '等级按字典的代码制映射会全部落空，分层与权益口径直接失效',
    (MEMBER_FILE, 'src_ch'): '注册渠道分组会漏一类，该渠道的记录同时缺注册设备，渠道获客口径不完整',
    (SHOP_FILE, 'area'): '大区分组会漏两类，区域汇总和片区分工都会少算',
    (SHOP_FILE, 'shop_stat'): '门店状态取值超出声明，营业门店口径需要复核',
    (CARD_FILE, 'card_kind'): '卡种取值超出声明，购卡与卡权益口径不完整，需确认新卡种是否应计入',
    (ORDER_FILE, 'ord_stat'): '订单状态取值超出声明，成交与退款口径需要复核',
    (ORDER_FILE, 'ch'): '渠道取值超出声明，渠道结构需要复核',
}


def _present(values):
    return [value for value in values if value not in MISSING]


def _normalize(value):
    """去掉首尾空白并把全角字符转半角，用于判断写法差异是否可归一化。"""
    return unicodedata.normalize('NFKC', value).strip()


def _extreme(present, kind, pick):
    if not present:
        return None
    if kind in ('integer', 'decimal'):
        try:
            return str(pick(Decimal(value) for value in present))
        except InvalidOperation:
            pass
    return pick(present)


def _stat(filename, table, field):
    """一个字段一条统计：类型、缺失、取值分布或范围。"""
    values = [row['raw'][field] for row in table['rows']]
    present = _present(values)
    if present and all(INTEGER.match(value) for value in present):
        kind = 'integer'
    elif present and all(DECIMAL.match(value) for value in present):
        kind = 'decimal'
    else:
        kind = 'string'
    stat = {'source_file': filename, 'field': field, 'inferred_type': kind,
            'total_count': len(values), 'missing_count': len(values) - len(present)}
    counts = Counter(values)
    if 0 < len(counts) <= DISTINCT_LIMIT:
        stat['distribution'] = [{'value': value, 'count': count} for value, count in sorted(counts.items())]
    else:
        stat['range'] = {'min': _extreme(present, kind, min), 'max': _extreme(present, kind, max)}
    return stat


def _section_key(name):
    return name.strip().removesuffix('.csv')


def _parse_dictionary(text):
    """按“## 表名（文件名）”分节解析字段表；字典不用表格列举字段时返回空。"""
    sections, current = {}, None
    for line in text.splitlines():
        heading = SECTION.match(line.strip())
        if heading:
            current = _section_key(heading.group(2))
            sections.setdefault(current, {})
            continue
        if current is None or not line.startswith('|'):
            continue
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if len(cells) < 4 or not cells[0].startswith('`'):
            continue
        sections[current][cells[0].strip('`')] = {'type': cells[2], 'note': cells[3]}
    return {name: fields for name, fields in sections.items() if fields}


def _claim(declared, filename, field, dictionary, keywords, default):
    """字典原话优先，其次按关键词找句子，最后用兜底说明。"""
    row = declared.get(_section_key(filename), {}).get(field)
    if row:
        parts = [f'类型“{row["type"]}”'] if row.get('type') else []
        if row.get('note'):
            parts.append(f'说明“{row["note"]}”')
        return '字典 v2.3 记载：' + '、'.join(parts)
    sentences = [line.strip().strip('|').strip() for line in re.split(r'[。；\n]', dictionary) if line.strip()]
    for sentence in sentences:
        if field in sentence:
            return sentence.strip('`')
    for sentence in sentences:
        if any(keyword in sentence for keyword in keywords):
            return sentence.strip('`')
    return default


def profile(tables, dictionary, context):
    fields, anomalies, differences = [], [], []
    by_file = tables

    for filename in sorted(by_file):
        for field in by_file[filename]['fields']:
            fields.append(_stat(filename, by_file[filename], field))

    def table_of(name):
        return by_file.get(name)

    def rows_of(name):
        table = by_file.get(name)
        return table['rows'] if table else []

    declared = _parse_dictionary(dictionary)
    member_rows, order_rows = rows_of(MEMBER_FILE), rows_of(ORDER_FILE)

    # 1) 完全重复的记录：全部字段逐字相同
    for filename in sorted(by_file):
        seen, duplicates = set(), []
        for row in by_file[filename]['rows']:
            key = tuple(row['raw'].items())
            if key in seen:
                duplicates.append(row['source_row'])
            seen.add(key)
        if duplicates:
            anomalies.append({'pattern': f'完全重复的记录 {len(duplicates)} 条：{filename} 内全部字段逐字相同，只保留首次出现',
                              'evidence': {'source_file': filename, 'sample_rows': duplicates[:MAX_SAMPLE]}})

    # 2) 孤儿订单：订单的会员号在会员表里不存在
    member_ids = {row['raw']['hy_id'] for row in member_rows if 'hy_id' in row['raw']}
    if member_ids and order_rows:
        orphans = [row['source_row'] for row in order_rows if row['raw'].get('hy_id') not in member_ids]
        if orphans:
            anomalies.append({'pattern': f'孤儿订单 {len(orphans)} 条：订单的会员号在会员表中不存在，订单归不到任何会员',
                              'evidence': {'source_file': ORDER_FILE, 'sample_rows': orphans[:MAX_SAMPLE]}})

    # 3) 门店号写法不统一：门店表自身，以及引用方取不到门店表
    shop_table = table_of(SHOP_FILE)
    if shop_table:
        odd_codes = [row for row in shop_table['rows'] if row['raw']['shop_cd'] != _normalize(row['raw']['shop_cd'])]
        shop_codes = {row['raw']['shop_cd'] for row in shop_table['rows']}
        normalized_codes = {_normalize(row['raw']['shop_cd']) for row in shop_table['rows']}
        if odd_codes:
            samples = '、'.join(repr(row['raw']['shop_cd']) for row in odd_codes[:3])
            anomalies.append({'pattern': f'门店表自身编号写法不统一 {len(odd_codes)} 条：{SHOP_FILE} 的 shop_cd 带首尾空格或全角字符',
                              'evidence': {'source_file': SHOP_FILE, 'sample_rows': [row['source_row'] for row in odd_codes[:MAX_SAMPLE]]}})
            differences.append({'source_file': SHOP_FILE, 'field': 'shop_cd',
                                'dictionary_claim': _claim(declared, SHOP_FILE, 'shop_cd', dictionary, ('门店', '编码'), '字典声明门店编码为 4 位数字，唯一'),
                                'actual': f'门店表自己有 {len(odd_codes)} 条编号带首尾空格或全角字符，例如 {samples}',
                                'impact': '门店主键不统一，引用方按原值关联会取不到门店；需要在适配时统一去空白并把全角转半角，再确认剩下的是不是真的缺门店'})
        for filename, field in ((ORDER_FILE, 'shop_cd'), (MEMBER_FILE, 'reg_shop')):
            rows = rows_of(filename)
            if not rows or field not in by_file[filename]['fields']:
                continue
            missing = [row for row in rows if row['raw'][field] not in shop_codes]
            if not missing:
                continue
            fixable = [row for row in missing if _normalize(row['raw'][field]) in normalized_codes]
            left = [row for row in missing if _normalize(row['raw'][field]) not in normalized_codes]
            examples = '、'.join(repr(row['raw'][field]) for row in left[:3])
            anomalies.append({'pattern': f'门店号取不到门店表 {len(missing)} 条：{filename} 的 {field} 有 {len(fixable)} 条去空白、全角转半角后能对上，{len(left)} 条门店表里确实没有',
                              'evidence': {'source_file': filename, 'sample_rows': [row['source_row'] for row in missing[:MAX_SAMPLE]]}})
            differences.append({'source_file': filename, 'field': field,
                                'dictionary_claim': _claim(declared, filename, field, dictionary, ('门店', '编码'), f'字典声明 {field} 为门店编码，见门店表'),
                                'actual': f'{len(missing)} 条取不到门店表：{len(fixable)} 条是首尾空格或全角写法，归一化后能对上；{len(left)} 条归一化后仍没有，例如 {examples}',
                                'impact': '门店维度分组会丢记录；能归一化的按格式修，归一化后仍没有的不能当零，要写进覆盖说明并向客户核对门店主数据'})

    # 4) 金额字段：字典声明整数分，实际是元的两位小数
    for filename in (ORDER_FILE, CARD_FILE):
        table = table_of(filename)
        if not table:
            continue
        hit = []
        for field in table['fields']:
            if field not in MONEY_FIELDS:
                continue
            present = _present([row['raw'][field] for row in table['rows']])
            if present and all('.' in value for value in present):
                hit.append((field, present[0]))
        if not hit:
            continue
        names = '、'.join(field for field, _ in hit)
        sample_rows = [row['source_row'] for row in table['rows'] if any('.' in row['raw'][field] for field, _ in hit)][:MAX_SAMPLE]
        anomalies.append({'pattern': f'金额按元记两位小数 {len(table["rows"])} 条：{filename} 的 {names} 与字典“整数分”不符',
                          'evidence': {'source_file': filename, 'sample_rows': sample_rows}})
        for field, example in hit:
            differences.append({'source_file': filename, 'field': field,
                                'dictionary_claim': _claim(declared, filename, field, dictionary, ('分', '金额', '单位'), f'字典声明 {field} 为整数分'),
                                'actual': f'{len(table["rows"])} 条全部为元的两位小数，例如 {field}={example}',
                                'impact': '按分直接取用会把金额放大 100 倍，涉及成交金额、客单价、退款金额等口径；适配时必须按 Decimal 乘 100 取整'})

    # 5) 日期格式混用：字典声明日期，实际出现斜杠或无分隔写法
    for filename in sorted(by_file):
        for field in by_file[filename]['fields']:
            if field not in DATE_FIELDS:
                continue
            bad = [row['source_row'] for row in by_file[filename]['rows']
                   if row['raw'][field] not in MISSING and not ISO_DATE.match(row['raw'][field])]
            if not bad:
                continue
            example = next(row['raw'][field] for row in by_file[filename]['rows']
                           if row['raw'][field] not in MISSING and not ISO_DATE.match(row['raw'][field]))
            anomalies.append({'pattern': f'日期格式混用 {len(bad)} 条：{filename} 的 {field} 出现斜杠或无分隔写法，例如 {example}',
                              'evidence': {'source_file': filename, 'sample_rows': bad[:MAX_SAMPLE]}})
            differences.append({'source_file': filename, 'field': field,
                                'dictionary_claim': _claim(declared, filename, field, dictionary, ('ISO', '日期'), f'字典声明 {field} 为日期'),
                                'actual': f'{len(bad)} 条不是 ISO 写法，出现 {example} 这类斜杠或无分隔日期',
                                'impact': '按单一格式解析会把这批记录当无效值丢掉或误判成缺失，影响新客、留存和门店开业时间等口径；适配要按多格式显式解析'})

    # 6) 手机号已脱敏：字典声明 11 位
    member_table = table_of(MEMBER_FILE)
    if member_table and 'mobile' in member_table['fields'] and member_rows:
        masked = [row['source_row'] for row in member_rows if '****' in row['raw']['mobile']]
        if len(masked) == len(member_rows):
            anomalies.append({'pattern': f'手机号已脱敏 {len(masked)} 条：{MEMBER_FILE} 的 mobile 全部为掩码形式，无法还原',
                              'evidence': {'source_file': MEMBER_FILE, 'sample_rows': masked[:MAX_SAMPLE]}})
            differences.append({'source_file': MEMBER_FILE, 'field': 'mobile',
                                'dictionary_claim': _claim(declared, MEMBER_FILE, 'mobile', dictionary, ('11 位', '手机'), '字典声明手机号为 11 位'),
                                'actual': f'{len(masked)} 条全部是 139****3278 这类掩码，取不到完整号码',
                                'impact': '手机号不能当触达依据，也不能当跨系统匹配键；要请老周确认脱敏发生在导出环节还是库里本来如此'})

    # 7) 标签列：分隔符与字典不一致，且混进了字典标签表之外的取值
    if member_table and 'tag' in member_table['fields'] and member_rows:
        separator_rows, unknown_rows, unknown = [], [], Counter()
        for row in member_rows:
            raw = row['raw']['tag']
            if raw in MISSING:
                continue
            if re.search(r'[，;；、|/]', raw):
                separator_rows.append(row['source_row'])
            tokens = []
            for chunk in TAG_SPLIT.split(raw):
                tokens.extend(token for token in BLANK.split(chunk.strip()) if token)
            outside = [token for token in tokens if token not in DICTIONARY_TAGS]
            if outside:
                unknown_rows.append(row['source_row'])
                for token in outside:
                    unknown[token] += 1
        if separator_rows or unknown_rows:
            note_like = sorted(token for token in unknown if NOTE_SHAPE.search(token))
            plain = sorted(token for token in unknown if not NOTE_SHAPE.search(token))
            anomalies.append({'pattern': f'会员标签列混写 {len(unknown_rows)} 行：{len(separator_rows)} 行用逗号以外的分隔符，{len(unknown)} 种取值不在字典附录标签表内',
                              'evidence': {'source_file': MEMBER_FILE, 'sample_rows': unknown_rows[:MAX_SAMPLE]}})
            differences.append({'source_file': MEMBER_FILE, 'field': 'tag',
                                'dictionary_claim': _claim(declared, MEMBER_FILE, 'tag', dictionary, ('标签', '逗号'), '字典声明多个标签用逗号分隔，取值见附录标签表'),
                                'actual': f'{len(separator_rows)} 行用中文逗号、分号、斜杠或空格分隔；{len(unknown_rows)} 行含字典标签表外的取值，共 {len(unknown)} 种，'
                                          f'其中 {len(note_like)} 种是带连字符或句号的备注文字（例如 {note_like[0] if note_like else "—"}），'
                                          f'{len(plain)} 种是字典里没有的短词（例如 {plain[0] if plain else "—"}），需要客户区分新增标签和备注',
                                'impact': '按逗号切分会漏掉合法标签；把备注当标签会污染标签口径；把客户已确认的新标签当无效值删掉会丢信息。适配要把拆分、保留、待核分开处理'})

    # 8) 字典未收录的字段：字典落后于数据
    if declared:
        for filename in sorted(by_file):
            known_fields = declared.get(_section_key(filename))
            if known_fields is None:
                continue
            for field in by_file[filename]['fields']:
                if field in known_fields:
                    continue
                present = _present([row['raw'][field] for row in by_file[filename]['rows']])
                differences.append({'source_file': filename, 'field': field,
                                    'dictionary_claim': f'字典 v2.3 的 {filename} 一节没有列出该字段',
                                    'actual': f'导出里有这一列，{len(present)} 条有值，例如 {present[0] if present else "—"}',
                                    'impact': '字典需要补字段说明；字段含义没有人书面确认过，适配时不能凭列名猜'})
    else:
        first = sorted(by_file)[0]
        differences.append({'source_file': first, 'field': by_file[first]['fields'][0],
                            'dictionary_claim': '该字典没有逐字段列举字段，无法逐项核对',
                            'actual': f'导出含 {len(by_file)} 个文件、{len(fields)} 个字段',
                            'impact': '拿不到逐字段的字典说法，只能按数据实际取值反推含义，需要向客户索取逐字段字典'})

    # 9) 字典已声明的枚举里出现了声明之外的取值
    for (filename, field), allowed in sorted(DECLARED_VALUES.items()):
        table = table_of(filename)
        if not table or field not in table['fields']:
            continue
        counts = Counter(row['raw'][field] for row in table['rows'])
        extra = sorted((value, count) for value, count in counts.items() if value not in MISSING and value not in allowed)
        if not extra:
            continue
        observed = '、'.join(f'{value}（{count} 条）' for value, count in extra)
        anomalies.append({'pattern': f'取值超出字典声明 {filename} 的 {field}：另有 {observed}，字典没有写明',
                          'evidence': {'source_file': filename,
                                       'sample_rows': [row['source_row'] for row in table['rows'] if row['raw'][field] in {value for value, _ in extra}][:MAX_SAMPLE]}})
        differences.append({'source_file': filename, 'field': field,
                            'dictionary_claim': _claim(declared, filename, field, dictionary, (field,), f'字典声明 {field} 的取值'),
                            'actual': f'实际还出现 {observed}',
                            'impact': ENUM_IMPACT.get((filename, field), '口径会漏一类，需向客户确认该取值如何处理')})

    return {'contract_version': 'w04-0.1.0', 'data_version': context['data_version'],
            'fields': fields, 'anomalies': anomalies, 'dictionary_differences': differences}


# --- 第 7 步：适配器 ---------------------------------------------------------
# 数据源文件与查询库表名、主键的对应。只处理四个 CRM 导出；小林工作账只用于对照。
SOURCE_FILES = {'shop': SHOP_FILE, 'member': MEMBER_FILE, 'order': ORDER_FILE, 'card': CARD_FILE}
TARGET_TABLES = {'shop': 'stores', 'member': 'members', 'order': 'orders', 'card': 'cards'}
PRIMARY_KEY = {'shop': 'shop_cd', 'member': 'hy_id', 'order': 'ord_no', 'card': 'card_no'}

# 契约与访谈确认过的取值映射（老周第 1 场 MSG-05078；陈姐第 1 场 MSG-05113）
ACCOUNT_STATUS = {'0': '未激活', '1': '活跃', '2': '冻结', '3': '注销'}
ORDER_STATUS = {'已支付': 'paid', '已完成': 'paid', '部分退款': 'paid', '全额退款': 'paid', '已取消': 'cancelled'}
CARD_TYPE = {'悦享卡（年）': '悦享年卡', '悦享年卡': '悦享年卡', '家庭季卡': '家庭季卡',
             '异业联名卡': '异业联名卡', '体验卡': '体验卡'}

NOTE_RESTRICTIONS = ('勿打电话', '勿发短信')
NOTE_CONTACT = ('联系状态', '电话', '微信', '号码', '短信')
NOTE_RELATION = ('熟客', '客户关系', '老客户', 'VIP', '朋友')


def _store_code(value):
    """门店编码：去首尾空白、全角转半角，再拿去和门店表比对。"""
    return unicodedata.normalize('NFKC', value).strip()


def _date(value, optional=False):
    """按 ISO、斜杠、无分隔、日期时间四种写法显式解析；解析不了抛 INVALID_DATE。"""
    text = value.strip()
    if text in MISSING:
        if optional:
            return ''
        raise ValueError('INVALID_DATE')
    for pattern in ('%Y-%m-%d', '%Y/%m/%d', '%Y%m%d', '%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S'):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError('INVALID_DATE')


def _cents(value):
    """字典声明整数分，实际是元的两位小数，按 Decimal 乘 100 取整。"""
    number = Decimal(value) * 100
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError('INVALID_MONEY')
    return int(number)


def _note_category(text):
    """备注按意思归类：触达限制优先，其次卡务、联系状态、客户关系，归不进去才用其他。"""
    if text.startswith(NOTE_RESTRICTIONS):
        return '触达限制'
    if '卡' in text:
        return '卡务'
    if text.startswith(NOTE_CONTACT) or any(word in text for word in ('打不通', '没接', '接不通', '回复', '方便')):
        return '联系状态'
    if text.startswith(NOTE_RELATION) or any(word in text for word in ('店长认识', '店长知道', '认识')):
        return '客户关系'
    return '其他'


def _field_mapping():
    """客户字段到查询库列的映射，逐条写明来源与变换。"""
    definitions = {
        MEMBER_FILE: {
            'members.member_id': (['hy_id'], '保留稳定会员号'),
            'members.registered_at': (['join_dt'], '按 ISO、斜杠、无分隔三种写法显式解析为本地日期'),
            'members.home_store_id': (['reg_shop'], '去首尾空白并把全角转半角后与门店表比对'),
            'members.tier': (['lv'], '直接采用等级文本（普通、银卡、金卡）'),
            'members.account_status': (['stat'], '0/1/2/3 映射为未激活、活跃、冻结、注销'),
            'members.registered_channel': (['src_ch'], '保留注册渠道（门店、小程序、商城、系统导入）'),
            'members.created_at': (['create_tm'], '取建档时间的本地日期'),
            'member_tags.tag': (['tag'], '命中 tags.txt 的合法标签才进标签表'),
            'member_notes.note_text': (['tag'], '非标签各段整条保留为备注，raw_text 记完整原值'),
        },
        ORDER_FILE: {
            'orders.order_id': (['ord_no'], '保留订单号'),
            'orders.member_id': (['hy_id'], '校验会员关联，取不到会员的整条隔离'),
            'orders.store_id': (['shop_cd'], '去空白、全角转半角后与门店表比对'),
            'orders.ordered_at': (['ord_tm'], '取下单时间的本地日期'),
            'orders.status': (['ord_stat'], '已支付、已完成、部分退款、全额退款转 paid；已取消转 cancelled'),
            'orders.gross_cents': (['amt_total'], 'Decimal 元乘 100 取整'),
            'orders.paid_cents': (['amt_pay'], 'Decimal 元乘 100 取整'),
            'orders.refund_cents': (['amt_rfd'], 'Decimal 元乘 100 取整；大于实付则隔离'),
            'orders.quantity': (['qty'], '转整数'),
            'orders.channel': (['ch'], '保留渠道（门店、小程序、商城）'),
        },
        CARD_FILE: {
            'cards.card_id': (['card_no'], '保留卡号'),
            'cards.member_id': (['hy_id'], '校验会员关联'),
            'cards.card_type': (['card_kind'], '悦享卡（年）改名为悦享年卡；员工卡不计付费资格，隔离'),
            'cards.valid_from': (['st_dt'], '解析生效日期'),
            'cards.valid_until': (['ed_dt'], '解析到期日期'),
            'cards.ended_at': (['stop_dt'], '空、NULL、-、无 视为未提前终止，留空'),
            'cards.card_paid_cents': (['pay_amt'], 'Decimal 元乘 100 取整'),
        },
        SHOP_FILE: {
            'stores.store_id': (['shop_cd'], '去首尾空白并把全角转半角'),
            'stores.region': (['area'], '保留大区'),
            'stores.store_name': (['shop_nm'], '保留门店名称'),
        },
    }
    mapping = []
    for filename, targets in definitions.items():
        for target, (fields, transformation) in targets.items():
            mapping.append({'source_file': filename, 'source_fields': fields, 'target': target,
                            'transformation': transformation})
    return mapping


def adapt(tables, rules, context):
    """按 cleaning_rules.yaml 执行清洗、字段映射、去向登记，并写出覆盖说明。

    返回 tables、record_counts、field_mapping、samples、coverage_notes。
    对账口径：read = accepted + quarantined + deduplicated；accepted 等于写出的行数，
    quarantined 等于隔离文件里对应类别的行数。
    """
    config = {record['rule_id']: record for record in rules['abnormal_records']}
    tag_rules = rules['tag_cleaning']
    tags_file = Path(context['rules_dir']) / tag_rules['legal_tags_source']
    known_tags = {line.strip() for line in tags_file.read_text(encoding='utf-8-sig').splitlines() if line.strip()}
    delimiter = re.compile('|'.join(re.escape(item) for item in tag_rules['delimiters']))

    output = {name: [] for name in ['members', 'orders', 'stores', 'cards', 'member_tags', 'member_notes', 'quarantine']}
    counts = {kind: {'read': len(tables[SOURCE_FILES[kind]]['rows']), 'accepted': 0, 'quarantined': 0, 'deduplicated': 0}
              for kind in SOURCE_FILES}
    samples = []
    accepted_members, store_ids = set(), set()
    tag_keys, note_keys = set(), set()

    def isolate(kind, row, code):
        counts[kind]['quarantined'] += 1
        output['quarantine'].append({'record_type': kind, 'source_file': row['source_file'],
                                     'source_row': row['source_row'], 'reason_code': code,
                                     'raw_json': json.dumps(row['raw'], ensure_ascii=False, sort_keys=True)})
        if not any(sample['status'] == 'quarantined' for sample in samples):
            samples.append({'source_file': row['source_file'], 'source_row': row['source_row'], 'status': 'quarantined',
                            'destination': 'quarantine.csv 记录 %d' % len(output['quarantine']), 'reason': code})

    # 先门店，再会员、订单、会员卡：被隔离的会员，其订单和卡随之取不到会员而隔离。
    for kind in ('shop', 'member', 'order', 'card'):
        filename = SOURCE_FILES[kind]
        rows = tables[filename]['rows']
        key = PRIMARY_KEY[kind]
        variants = defaultdict(set)
        for row in rows:
            variants[row['raw'][key]].add(tuple(row['raw'].items()))
        seen = set()
        for row in rows:
            raw = row['raw']
            identity = tuple(raw.items())
            if identity in seen:
                counts[kind]['deduplicated'] += 1
                continue
            seen.add(identity)
            if len(variants[raw[key]]) > 1:
                isolate(kind, row, config['duplicate_key']['reason_code'])
                continue
            try:
                if kind == 'shop':
                    store_id = _store_code(raw['shop_cd'])
                    mapped = {'store_id': store_id, 'region': raw['area'], 'store_name': raw['shop_nm']}
                    store_ids.add(store_id)
                elif kind == 'member':
                    account_status = ACCOUNT_STATUS.get(raw['stat'])
                    if account_status is None:
                        raise ValueError('INVALID_ACCOUNT_STATUS')
                    home_store = _store_code(raw['reg_shop'])
                    if home_store not in store_ids:
                        raise ValueError(config['unlinked_store']['reason_code'])
                    mapped = {'member_id': raw['hy_id'], 'registered_at': _date(raw['join_dt']),
                              'home_store_id': home_store, 'tier': raw['lv'], 'account_status': account_status,
                              'registered_channel': raw['src_ch'], 'created_at': _date(raw['create_tm'])}
                    accepted_members.add(raw['hy_id'])
                    tag_text = raw['tag']
                    if tag_text not in MISSING:
                        for segment in delimiter.split(tag_text):
                            segment = segment.strip()
                            if not segment:
                                continue
                            if segment in known_tags:
                                tag_key = (raw['hy_id'], segment)
                                if tag_key not in tag_keys:
                                    tag_keys.add(tag_key)
                                    output['member_tags'].append({'member_id': raw['hy_id'], 'tag': segment})
                            else:
                                note = {'member_id': raw['hy_id'], 'source_file': filename,
                                        'source_row': row['source_row'], 'source_field': 'tag', 'raw_text': tag_text,
                                        'note_text': segment, 'category': _note_category(segment)}
                                note_key = (raw['hy_id'], filename, row['source_row'], 'tag', segment)
                                if note_key not in note_keys:
                                    note_keys.add(note_key)
                                    output['member_notes'].append(note)
                elif kind == 'order':
                    if raw['hy_id'] not in accepted_members:
                        raise ValueError(config['orphan_order']['reason_code'])
                    store_id = _store_code(raw['shop_cd'])
                    if store_id not in store_ids:
                        raise ValueError(config['unlinked_store']['reason_code'])
                    status = ORDER_STATUS.get(raw['ord_stat'])
                    if status is None:
                        raise ValueError('UNSUPPORTED_ORDER_STATUS')
                    paid_cents, refund_cents = _cents(raw['amt_pay']), _cents(raw['amt_rfd'])
                    if refund_cents > paid_cents:
                        raise ValueError(config['refund_exceeds_paid']['reason_code'])
                    mapped = {'order_id': raw['ord_no'], 'member_id': raw['hy_id'], 'store_id': store_id,
                              'ordered_at': _date(raw['ord_tm']), 'status': status,
                              'gross_cents': _cents(raw['amt_total']), 'paid_cents': paid_cents,
                              'refund_cents': refund_cents, 'quantity': int(raw['qty']), 'channel': raw['ch']}
                else:
                    if raw['hy_id'] not in accepted_members:
                        raise ValueError(config['orphan_order']['reason_code'])
                    card_type = CARD_TYPE.get(raw['card_kind'])
                    if card_type is None:
                        raise ValueError(config['unsupported_card_type']['reason_code'])
                    mapped = {'card_id': raw['card_no'], 'member_id': raw['hy_id'], 'card_type': card_type,
                              'valid_from': _date(raw['st_dt']), 'valid_until': _date(raw['ed_dt']),
                              'ended_at': _date(raw['stop_dt'], optional=True), 'card_paid_cents': _cents(raw['pay_amt'])}
            except (ValueError, InvalidOperation) as exc:
                isolate(kind, row, str(exc) if isinstance(exc, ValueError) else 'INVALID_MONEY')
                continue
            output[TARGET_TABLES[kind]].append(mapped)
            counts[kind]['accepted'] += 1
            if kind == 'order' and not any(sample['status'] == 'accepted' for sample in samples):
                samples.append({'source_file': filename, 'source_row': row['source_row'], 'status': 'accepted',
                                'destination': 'orders.csv 记录 %d' % len(output['orders']),
                                'reason': '字段、单位、日期与关联均符合契约'})

    coverage = {
        'source': '本次只含新 CRM 导出的会员、订单、会员卡、门店四个文件；旧收银系统消费记录未导出，'
                  '小林工作账只用于对照核查，不导入查询库。',
        'time_range': {'start': '2024-09-01', 'end_exclusive': '2026-09-01'},
        'quarantined': {kind: counts[kind]['quarantined'] for kind in counts},
    }
    return {'tables': output, 'record_counts': counts, 'field_mapping': _field_mapping(),
            'samples': samples, 'coverage_notes': coverage}


# --- 第 8 步：二次导入对账 -----------------------------------------------------
RECORD_SOURCE = {'member': MEMBER_FILE, 'order': ORDER_FILE, 'card': CARD_FILE, 'shop': SHOP_FILE}


def reconcile(payload):
    """按源文件、清洗结果和两次独立导入的库内事实，算出适配器测试报告。

    三处真算：每类 read=accepted+quarantined+deduplicated 且 accepted 等于库内行数；
    重复导入前后逐表计数比对；清洗后订单金额汇总与两次库内 paid_cents 比对。
    """
    metadata = payload['metadata']
    manifest = payload['manifest']
    record_counts = []
    all_balanced = True
    for kind in ('member', 'order', 'card', 'shop'):
        values = metadata['record_counts'][kind]
        read = len(payload['source'][RECORD_SOURCE[kind]]['rows'])
        in_database = payload['first']['counts']['raw_' + TARGET_TABLES[kind]]
        balanced = (read == values['read'] == values['accepted'] + values['quarantined'] + values['deduplicated']
                    and in_database == values['accepted'])
        all_balanced = all_balanced and balanced
        record_counts.append({
            'record_type': kind,
            'read': values['read'], 'accepted': values['accepted'],
            'quarantined': values['quarantined'], 'deduplicated': values['deduplicated'],
            'reconciliation': {
                'balanced': balanced,
                'evidence': '源文件 %d = 接受 %d + 隔离 %d + 去重 %d；库内 %d' % (
                    read, values['accepted'], values['quarantined'], values['deduplicated'], in_database)}})

    cleaned_orders = payload['cleaned']['orders.csv']['rows']
    total_paid = sum(int(row['raw']['paid_cents']) for row in cleaned_orders)
    before, after = payload['first']['counts'], payload['second']['counts']
    repeat_equal = before == after
    passed = (all_balanced and repeat_equal
              and len(cleaned_orders) == payload['first']['order_count'] == payload['second']['order_count']
              and total_paid == payload['first']['paid_cents'] == payload['second']['paid_cents'])
    return {
        'contract_version': 'w04-0.1.0',
        'data_version': manifest['id'],
        'field_mapping': metadata['field_mapping'],
        'record_counts': record_counts,
        'samples': metadata['samples'],
        'repeat_import': {
            'first_run_id': payload['first_run_id'], 'second_run_id': payload['second_run_id'],
            'before': before, 'after': after, 'row_counts_equal': repeat_equal},
        'test_result': {
            'passed': passed,
            'details': '清洗后订单 %d 条，实付合计 %d 分；两次独立导入逐表计数、订单条数与实付金额均一致。'
                       % (len(cleaned_orders), total_paid)},
    }
