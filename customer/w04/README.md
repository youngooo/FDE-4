# W04 客户代码入口

在 `solution.py` 实现剖析、适配和对账，在 `test_solution.py` 写自己的测试。空白入口会明确失败。命令和数据形状见 `contracts/w04/README.md`，同接口完整例题见 `examples/w04/wutong/`。

解压后的工程根目录就是本周的交付仓库。在工程根目录执行 `python tools/w04.py init --workspace .`，把四份文档模板补到 `docs/w04/`。`check.json` 中的 `{root}` 指工程根目录，预检从这里调用课程工具。将 W03 的 `docs/w03/business_model.md` 复制到 `docs/w04/business_model.md`；checkpoint 起步使用其中的 `w03-reference/business_model.md`。保留 W03 原版，按证据修改 W04 副本，并在 `model_changes.md` 记录核对结果与修订依据，再核对模型与指标是否一致。初始化不会覆盖已有的代码和文档，可以重复执行。

字段含义、清洗判断、映射和覆盖说明属于客户层。原文件只读保留，输出进入新目录。自建路线可自行实现命令，但提交同样格式的 CSV、报告和源码；教师核验需能在指定输入目录上重跑。

## 运行目录

每次 adapt 和 load 都要使用不存在的输出目录和项目目录，全量重导不能追加旧库。建议把每轮运行放在 `.runtime/w04/run-01/`、`run-02/`……下，`.runtime/` 不进入提交；报告直接写到 `artifacts/w04/`。规则文件固定放在 `artifacts/w04/cleaning_rules.yaml`，预检按这个位置执行适配。下面的 `YOUR_*` 换成自己的实际路径：

```sh
python tools/w04.py profile --source YOUR_DATA_DIR --dictionary YOUR_DICTIONARY --code customer/w04/solution.py --output artifacts/w04/profile_report.json --data-version YOUR_DATA_VERSION
python tools/w04.py adapt --source YOUR_DATA_DIR --rules artifacts/w04/cleaning_rules.yaml --code customer/w04/solution.py --output .runtime/w04/run-01/adapt --library YOUR_LIBRARY --project .runtime/w04/run-01/project-a
python tools/w04.py load --data .runtime/w04/run-01/adapt/cleaned --library YOUR_LIBRARY --project .runtime/w04/run-01/project-b
python tools/w04.py reconcile --run .runtime/w04/run-01/adapt --first .runtime/w04/run-01/project-a --second .runtime/w04/run-01/project-b --code customer/w04/solution.py --output artifacts/w04/adapter_test_report.json
python tools/w04.py check --workspace . --output artifacts/w04/precheck.json
```

adapt 或 load 中途失败时，输出目录（只运行 load 时为项目目录）里的 `import_failed.json` 写明失败阶段和原因。这个目录只保留作诊断，修正后换下一个运行编号重跑；路径已存在时，报错会列出已存在的路径。
