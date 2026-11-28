"""首批历史 major 政策事件种子 (P3-T6) — 一次性数据录入, 幂等可重跑。

背景: 东财快讯只覆盖近几周增量, 历史 major 事件无公开 API, 按设计 §2.1 人工录入。
每条 source 均经 scripts/probe_event_sources.py / resolve_event_sources.py 实探 HTTP 200
(2026-11-28)。百科条目作溯源时 note 已注明, 官方原件可后续人工替换 (merge 不覆盖人工修改)。

用法: python scripts/seed_policy_history.py [--data-root data] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HISTORICAL_EVENTS: list[dict] = [
    {
        "id": "2005-04-29-guquan-fenzhi-gaige",
        "date": "2005-04-29",
        "title": "股权分置改革试点启动 (证监会)",
        "category": "监管政策",
        "importance": "major",
        "direction": "positive",
        "source": "https://zh.wikipedia.org/wiki/%E8%82%A1%E6%9D%83%E5%88%86%E7%BD%AE%E6%94%B9%E9%9D%A9",
        "note": "A 股最深层次制度变革之一, 开启 2005-2007 大牛市; 溯源为百科条目",
        "status": "approved",
    },
    {
        "id": "2005-07-21-huigai",
        "date": "2005-07-21",
        "title": "人民币汇率形成机制改革 (7·21 汇改)",
        "category": "货币政策",
        "importance": "major",
        "direction": "neutral",
        "source": "https://zh.wikipedia.org/wiki/%E4%BA%BA%E6%B0%91%E5%B8%81%E6%B1%87%E7%8E%87",
        "note": "人民币脱离盯住美元, 开启长期升值通道; 溯源为百科条目",
        "status": "approved",
    },
    {
        "id": "2007-05-30-yinhuashui-shangdiao",
        "date": "2007-05-30",
        "title": "证券交易印花税上调至 3‰ (5·30)",
        "category": "财政政策",
        "importance": "major",
        "direction": "negative",
        "source": "https://baike.baidu.com/item/%E8%AF%81%E5%88%B8%E4%BA%A4%E6%98%93%E5%8D%B0%E8%8A%B1%E7%A8%8E",
        "note": "上调当日上证暴跌 6.5%; 溯源为百科条目",
        "status": "approved",
    },
    {
        "id": "2008-04-24-yinhuashui-xiadiaio",
        "date": "2008-04-24",
        "title": "证券交易印花税下调至 1‰",
        "category": "财政政策",
        "importance": "major",
        "direction": "positive",
        "source": "https://baike.baidu.com/item/%E8%AF%81%E5%88%B8%E4%BA%A4%E6%98%93%E5%8D%B0%E8%8A%B1%E7%A8%8E",
        "note": "下调当日上证大涨 9.29%; 溯源为百科条目",
        "status": "approved",
    },
    {
        "id": "2008-09-15-shouci-jiangxi",
        "date": "2008-09-15",
        "title": "央行下调贷款基准利率 (2008 周期首次降息)",
        "category": "货币政策",
        "importance": "major",
        "direction": "positive",
        "source": "https://zh.wikipedia.org/zh-cn/2008%E5%B9%B4%E9%87%91%E8%9E%8D%E5%8D%B1%E6%9C%BA",
        "note": "雷曼倒闭当日央行宣布降息+降准; 溯源为金融危机条目, 央行公告原件待人工替换",
        "status": "approved",
    },
    {
        "id": "2008-11-09-siwanyi",
        "date": "2008-11-09",
        "title": "四万亿投资计划 (国务院常务会议)",
        "category": "财政政策",
        "importance": "major",
        "direction": "positive",
        "source": "https://zh.wikipedia.org/wiki/%E5%9B%9B%E4%B8%87%E4%BA%BF%E8%AE%A1%E5%88%92",
        "note": "2009 年 V 型反转的直接推手",
        "status": "approved",
    },
    {
        "id": "2014-11-17-hugangtong",
        "date": "2014-11-17",
        "title": "沪港通正式开通",
        "category": "监管政策",
        "importance": "major",
        "direction": "positive",
        "source": "https://zh.wikipedia.org/wiki/%E6%B2%AA%E6%B8%AF%E9%80%9A",
        "note": "资本市场双向开放里程碑, 2014-2015 牛市催化之一",
        "status": "approved",
    },
    {
        "id": "2015-06-15-qingli-peizi",
        "date": "2015-06-15",
        "title": "清理场外配资引发杠杆牛去杠杆 (股灾起点)",
        "category": "监管政策",
        "importance": "major",
        "direction": "negative",
        "source": "https://zh.wikipedia.org/wiki/2015%E5%B9%B4%E4%B8%AD%E5%9B%BD%E8%82%A1%E7%81%BE",
        "note": "上证自 5178 起三周跌逾 30%",
        "status": "approved",
    },
    {
        "id": "2015-07-04-ipo-zanhuan",
        "date": "2015-07-04",
        "title": "IPO 暂缓发行 (救市组合拳)",
        "category": "监管政策",
        "importance": "major",
        "direction": "neutral",
        "source": "https://zh.wikipedia.org/wiki/2015%E5%B9%B4%E4%B8%AD%E5%9B%BD%E8%82%A1%E7%81%BE",
        "note": "28 只新股暂缓发行, 系 2015 股灾条目; 21 家券商救市公告同日",
        "status": "approved",
    },
    {
        "id": "2016-01-04-rongduan",
        "date": "2016-01-04",
        "title": "指数熔断机制实施 (四日两熔断)",
        "category": "监管政策",
        "importance": "major",
        "direction": "negative",
        "source": "https://zh.wikipedia.org/wiki/%E7%86%94%E6%96%AD%E6%9C%BA%E5%88%B6",
        "note": "实施 4 个交易日触发 2 次熔断后暂停; 当周上证跌 9.97%",
        "status": "approved",
    },
    {
        "id": "2018-03-23-maoyizhan",
        "date": "2018-03-23",
        "title": "中美贸易战开打 (301 关税签署)",
        "category": "外部事件",
        "importance": "major",
        "direction": "negative",
        "source": "https://zh.wikipedia.org/zh-cn/2018%E5%B9%B4%E4%B8%AD%E7%BE%8E%E8%B4%B8%E6%98%93%E6%88%98",
        "note": "特朗普签署对华关税备忘录, 当日上证跌 3.39%",
        "status": "approved",
    },
    {
        "id": "2018-06-01-msci-naru",
        "date": "2018-06-01",
        "title": "A 股正式纳入 MSCI 新兴市场指数",
        "category": "外部事件",
        "importance": "major",
        "direction": "positive",
        "source": "https://zh.wikipedia.org/wiki/MSCI",
        "note": "226 只 A 股首步納入 2.5% 因子",
        "status": "approved",
    },
    {
        "id": "2019-07-22-kechuangban",
        "date": "2019-07-22",
        "title": "科创板开板 首批 25 家上市",
        "category": "监管政策",
        "importance": "major",
        "direction": "neutral",
        "source": "https://zh.wikipedia.org/wiki/%E7%A7%91%E5%88%9B%E6%9D%BF",
        "note": "注册制试验田; 对大盘整体影响中性",
        "status": "approved",
    },
    {
        "id": "2019-08-17-lpr-gaige",
        "date": "2019-08-17",
        "title": "LPR 贷款市场报价利率形成机制改革",
        "category": "货币政策",
        "importance": "major",
        "direction": "positive",
        "source": "https://zh.wikipedia.org/zh-cn/%E8%B4%B7%E6%AC%BE%E5%B8%82%E5%9C%BA%E6%8A%A5%E4%BB%B7%E5%88%A9%E7%8E%87",
        "note": "央行公告〔2019〕第15号; 利率市场化两轨并一轨",
        "status": "approved",
    },
    {
        "id": "2020-02-03-yiqing-kaishi",
        "date": "2020-02-03",
        "title": "疫情后首个交易日 央行超额投放 1.2 万亿",
        "category": "外部事件",
        "importance": "major",
        "direction": "negative",
        "source": "https://zh.wikipedia.org/zh-cn/2019%E5%86%A0%E7%8A%B6%E7%97%85%E6%AF%92%E7%97%85%E7%96%AB%E6%83%85",
        "note": "春节后开市上证跌 7.72%, 央行当日逆回购 1.2 万亿; 疫情条目为溯源背景",
        "status": "approved",
    },
    {
        "id": "2021-07-24-shuangjian",
        "date": "2021-07-24",
        "title": "「双减」政策发布 (教培行业剧震)",
        "category": "产业政策",
        "importance": "major",
        "direction": "negative",
        "source": "https://zh.wikipedia.org/wiki/%E2%80%9C%E5%8F%8C%E5%87%8F%E2%80%9D%E6%94%BF%E7%AD%96",
        "note": "中办国办印发; 次周 A 股教育板块腰斩, 市场对政策不确定性重定价",
        "status": "approved",
    },
    {
        "id": "2021-09-02-beijiaosuo",
        "date": "2021-09-02",
        "title": "北交所设立宣布",
        "category": "监管政策",
        "importance": "major",
        "direction": "neutral",
        "source": "https://zh.wikipedia.org/wiki/%E5%8C%97%E4%BA%AC%E8%AF%81%E5%88%B8%E4%BA%A4%E6%98%93%E6%89%80",
        "note": "服务专精特新中小企业; 2021-11-15 开市",
        "status": "approved",
    },
    {
        "id": "2022-11-11-ershitiao",
        "date": "2022-11-11",
        "title": "优化疫情防控二十条措施发布",
        "category": "会议定调",
        "importance": "major",
        "direction": "positive",
        "source": "https://baike.baidu.com/item/%E4%BC%98%E5%8C%96%E8%90%BD%E5%AE%9E%E7%96%AB%E6%83%85%E9%98%B2%E6%8E%A7%E4%BA%8C%E5%8D%81%E6%9D%A1%E6%8E%AA%E6%96%BD",
        "note": "中央政治局常委会会议审议; 溯源为百科条目",
        "status": "approved",
    },
    {
        "id": "2023-08-27-yinhuashui-jianban",
        "date": "2023-08-27",
        "title": "证券交易印花税减半征收",
        "category": "财政政策",
        "importance": "major",
        "direction": "positive",
        "source": "https://baike.baidu.com/item/%E5%8D%B0%E8%8A%B1%E7%A8%8E%E5%87%8F%E5%8D%8A",
        "note": "财政部 税务总局公告 2023 年第 39 号, 减半至 0.5‰",
        "status": "approved",
    },
    {
        "id": "2024-04-12-xinguojiutiao",
        "date": "2024-04-12",
        "title": "新「国九条」发布 (资本市场第三个国九条)",
        "category": "监管政策",
        "importance": "major",
        "direction": "neutral",
        "source": "https://baike.baidu.com/item/%E6%96%B0%E5%9B%BD%E4%B9%9D%E6%9D%A1",
        "note": "强监管防风险促高质量发展; 短期小微盘承压, 长期制度利好",
        "status": "approved",
    },
    {
        "id": "2024-09-24-jinrong-fabuhui",
        "date": "2024-09-24",
        "title": "国新办金融支持经济高质量发展发布会 (一揽子政策)",
        "category": "货币政策",
        "importance": "major",
        "direction": "positive",
        "source": "https://baike.baidu.com/item/9%C2%B724%E6%96%B0%E6%94%BF",
        "note": "降准+降息+互换便利+回购增持再贷款; 当日上证涨 4.15%, 开启 9·24 行情",
        "status": "approved",
    },
    {
        "id": "2024-11-08-huazhai-shiwan-yi",
        "date": "2024-11-08",
        "title": "人大常委会通过 6 万亿地方债置换 + 化债组合拳",
        "category": "财政政策",
        "importance": "major",
        "direction": "positive",
        "source": "https://baike.baidu.com/item/%E5%8C%96%E5%80%BA",
        "note": "直接安排 10 万亿元化解地方隐性债务",
        "status": "approved",
    },
    {
        "id": "2025-05-12-riguanei-lianhe-shengming",
        "date": "2025-05-12",
        "title": "中美日内瓦经贸会谈联合声明 (关税互降 115%)",
        "category": "外部事件",
        "importance": "major",
        "direction": "positive",
        "source": "https://baike.baidu.com/item/%E4%B8%AD%E7%BE%8E%E7%BB%8F%E8%B4%B8%E4%BC%9A%E8%B0%88",
        "note": "对等关税互降 115 个百分点, 90 天窗口",
        "status": "approved",
    },
]

FIXED_CALENDAR_ENTRIES: list[dict] = [
    {"date": "2027-03-05", "title": "十四届全国人大五次会议 (全国两会)", "kind": "两会", "note": "每年 3 月 5 日 (法定)"},
]


def main() -> int:
    parser = argparse.ArgumentParser(description="历史 major 事件 + 固定日历种子录入 (幂等)")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    policy_dir = Path(args.data_root) / "policy"
    policy_dir.mkdir(parents=True, exist_ok=True)

    # 事件: 按 id 增量 (存在即跳过, 不覆盖)
    events_path = policy_dir / "policy_events.json"
    raw = json.loads(events_path.read_text(encoding="utf-8")) if events_path.exists() else {"events": []}
    existing_ids = {e.get("id") for e in raw.get("events", [])}
    added = 0
    for ev in HISTORICAL_EVENTS:
        if ev["id"] in existing_ids:
            continue
        raw.setdefault("events", []).append(ev)
        existing_ids.add(ev["id"])
        added += 1

    # 日历: 全量覆写 (日历是人工维护的当前快照)
    calendar_path = policy_dir / "fixed_calendar.json"
    calendar_raw = {"entries": FIXED_CALENDAR_ENTRIES}

    print(f"历史 major 事件: 新增 {added} / 共 {len(HISTORICAL_EVENTS)} 条 (已存在跳过)")
    print(f"固定日历: {len(FIXED_CALENDAR_ENTRIES)} 条")

    if args.dry_run:
        print("--dry-run: 未写库")
        return 0

    events_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    calendar_path.write_text(json.dumps(calendar_raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"写入 -> {events_path} / {calendar_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
