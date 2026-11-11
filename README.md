# W04 青禾问数作业（数据剖析、清洗适配与指标修订）

本仓库提交第四周作业：在真实导出的青禾 CRM 数据上完成字段剖析与字典差异归类，用自写的清洗规则把原始记录适配导入指标库，核对并修订 W03 的 38 项指标，再按「月度会员复购率」链路做实机演示与调优对照。

## 阅读入口

| 内容 | 文件 |
| --- | --- |
| 本周核实后的业务模型 | [business_model.md](docs/w04/business_model.md) |
| 模型核对范围、修订前后与依据 | [model_changes.md](docs/w04/model_changes.md) |
| 指标库修订记录（7 项，ID 不变） | [metric_changes.md](docs/w04/metric_changes.md) |
| 数据诊断：字典差异三类、工作账对照、待核清单 | [data_diagnosis.md](docs/w04/data_diagnosis.md) |
| 演示链路选择、bad case 与下一步 | [demo_plan.md](docs/w04/demo_plan.md) |
| 剖析／清洗适配源码与单元测试 | [solution.py](customer/w04/solution.py)、[test_solution.py](customer/w04/test_solution.py)、[unittest_run.txt](customer/w04/unittest_run.txt) |
| 字段统计、异常模式与字典差异 | [profile_report.json](artifacts/w04/profile_report.json) |
| 本人编写的清洗规则 | [cleaning_rules.yaml](artifacts/w04/cleaning_rules.yaml) |
| 映射、读入、接受、隔离、去重与对账 | [adapter_test_report.json](artifacts/w04/adapter_test_report.json) |
| 38 项定稿指标库 | [library](artifacts/w04/library) |
| 38 项在导入后库上的执行结果 | [metrics_run.json](artifacts/w04/metrics_run.json) |
| 演示运行记录与调优对照 | [demo_annotation.json](artifacts/w04/demo_annotation.json)、[demo_run.json](artifacts/w04/demo_run.json) |
| 本周访谈原始导出 | [interviews](artifacts/w04/interviews) |
| 课程预检结果 | [precheck-v1.json](artifacts/w04/precheck-v1.json) |

## 本周结果

**数据与覆盖。** 数据版本 `qinghe-w04-v1.1`，覆盖 `[2024-09-01, 2026-09-01)`（结束日不含），来源只含新 CRM 导出的会员、订单、会员卡、门店四个文件；旧收银系统消费记录未导出，小林工作账只用于对照、不进入查询库。

**剖析。** 46 个字段、15 类异常模式、17 处字典差异，按「字典过时、映射错误、数据暂缺」三类归类，每处写明影响、修订对象和取证对象。

**适配与导入**（读入 → 接受，括号内为隔离／去重）：

- members 119,754 → 119,751（隔离 3）
- orders 168,253 → 167,661（隔离 256／去重 336）
- cards 16,648 → 16,349（隔离 299）
- stores 403 → 403

四条对账等式全部成立，被拒记录合计 558 条逐条有去向；合法标签 56,212 条进 `member_tags`，备注 9,172 条整条保留原文与来源，触达限制类备注（勿打电话／勿发短信）按规则整条保留。

**重复导入。** 两次独立导入的各表计数、订单条数与实付金额（1,708,397,059 分）完全一致。

**指标。** 38 项在导入后的库上全部 `status=ok`，ID 不变；本轮修订 7 项（6 项付费月报与 `new_member_count`），修订集中在定义文字、约束与来源说明，计算口径未变，`catalog.json` 同步补充来源与约束。

**演示。** 链路为月度会员复购率查询与数据来源覆盖说明。2026 年 8 月月内复购率 11.80%；调优为同一问题、只改一处，改动位置 `提示词／上下文`（只改 `customer/w04/answer_prompt.txt`），调优后回答带数据来源与时间覆盖边界。`demo_run.json` 共 9 条运行记录，其中 5 条标注 `bad_case` 并写明原因（部分覆盖窗口被整体拒答、瞬时故障重跑），全部保留未删。

**预检。** [precheck-v1.json](artifacts/w04/precheck-v1.json) 80 项全部通过（`passed: true`、`manual_review_required: true`）。

六项付费月报按 P1 暂定口径验证，书面业务确认仍待取得；以上工程结果不代表教师验收、业务核定或生产上线批准。

## 下载提交包

[下载 w04-submit.zip](submission/w04-submit.zip) · [SHA256](submission/SHA256SUMS.txt)

ZIP 按仓库原路径打包 `customer/w04/`、`docs/w04/`、`artifacts/w04/` 三层，共 98 个文件；仓库中的成果文件与 ZIP 为同一版本，README 与 Git 配置是仓库导航附件。

## 复跑条件

- 需要课程工程副本（含 `tools/w04.py`、`templates/`、`examples/`）、课程原始数据目录与字典文件，以及自己的模型配置（三个模型环境变量）。
- 统一使用 `.venv/bin/python`。剖析、适配、导入、对账与预检按 [customer/w04/README.md](customer/w04/README.md) 的命令重跑，适配与导入必须使用不存在的输出目录和项目目录。
- 清洗后的契约 CSV、导入库与 `.runtime/` 中间产物可重跑再生，不随作业提供；仓库不含虚拟环境、缓存、密钥或课程原始数据。
