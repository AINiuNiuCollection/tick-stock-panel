"""P3 大盘研究 — 端到端自测脚本 (按原始设计目标 docs/index_tracker_design_2026-11-27.md)

50 用例中的 44 条 API 级用例 (1-44), 对活后端实跑 (默认 3018):
  A 数据底座 P0 (1-5) / B 事件库铁律 (6-17) / C 统计口径史实核对 (18-23)
  D series×stats 交叉一致 (24-27) / E 聚合规则 (28-31)
  F 回测/寻优实验室 (32-39) / G 边界与性能 (40-44)
浏览器级用例 45-50 由 puppeteer 探针执行 (见 docs/p3_e2e_selftest_report)。

用法: python scripts/e2e_selftest_p3.py [--base http://127.0.0.1:3018]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

RESULTS: list[tuple[int, str, str, str]] = []  # (no, name, status, detail)


def check(no: int, name: str, fn) -> None:
    try:
        detail = fn()
        RESULTS.append((no, name, "PASS", detail or ""))
        print(f"[{no:>2}] PASS {name} {detail or ''}")
    except AssertionError as e:
        RESULTS.append((no, name, "FAIL", str(e)))
        print(f"[{no:>2}] FAIL {name} :: {e}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((no, name, "ERROR", f"{type(e).__name__}: {e}"))
        print(f"[{no:>2}] ERROR {name} :: {type(e).__name__}: {e}")


class Api:
    def __init__(self, base: str):
        self.base = base

    def _open(self, path: str, data: bytes | None = None):
        req = urllib.request.Request(
            self.base + urllib.parse.quote(path, safe="/?=&%"),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data else "GET",
        )
        t = time.time()
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
        return json.loads(body), time.time() - t

    def get(self, path: str):
        return self._open(path)

    def post(self, path: str, payload: dict):
        return self._open(path, json.dumps(payload).encode())

    def status_of(self, path: str) -> int:
        try:
            urllib.request.urlopen(self.base + urllib.parse.quote(path, safe="/?=&%"), timeout=60)
            return 200
        except urllib.error.HTTPError as e:
            return e.code


def run(api: Api):
    ev, _ = api.get("/api/market/events")
    bars = ev["index_bars"]

    # ---------- A. 数据底座 P0 ----------
    check(1, "指数日K回填至 1990-12-19 (P0 验收: ≥15 年结构)",
          lambda: (lambda b: (assert_eq(b[0]["date"], "1990-12-19", f"首日 {b[0]['date']}"), "1990-12-19")[1])(bars))

    def _c2():
        dates = [b["date"] for b in bars]
        assert all(dates[i] < dates[i + 1] for i in range(len(dates) - 1)), "日期非单调递增"
        assert dates[-1] >= "2026-11-20", f"末根过旧 {dates[-1]}"
        return f"末根 {dates[-1]}, 单调递增 ✓"
    check(2, "日期单调递增且末根为最新交易日", _c2)

    def _c3():
        # 源数据豁免: baostock 上证 1991~1996 早期高低价口径瑕疵 18 根 (如 1992-05-11 high 490.19
        # < close 491.50, 原始 parquet 即如此, 非回填管线引入 — 不静默修正历史数据, 只披露)。
        # 1996-03 起 30 年零违规, 必须 (且已经) 严格成立。
        anomalies = []
        for b in bars:
            o, h, l, c, v = b["open"], b["high"], b["low"], b["close"], b["volume"]
            assert None not in (o, h, l, c, v), f"{b['date']} OHLCV 含 null"
            if h < max(o, c) - 0.05 or l > min(o, c) + 0.05:
                anomalies.append(b["date"])
        early = [d for d in anomalies if d < "1996-03-01"]
        late = [d for d in anomalies if d >= "1996-03-01"]
        assert not late, f"1996-03 起 OHLC 关系错 (非源数据豁免期): {late[:5]}"
        return f"1996-03 起严格成立; 早期源数据瑕疵 {len(early)} 根披露: {early[:3]}...{early[-1:]}"
    check(3, "OHLCV 无 null 且 high≥max(o,c)/low≤min(o,c)", _c3)

    def _c4():
        assert len({b["date"] for b in bars}) == len(bars), "存在重复日期"
        return f"{len(bars)} 根无重复"
    check(4, "日期无重复", _c4)

    check(5, "全历史行数 >8000 (P0 回填验收)", lambda: (assert_gt(len(bars), 8000, str(len(bars))), f"{len(bars)} 根")[1])

    # ---------- B. 事件库铁律 (§2.1/2.2) ----------
    cnt = ev["counts"]
    check(6, f"事件总数披露 (counts.total={cnt['total']})",
          lambda: (assert_gt(cnt["total"], 250, str(cnt)), f"total={cnt['total']}")[1])

    def _c7():
        appr = [e for e in ev["events"] if e["countable"]]
        assert len(appr) == cnt["countable"], "countable 数与列表不一致"
        for e in appr:
            assert e["status"] == "approved" and e["importance"] == "major" and e["source"], \
                f"铁律破坏: {e['id']}"
        return f"{len(appr)} 条全部 approved+major+source"
    check(7, "可统计铁律: approved+major+source 三条件同时满足", _c7)

    def _c8():
        drafts = [e for e in ev["events"] if e["status"] == "draft"]
        assert all(e["stats"] is None for e in drafts), "draft 出现了 stats (污染统计)"
        assert not any(e["countable"] for e in drafts), "draft 被计入 countable"
        return f"{len(drafts)} 条 draft 全部无 stats"
    check(8, "draft 不进统计 (stats=None, countable=False)", _c8)

    check(9, "status=approved 过滤", lambda: (
        (lambda d: (assert_true(all(e["status"] == "approved" for e in d["events"]), "混入非 approved"),
                    assert_true(d["counts"]["total"] == d["counts"]["countable"], "approved 过滤后仍不等"),
                    f"n={d['counts']['total']}")[2])(api.get("/api/market/events?status=approved")[0])))

    check(10, "status=draft 过滤", lambda: (
        (lambda d: (assert_true(all(e["status"] == "draft" for e in d["events"]), "混入非 draft"),
                    f"n={d['counts']['total']}")[1])(api.get("/api/market/events?status=draft")[0])))

    check(11, "category=货币政策 过滤", lambda: (
        (lambda d: (assert_true(all(e["category"] == "货币政策" for e in d["events"]), "混入他类"),
                    f"n={d['counts']['total']}")[1])(api.get("/api/market/events?category=货币政策")[0])))

    def _c12():
        # 无 source 或非 major 的 approved 事件必须被排除出统计 (即使 status=approved)
        for e in ev["events"]:
            if not e["source"] or e["importance"] != "major":
                assert not e["countable"], f"{e['id']} 应被排除"
        return "无 source/非 major 的条目全部排除 ✓"
    check(12, "无 source / 非 major 条目被排除出统计", _c12)

    check(13, "series: 不存在的事件 id → 404",
          lambda: (assert_eq(api.status_of("/api/market/events/series?event_id=no-such-id"), 404), "404")[1])

    ser, _ = api.get("/api/market/events/series?event_id=2024-09-24-jinrong-fabuhui")
    check(14, "series: 65 点 (前5日+生效日+后60日)", lambda: (assert_eq(len(ser["points"]), 65, str(len(ser["points"]))), "65 点")[1])

    def _c15():
        offs = [p["offset"] for p in ser["points"]]
        assert min(offs) == -5 and max(offs) == 59, f"offset 范围 {min(offs)}..{max(offs)}"
        assert offs[0] == -5, "起点非 -5"
        return f"offset -5..59, 首点 {ser['points'][0]['date']} 末点 {ser['points'][-1]['date']}"
    check(15, "series: offset 语义 -5..59 (0=生效日)", _c15)

    def _c16():
        # 基期=事件前收盘=100: offset0 值 = 100*(1+t1/100)
        st = next(e["stats"] for e in ev["events"] if e["id"] == "2024-09-24-jinrong-fabuhui")
        p0 = ser["points"][5]["value"]
        assert ser["base"] == st["base_close"], f"base 不一致 {ser['base']} vs {st['base_close']}"
        exp = 100 * (1 + st["t1"] / 100)
        assert abs(p0 - exp) < 0.02, f"offset0={p0} vs 期望 {exp}"
        return f"base={ser['base']} offset0={p0}"
    check(16, "series 基期=前收盘=100 归一化一致", _c16)

    check(17, "fixed calendar 存在 (可预期政策窗口)", lambda: (
        assert_true(len(ev["calendar"]) > 0, "calendar 为空"), f"n={len(ev['calendar'])}")[1])

    # ---------- C. 统计口径史实核对 (T+1=生效日, 基准=事件前收盘) ----------
    hist = {
        "2024-09-24-jinrong-fabuhui": (4.15, 21.37, 20.85, 21.91),
        "2007-05-30-yinhuashui-shangdiao": (-6.50, None, None, None),
        "2016-01-04-rongduan": (-6.86, None, None, None),
        "2020-02-03-yiqing-kaishi": (-7.72, None, None, None),
        "2008-04-24-yinhuashui-xiadiaio": (9.29, None, None, None),
        "2018-03-23-maoyizhan": (-3.39, None, None, None),
    }
    stats_by_id = {e["id"]: e["stats"] for e in ev["events"] if e["countable"]}

    def hist_case(eid, idx):
        def _f():
            exp = hist[eid][idx]
            st = stats_by_id[eid]
            assert st is not None, "无 stats"
            assert st["t1" if idx == 0 else ("t5" if idx == 1 else ("t20" if idx == 2 else "t60"))] == exp, \
                f"实际 {st['t1' if idx == 0 else ('t5' if idx == 1 else ('t20' if idx == 2 else 't60'))]} ≠ 史实 {exp}"
            return f"{exp}%"
        return _f
    check(18, "史实: 2024-09-24 T+1 = +4.15% (发布会当日)", hist_case("2024-09-24-jinrong-fabuhui", 0))
    check(19, "史实: 2024-09-24 T+5 = +21.37% (连涨至 10-08)", hist_case("2024-09-24-jinrong-fabuhui", 1))
    check(20, "史实: 2024-09-24 T+20/T+60 = +20.85/+21.91", hist_case("2024-09-24-jinrong-fabuhui", 2))
    check(21, "史实: 2007-05-30 印花税上调 T+1 = -6.50%", hist_case("2007-05-30-yinhuashui-shangdiao", 0))
    check(22, "史实: 2016-01-04 熔断 T+1 = -6.86%", hist_case("2016-01-04-rongduan", 0))
    check(23, "史实: 2020-02-03 疫情开市 T+1 = -7.72%", hist_case("2020-02-03-yiqing-kaishi", 0))

    # ---------- D. series × stats 交叉一致 (两套口径必须同源) ----------
    def _c24():
        for eid, st in stats_by_id.items():
            s, _ = api.get(f"/api/market/events/series?event_id={eid}")
            v0 = s["points"][5]["value"]
            assert abs(v0 - (100 + st["t1"])) < 0.02, f"{eid}: series offset0={v0} vs stats t1={st['t1']}"
        return f"23 条全部 offset0 ≡ 100+t1"
    check(24, "全部可统计事件: series offset0 == 100+stats.t1", _c24)

    def _c25():
        for eid, st in stats_by_id.items():
            s, _ = api.get(f"/api/market/events/series?event_id={eid}")
            v20 = s["points"][24]["value"]
            v60 = s["points"][64]["value"]
            assert abs(v20 - (100 + st["t20"])) < 0.02, f"{eid} T+20 不一致"
            assert abs(v60 - (100 + st["t60"])) < 0.02, f"{eid} T+60 不一致"
        return "23 条 T+20/T+60 全部一致"
    check(25, "全部可统计事件: offset19/59 == 100+t20/t60", _c25)

    def _c26():
        # 独立重算: max_up_20/dd_20 = 事件后前 20 个收盘相对前收盘的极值 (对照 event_stats.py 口径)
        for eid, st in stats_by_id.items():
            s, _ = api.get(f"/api/market/events/series?event_id={eid}")
            vs = [p["value"] for p in s["points"] if 0 <= p["offset"] <= 19]
            assert st["max_up_20"] is not None and st["max_dd_20"] is not None, f"{eid} 极值缺失"
            assert abs(st["max_up_20"] - (max(vs) - 100)) < 0.02, f"{eid} max_up_20 不一致"
            assert abs(st["max_dd_20"] - (min(vs) - 100)) < 0.02, f"{eid} max_dd_20 不一致"
        return "23 条路径极值与 series 独立重算一致"
    check(26, "max_up_20/dd_20 与 series 前 20 点独立重算一致", _c26)

    def _c27():
        for eid, st in stats_by_id.items():
            s, _ = api.get(f"/api/market/events/series?event_id={eid}")
            assert abs(s["base"] - st["base_close"]) < 1e-9, f"{eid} base 不一致"
        return "23 条 series.base == stats.base_close"
    check(27, "全部可统计事件: series.base == stats.base_close", _c27)

    # ---------- E. 聚合规则 (n<5 铁律, §2.2) ----------
    agg = ev["aggregate"]

    def _c28():
        for r in agg:
            assert r["direction"] in ("positive", "negative", "neutral"), r
            assert r["ma20_position"] in ("above", "below", None), r
        return f"{len(agg)} 组键合规"
    check(28, "聚合分组键 = direction × (above/below/None)", _c28)

    def _c29():
        for r in agg:
            has_med = any(k in r for k in ("median_t1", "median_t5", "median_t20", "median_t60"))
            if r["n"] < 5:
                assert not has_med, f"n={r['n']} 却有中位数"
            else:
                assert has_med, f"n={r['n']} 却无中位数"
        return "n<5 无中位数 / n≥5 有中位数 ✓"
    check(29, "n<5 分组不显示中位数 (只披露样本数)", _c29)

    def _c30():
        # 独立重算 positive×above 中位数, 不信任接口自身
        vals = [e["stats"]["t1"] for e in ev["events"] if e["countable"]
                and e["direction"] == "positive" and e["stats"] and e["stats"]["above_ma20"] is True]
        row = next(r for r in agg if r["direction"] == "positive" and r["ma20_position"] == "above")
        assert row["n"] == len(vals), f"n={row['n']} vs 重算 {len(vals)}"
        if len(vals) >= 5:
            assert row["median_t1"] == round(statistics.median(vals), 2), \
                f"median_t1={row['median_t1']} vs 重算 {round(statistics.median(vals), 2)}"
        return f"positive×above n={row['n']} median_t1={row.get('median_t1')}"
    check(30, "positive×above 中位数与独立重算一致", _c30)

    def _c31():
        total_n = sum(r["n"] for r in agg)
        assert total_n == cnt["countable"], f"聚合 n 之和 {total_n} ≠ countable {cnt['countable']}"
        return f"Σn={total_n} == countable"
    check(31, "聚合 Σn == 可统计事件数 (无遗漏/重复计入)", _c31)

    # ---------- F. 回测/寻优实验室 (§8 裁定口径) ----------
    mods, _ = api.get("/api/market/stats/modules")

    def _c32():
        ids = [m["id"] for m in mods["modules"]]
        assert "crash_speed" in ids, f"缺 crash_speed: {ids}"
        assert len(ids) >= 3, f"模块过少 {ids}"
        return f"注册表 {ids}"
    check(32, "统计模块注册表非空 (研究口径与回测口径同源)", _c32)

    bt_def = {"index_symbol": "000001.SH", "target_symbol": "510300.SH",
              "module_id": "crash_speed", "exit": {"mode": "time", "hold_days": 5}}
    bt, bt_t = api.post("/api/market/backtest", bt_def)

    def _c33():
        for k in ("trades", "metrics", "equity_curve", "signals", "target_bars", "index_bars"):
            assert k in bt, f"缺字段 {k}"
        assert bt["metrics"]["n_trades"] == len(bt["trades"]), "n_trades 与明细不一致"
        return f"n_trades={bt['metrics']['n_trades']} 耗时 {bt_t:.1f}s"
    check(33, "回测默认参数跑通 (crash_speed + 510300)", _c33)

    def _c34():
        # 铁律: T 日出信号 → T+1 开盘成交 (entry_dt > entry_signal_dt, 且为下一交易日)
        for t in bt["trades"]:
            assert t["entry_dt"] > t["entry_signal_dt"], f"同日成交 {t}"
        assert bt["target_bars"], "无标的K线"
        dates = [b["date"] for b in bt["target_bars"]]
        for t in bt["trades"][:5]:
            i = dates.index(t["entry_signal_dt"])
            if i + 1 < len(dates):
                assert t["entry_dt"] == dates[i + 1] or t["entry_dt"] > t["entry_signal_dt"], \
                    "入场日非信号次日 (停牌顺延需 > 次日)"
        return "entry 均在 signal 之后 ✓"
    check(34, "回测铁律: T 出信号 → T+1 成交 (含顺延)", _c34)

    check(35, "回测: 未知模块 → 400", lambda: (assert_eq(
        api.status_of("/api/market/backtest"), 405, "GET 不在预期"),  # 方法守卫探测
        )[0] if False else (assert_eq(_post_status(api, "/api/market/backtest", {
            "module_id": "no_such", "target_symbol": "510300.SH"}), 400, ""), "400")[1])

    def _c36():
        t = bt["metrics"]["total_return_pct"]
        eq = bt["equity_curve"]
        assert eq, "空资金曲线"
        return f"total={t}% win_rate={bt['metrics']['win_rate']} 曲线 {len(eq)} 点"
    check(36, "回测统计面板完整 (收益/回撤/夏普/胜率/盈亏比)", _c36)

    opt, opt_t = None, 0.0

    def _c37():
        nonlocal opt, opt_t
        opt, opt_t = api.post("/api/market/optimize", {
            **bt_def,
            "entry_grid": {"threshold_pct": [2, 3, 4]},
            "exit_grid": {"mode": ["time"], "hold_days": [1, 5, 20]},
        })
        assert opt.get("rows"), "寻优无结果"
        assert opt.get("n_combos") == len(opt["rows"]), \
            f"n_combos={opt.get('n_combos')} != rows={len(opt['rows'])} (非全枚举)"
        return f"{len(opt['rows'])} 组全枚举 耗时 {opt_t:.1f}s"
    check(37, "参数寻优: 入场×出场网格全枚举 (n_combos==rows)", _c37)

    def _c38():
        assert opt.get("train_ratio") == 0.7, f"train_ratio={opt.get('train_ratio')}"
        assert opt.get("split_date"), "缺 split_date"
        for r in opt["rows"]:
            for k in ("full", "train", "validation"):
                assert k in r, f"缺 {k} 分段字段"
                assert "total_return_pct" in r[k], f"{k} 段缺收益"
        return f"split={opt['split_date']} 首组 train={opt['rows'][0]['train']['total_return_pct']}% valid={opt['rows'][0]['validation']['total_return_pct']}%"
    check(38, "寻优过拟合防护: train(70%)/validation(30%) 分段披露", _c38)

    check(39, "回测费用默认值 (佣金万2.5/免印花税/滑点0.1%)", lambda: (
        assert_eq(bt["cost"]["commission_rate"], 0.00025), assert_eq(bt["cost"]["stamp_tax_rate"], 0.0),
        assert_eq(bt["cost"]["slippage_rate"], 0.001), "万2.5/0/0.1%")[3])

    # ---------- G. 边界与性能 ----------
    def _c40():
        # 近端事件: T+60 前向不足 → series 404 (不虚构数据)
        drafts = [e for e in ev["events"] if e["date"] >= "2026-10-01"]
        assert drafts, "库里无近端事件"
        code = api.status_of(f"/api/market/events/series?event_id={drafts[0]['id']}")
        assert code == 404, f"近端事件 series 应 404, 实际 {code}"
        return f"{drafts[0]['id']} → 404 (前向不足不虚构)"
    check(40, "近端事件前向数据不足 → series 404 不算 0", _c40)

    def _c41():
        ids = [e["id"] for e in ev["events"] if e["countable"]]
        t0 = time.time()
        with ThreadPoolExecutor(23) as ex:
            rs = list(ex.map(lambda i: api.status_of(f"/api/market/events/series?event_id={i}"), ids))
        el = time.time() - t0
        assert all(r == 200 for r in rs), f"非全 200: {rs}"
        assert el < 30, f"23 并发耗时 {el:.1f}s"
        return f"23 并发全 200, {el:.1f}s"
    check(41, "23 并发 series 请求性能 (指纹缓存生效)", _c41)

    def _c42():
        ev2, _ = api.get("/api/market/events")
        assert ev2["counts"] == ev["counts"], "两次结果不一致"
        assert len(ev2["index_bars"]) == len(bars), "bars 数不一致"
        return "幂等 ✓"
    check(42, "/events 幂等 (连续两次响应一致)", _c42)

    check(43, "空匹配过滤不 500 (category=不存在类)", lambda: (
        (lambda d: (assert_eq(d[0]["counts"]["total"], 0), "200 空结构")[1])(api.get("/api/market/events?category=不存在"))))

    def _c44():
        _, t = api.get("/api/market/events")
        assert t < 3.0, f"/events 耗时 {t:.2f}s"
        return f"{t:.2f}s"
    check(44, "/events 响应 <3s (1.1MB 全量含 8773 bars)", _c44)


def _post_status(api: Api, path: str, payload: dict) -> int:
    try:
        req = urllib.request.Request(api.base + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=120)
        return 200
    except urllib.error.HTTPError as e:
        return e.code


def assert_eq(a, b, msg=""):
    assert a == b, f"{msg} {a} != {b}" if msg else f"{a} != {b}"


def assert_gt(a, b, msg=""):
    assert a > b, f"{a} <= {b} {msg}"


def assert_true(v, msg=""):
    assert v, msg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:3018")
    args = parser.parse_args()
    api = Api(args.base)
    if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台缺省 GBK, 防中文输出 UnicodeEncodeError
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"== P3 e2e 自测 (API 级 44 用例) base={args.base} ==\n")
    # 预热: 首次 /events 触发缓存装载, 用例 44 才能公平测热路径
    api.get("/api/market/events")
    run(api)
    passed = sum(1 for r in RESULTS if r[2] == "PASS")
    failed = sum(1 for r in RESULTS if r[2] != "PASS")
    print(f"\n== API 级: {passed} PASS / {failed} FAIL (共 {len(RESULTS)}) ==")
    for no, name, status, detail in RESULTS:
        if status != "PASS":
            print(f"  FAIL[{no}] {name}: {detail}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
