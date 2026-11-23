"""B2 零命中漏斗探针 (用后即删): 全市场统计 B1/B2/B3 产出、年龄与背驰分布。

不带 max_signal_age / min_divergence_hits 过滤 (0=不限),
回答: 是市场上根本没有 B2, 还是 B2 被哪个过滤器绞杀了。
"""
import glob
import time
from collections import Counter
from datetime import date

import polars as pl

from app.custom.czsc.application.scanner import ScanService
from app.custom.czsc.application.service import get_default_service
from app.custom.czsc.config import ScanRequest


class NoNestAnalyzer:
    """包装真实 analyzer 但禁用区间套下钻 — 探针不做次级别外呼。"""
    nest_verifier = None

    def __init__(self, inner):
        self.inner = inner

    def analyze(self, req):
        return self.inner.analyze(req)


paths = sorted(glob.glob('../data/kline_daily/date=*'))
df = pl.read_parquet(paths[-1])
symbols = df['symbol'].unique().to_list()
print(f'universe: {len(symbols)} symbols (last partition {paths[-1].split("=")[-1]})', flush=True)

req = ScanRequest(
    symbols=tuple(symbols), freq='日线', as_of=date(2026, 11, 23), lookback_days=425,
    signal_types=('B1', 'B2', 'B3'), max_signal_age=0, min_divergence_hits=0,
    order_by='dt_desc', limit=100000, max_workers=16,
).normalized()

svc = ScanService(analyzer=NoNestAnalyzer(get_default_service()))
t0 = time.time()
res = svc.scan(req)
elapsed = time.time() - t0
print(f'elapsed={elapsed:.1f}s scanned={res.total_scanned} errors={len(res.errors)}', flush=True)
if res.errors:
    for k, v in list(res.errors.items())[:5]:
        print('  err:', k, v)

counts = Counter(h.type for h in res.hits)
print('hits by type:', dict(counts), flush=True)

for t in ('B1', 'B2', 'B3'):
    hs = [h for h in res.hits if h.type == t]
    if not hs:
        print(f'{t}: 0 个', flush=True)
        continue
    ages = Counter(h.signal_age_days for h in hs)
    divs = Counter(len(h.divergence_pass) for h in hs)
    print(f'{t}: n={len(hs)}  年龄分布(前12): {dict(sorted(ages.items())[:12])}  '
          f'背驰命中分布: {dict(divs)}', flush=True)

print('\n=== 全部 B2 详情 ===', flush=True)
for h in res.hits:
    if h.type == 'B2':
        print(f'  B2 {h.symbol} dt={str(h.dt)[:10]} price={h.price} age={h.signal_age_days} '
              f'div={h.divergence_pass} type={h.divergence_type}', flush=True)

print('\n=== B1 年龄≤10 的 (用户年龄窗口内) ===', flush=True)
young_b1 = [h for h in res.hits if h.type == 'B1' and h.signal_age_days <= 10]
print(f'  n={len(young_b1)}', flush=True)
print('\n=== B3 年龄≤10 的 ===', flush=True)
young_b3 = [h for h in res.hits if h.type == 'B3' and h.signal_age_days <= 10]
print(f'  n={len(young_b3)}  其中背驰命中≥2: '
      f'{sum(1 for h in young_b3 if len(h.divergence_pass) >= 2)}', flush=True)
