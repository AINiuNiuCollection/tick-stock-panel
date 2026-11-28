"""政策事件抓取 CLI — 东财快讯 → 关键词过滤 → draft 增量合并 (P3-T2)。

用法:
    python scripts/fetch_policy_events.py [--data-root data] [--pages 40] [--since-days 7] [--dry-run]

    --dry-run: 只打印候选不写库。
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.custom.market.events import merge_fetched  # noqa: E402
from app.custom.market.fetcher import fetch_policy_drafts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取东财快讯生成政策事件 draft 候选")
    parser.add_argument("--data-root", default="data", help="数据根目录 (含 policy/policy_events.json)")
    parser.add_argument("--pages", type=int, default=40, help="抓取页数 (每页50条)")
    parser.add_argument("--since-days", type=int, default=7, help="只保留近 N 天事件")
    parser.add_argument("--dry-run", action="store_true", help="只打印候选, 不写库")
    args = parser.parse_args()

    print(f"抓取东财快讯 pages={args.pages} since_days={args.since_days} ...")
    drafts = fetch_policy_drafts(pages=args.pages, since_days=args.since_days)
    print(f"关键词过滤后候选 {len(drafts)} 条")
    for cat, n in Counter(d["category"] for d in drafts).most_common():
        print(f"  {cat}: {n}")
    for d in drafts[:10]:
        print(f"  [{d['date']}] ({d['category']}/{d['direction']}) {d['title'][:40]}")

    if args.dry_run:
        print("--dry-run: 未写库")
        return 0

    data_root = Path(args.data_root)
    added, skipped = merge_fetched(data_root, drafts)
    print(f"合并结果: 新增 {added} 条, 跳过已存在 {len(skipped)} 条 -> {data_root}/policy/policy_events.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
