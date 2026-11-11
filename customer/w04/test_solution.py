"""青禾 CRM 适配器测试：合法标签与备注拆分、隔离去向、金额日期换算、重复运行一致性。"""
import importlib.util
import json
from pathlib import Path
import unittest
import yaml

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
RULES_DIR = ROOT / 'artifacts' / 'w04'

spec = importlib.util.spec_from_file_location('w04_solution', HERE.with_name('solution.py'))
solution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(solution)

SHOP = {'shop_cd': '9801', 'shop_nm': '青禾体验店', 'area': '华东', 'shop_stat': '营业', 'open_dt': '2024-09-01'}


def sheet(filename, records):
    """构造和 io.read_inputs 一致的入参结构：source_file、从 1 起的 source_row、raw。"""
    return {filename: {'rows': [{'source_file': filename, 'source_row': index, 'raw': record}
                                for index, record in enumerate(records, 1)]}}


class CustomerAdapterTests(unittest.TestCase):
    def setUp(self):
        self.rules = yaml.safe_load((RULES_DIR / 'cleaning_rules.yaml').read_text(encoding='utf-8-sig'))
        self.context = {'source': 'unit-test', 'rules_dir': str(RULES_DIR), 'data_version': 'unit-test'}

    def member(self, **overrides):
        raw = {'hy_id': 'QH1', 'join_dt': '2025/03/16', 'reg_shop': '9801', 'lv': '普通',
               'stat': '1', 'src_ch': '门店', 'create_tm': '2025-03-16 10:00:00', 'tag': ''}
        raw.update(overrides)
        return raw

    def build(self, members=(), orders=(), cards=(), shops=(SHOP,)):
        return {**sheet('crm_shop.csv', list(shops)),
                **sheet('crm_member_export.csv', list(members)),
                **sheet('crm_order_export.csv', list(orders)),
                **sheet('crm_card_export.csv', list(cards))}

    def run_adapt(self, tables):
        return solution.adapt(tables, self.rules, self.context)

    def test_legal_tags_kept_and_notes_preserved(self):
        result = self.run_adapt(self.build(members=[self.member(tag='高价值,母婴-0到3岁,待核新品')]))
        self.assertEqual({row['tag'] for row in result['tables']['member_tags']}, {'高价值', '母婴-0到3岁'})
        notes = result['tables']['member_notes']
        self.assertEqual([note['note_text'] for note in notes], ['待核新品'])
        self.assertEqual(notes[0]['raw_text'], '高价值,母婴-0到3岁,待核新品')
        self.assertEqual(notes[0]['source_field'], 'tag')

    def test_fullwidth_delimiter_splits_tags(self):
        result = self.run_adapt(self.build(members=[self.member(tag='高价值，夜间购物')]))
        self.assertEqual({row['tag'] for row in result['tables']['member_tags']}, {'高价值', '夜间购物'})

    def test_unlinked_store_is_quarantined_with_source(self):
        result = self.run_adapt(self.build(members=[self.member(reg_shop='9999')]))
        self.assertEqual(result['tables']['members'], [])
        quarantined = result['tables']['quarantine']
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0]['record_type'], 'member')
        self.assertEqual(quarantined[0]['reason_code'], 'UNLINKED_STORE')
        self.assertEqual(quarantined[0]['source_file'], 'crm_member_export.csv')
        self.assertEqual(quarantined[0]['source_row'], 1)
        self.assertEqual(json.loads(quarantined[0]['raw_json'])['hy_id'], 'QH1')
        counts = result['record_counts']['member']
        self.assertEqual((counts['read'], counts['accepted'], counts['quarantined']), (1, 0, 1))

    def test_counts_balance_and_samples_have_two_kinds(self):
        order = {'ord_no': 'O1', 'hy_id': 'QH1', 'shop_cd': '9801', 'ord_tm': '2026-05-01 12:00:00',
                 'ord_stat': '已支付', 'amt_total': '10.00', 'amt_pay': '10.00', 'amt_rfd': '0.00',
                 'qty': '1', 'ch': '门店'}
        orphan = dict(order, ord_no='O2', hy_id='MISSING')
        result = self.run_adapt(self.build(members=[self.member()], orders=[order, orphan]))
        for kind, counts in result['record_counts'].items():
            self.assertEqual(counts['read'], counts['accepted'] + counts['quarantined'] + counts['deduplicated'], kind)
        statuses = {sample['status'] for sample in result['samples']}
        self.assertIn('accepted', statuses)
        self.assertIn('quarantined', statuses)

    def test_money_and_date_conversions(self):
        self.assertEqual(solution._cents('19.99'), 1999)
        self.assertEqual(solution._cents('100'), 10000)
        with self.assertRaises(ValueError):
            solution._cents('0.001')
        self.assertEqual(solution._date('2025/03/16'), '2025-03-16')
        self.assertEqual(solution._date('20250316'), '2025-03-16')
        self.assertEqual(solution._date('2025-03-16 08:00:00'), '2025-03-16')
        self.assertEqual(solution._date('无', optional=True), '')
        with self.assertRaises(ValueError):
            solution._date('2026-02-30')

    def test_repeat_run_is_identical(self):
        order = {'ord_no': 'O1', 'hy_id': 'QH1', 'shop_cd': '9801', 'ord_tm': '2026-05-01 12:00:00',
                 'ord_stat': '已支付', 'amt_total': '10.00', 'amt_pay': '10.00', 'amt_rfd': '0.00',
                 'qty': '1', 'ch': '门店'}
        tables = self.build(members=[self.member(tag='高价值,待核新品')], orders=[order, dict(order)])
        first, second = self.run_adapt(tables), self.run_adapt(tables)
        self.assertEqual(first['record_counts']['order']['deduplicated'], 1)
        self.assertEqual(first['record_counts']['order']['accepted'], 1)
        self.assertEqual(first['tables'], second['tables'])
        self.assertEqual(first['record_counts'], second['record_counts'])


if __name__ == '__main__':
    unittest.main()
