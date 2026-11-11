# 指标修订

## 本次修订的指标 ID 清单

本轮共修订 7 个指标（指标 ID 不变），修订集中在定义文字、约束与来源说明，指标的计算口径未变：

- monthly_paid_buyer_count
- monthly_paid_order_count
- monthly_paid_sales_cents
- monthly_paid_repeat_buyer_count
- monthly_paid_repeat_rate
- monthly_paid_avg_order_value
- new_member_count

其余 31 个指标 ID 本轮核对后无修订。

## 逐项修订前与修订后定义

| 指标 ID | 修订前定义 | 修订后定义 |
| --- | --- | --- |
| monthly_paid_buyer_count | 自然月内有至少一笔有效订单、且月末符合总部运营月报付费资格的不同账户数。 | 同前，补：付费资格按卡产品名称归一后判断（悦享卡（年）与悦享年卡为同一卡种），员工卡不计入。 |
| monthly_paid_order_count | 月末符合付费资格的账户在该自然月的全部有效订单数，按账户资格筛选，不按卡重复。 | 同前，补同上卡产品归一与员工卡排除说明。 |
| monthly_paid_sales_cents | 月末符合付费资格的账户在该自然月的有效订单净销售额合计，单位分。 | 同前，补同上卡产品归一与员工卡排除说明。 |
| monthly_paid_repeat_buyer_count | 月末符合付费资格，且同一自然月至少有两笔有效订单的不同账户数。 | 同前，补同上卡产品归一与员工卡排除说明。 |
| monthly_paid_repeat_rate | 月末付费会员复购人数除以月末付费会员购买人数；分母为零时未定义。 | 同前，补同上卡产品归一与员工卡排除说明（作用于分子分母的资格集合）。 |
| monthly_paid_avg_order_value | 月末付费会员净销售额除以月末付费会员有效订单数；单位分／单，分母零时未定义。 | 同前，补同上卡产品归一与员工卡排除说明（作用于分子分母的资格集合）。 |
| new_member_count | 按注册日期统计新注册 CRM 账户数；可按归属门店和会员等级分组，不等于自然人数。 | 同前，补：归属门店取不到、无法关联门店的记录不进入计数，列入覆盖说明。 |

`catalog.json` 同步修订：六项 monthly_paid_* 各追加一条 `sources`（引用 business_model.md 的卡种别名与员工卡结论）与一条 `constraints`（卡产品名称按旧名归一后判断；员工卡不纳入付费资格）；new_member_count 追加一条 `constraints`（仅统计门店关联校验通过的账户；注册门店取不到的记录列入覆盖说明，不按零计）。`metrics.yml` 同步追加上述说明；派生模型 `.sql` 的筛选与计算未改。所有指标 `id`、`name` 未变。

## 修订依据、来源、原因及适用范围

- 卡种别名与员工卡（六项 monthly_paid_*）：陈姐第 1 场确认「悦享卡（年）」是悦享年卡改名前的旧叫法、属同一卡种，「员工卡」不属会员权益、不计入付费会员资格（C-05 MSG-05113）。对应模型修订见 [model_changes.md](model_changes.md) 的 R7、第 2 节卡产品类型行、第 3 节 cards 行。该别名属字段格式问题，已在 `cleaning_rules.yaml` 的 `card_kind_alias` 归一，因此 `p1_qualified_member_months.sql` 中 `card_type in ('悦享年卡','家庭季卡')` 无需改写、计算口径不变；补充说明是为让定义可追溯。适用范围：仍限本期总部运营月报口径、完整自然月、P1 暂定试算。
- 门店归属覆盖（new_member_count）：第 3、8 步剖析与对账显示会员表 1130 条注册门店取不到门店表、归一化后仍余 3 条未关联，按 `UNLINKED_STORE` 隔离、不进入 members（见 [data_diagnosis.md](data_diagnosis.md) 与 `artifacts/w04/adapter_test_report.json`）。对应模型修订见 [model_changes.md](model_changes.md) 第 3 节新增待核段与第 6 节待核行。原因：按归属门店分组时不能把取不到的记录静默当零或当作未知门店。适用范围：按归属门店分组的统计；该限制待老周、小林核实门店定义与门店表完整性后调整。
- 订单状态成交口径、区域划分、手机号掩码：证据不足，未据此改指标定义，保留在模型待核事项中；若后续确认，将按同一流程修订并重新导入新项目回归。
- 与模型一致性的核对：本次修订的 7 个 ID 与 [model_changes.md](model_changes.md) 的关联指标列一一对应；未修订的 31 项指标的筛选项未引用门店归属或卡种别名以外的未定口径，与模型结论一致。38 项均在导入后的库上运行通过（`customer/w04/run_metrics.py` 打印 `38 []`，`project-c/validation.json` 的 `passed` 为 true）。
