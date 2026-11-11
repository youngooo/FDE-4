import json, sys
from pathlib import Path
sys.path.insert(0, 'platform')
from fde_product.metrics.engine import query_worker

project, start, end = sys.argv[1:4]
catalog = json.loads(Path('artifacts/w04/library/catalog.json').read_text(encoding='utf-8'))
results = {}
for metric in catalog:
    intent = {'metrics': [metric['id']], 'start': start, 'end': end, 'group_by': [], 'filters': []}
    results[metric['id']] = query_worker(project, intent)
Path('artifacts/w04/metrics_run.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(len(results), [key for key, value in results.items() if value['status'] != 'ok'])
