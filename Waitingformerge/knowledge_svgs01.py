"""知识库 SVG 插图生成模块。

每个函数返回一个自包含的 SVG 字符串，嵌入知识库条目的 Markdown 内容中。
所有颜色硬编码，确保在暗色/亮色模式下均可见。

颜色规范 (对齐项目):
  红涨 #C74040  绿跌 #2D9B65
  均线黄 #EAB308  均线蓝 #3B82F6
  网格 #888  文字 #AAA  背景 #1a1a1a (暗) / #FAFAFA (亮)
"""
from __future__ import annotations

# ---- 通用框架 ----

DARK_BG = "#18181B"
GRID = "rgba(255,255,255,0.06)"
GRID_LIGHT = "rgba(0,0,0,0.06)"
TEXT = "#A1A1AA"
TEXT_LIGHT = "#71717A"
BORDER = "#3F3F46"
BULL = "#C74040"
BEAR = "#2D9B65"
MA5 = "#EAB308"
MA10 = "#3B82F6"
MA20 = "#A855F7"
NEUTRAL = "#71717A"
ARROW = "#3B82F6"
ARROW_RED = "#EF4444"
ARROW_GREEN = "#10B981"
HIGHLIGHT = "#F59E0B"

def _svg_open(w: int, h: int) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" style="max-width:100%;height:auto;border-radius:6px;background:{DARK_BG};display:block;margin:0.5em 0;">'

def _svg_close() -> str:
    return "</svg>"


# ============================================================
# 1. K线基础元素
# ============================================================

def _candle(x: float, o: float, c: float, h: float, l: float, scale: float, base_y: float, w: float = 6) -> str:
    """绘制单根K线。o/c/h/l 是价格，scale 是 1元=多少px，base_y 是 0价格的Y坐标。"""
    bull = c >= o
    color = BULL if bull else BEAR
    y_h = base_y - h * scale
    y_l = base_y - l * scale
    y_o = base_y - o * scale
    y_c = base_y - c * scale
    body_top = min(y_o, y_c)
    body_h = max(abs(y_c - y_o), 1)
    hw = w / 2
    return (
        f'<line x1="{x:.1f}" y1="{y_h:.1f}" x2="{x:.1f}" y2="{y_l:.1f}" stroke="{color}" stroke-width="1"/>'
        f'<rect x="{x-hw:.1f}" y="{body_top:.1f}" width="{w}" height="{body_h:.1f}" fill="{color}"/>'
    )


def _candles_series(candles: list[tuple[float,float,float,float]], x0: float, dx: float, scale: float, base_y: float, w: float = 6) -> str:
    """批量绘制K线序列。candles=[(open, close, high, low), ...]"""
    parts = []
    for i, (o, c, h, l) in enumerate(candles):
        parts.append(_candle(x0 + i * dx, o, c, h, l, scale, base_y, w))
    return "".join(parts)


def _grid_lines(w: int, h: int, rows: int = 4) -> str:
    parts = []
    for i in range(1, rows):
        y = h * i / rows
        parts.append(f'<line x1="0" y1="{y:.0f}" x2="{w}" y2="{y:.0f}" stroke="{GRID}" stroke-width="0.5"/>')
    return "".join(parts)


def _text(x: float, y: float, text: str, size: int = 10, color: str = TEXT, anchor: str = "start") -> str:
    return f'<text x="{x:.0f}" y="{y:.0f}" fill="{color}" font-size="{size}" font-family="sans-serif" text-anchor="{anchor}">{text}</text>'


def _label_box(x: float, y: float, text: str, color: str, size: int = 9) -> str:
    w = len(text) * size * 0.65 + 8
    return (
        f'<rect x="{x:.0f}" y="{y-7:.0f}" width="{w:.0f}" height="14" fill="{color}" rx="2"/>'
        f'<text x="{x+4:.0f}" y="{y+3:.0f}" fill="#FFFFFF" font-size="{size}" font-family="sans-serif">{text}</text>'
    )


# ============================================================
# 2. 基础知识插图
# ============================================================

def svg_stock_structure() -> str:
    """股票结构示意: 公司→股份→股东。"""
    w, h = 480, 200
    parts = [_svg_open(w, h)]
    # 公司方框
    parts.append(f'<rect x="20" y="20" width="120" height="40" fill="none" stroke="{BORDER}" stroke-width="1.5" rx="4"/>')
    parts.append(_text(50, 45, "股份有限公司", 11, TEXT))
    # 分割线到股份
    parts.append(f'<line x1="140" y1="40" x2="200" y2="40" stroke="{NEUTRAL}" stroke-width="1" stroke-dasharray="3,2"/>')
    # 股份方框
    parts.append(f'<rect x="200" y="20" width="100" height="40" fill="none" stroke="{BORDER}" stroke-width="1.5" rx="4"/>')
    parts.append(_text(225, 45, "总股本", 11, TEXT))
    # 分割到股东
    parts.append(f'<line x1="300" y1="40" x2="360" y2="40" stroke="{NEUTRAL}" stroke-width="1" stroke-dasharray="3,2"/>')
    parts.append(f'<rect x="360" y="20" width="100" height="40" fill="none" stroke="{BORDER}" stroke-width="1.5" rx="4"/>')
    parts.append(_text(385, 45, "股东持有", 11, TEXT))
    # 下方要素
    items = [("面值", "票面金额"), ("市值", "股价×总股本"), ("股息", "利润分配"), ("股权", "表决/分红权")]
    for i, (k, v) in enumerate(items):
        x = 30 + i * 110
        parts.append(f'<rect x="{x}" y="100" width="95" height="50" fill="rgba(59,130,246,0.08)" stroke="{BORDER}" stroke-width="0.8" rx="3"/>')
        parts.append(_text(x + 47, 120, k, 11, ARROW, "middle"))
        parts.append(_text(x + 47, 138, v, 9, TEXT, "middle"))
    # 箭头
    parts.append(f'<path d="M 240 60 L 240 90" stroke="{NEUTRAL}" stroke-width="1" fill="none" marker-end="url(#arrowDown)"/>')
    parts.append(f'<defs><marker id="arrowDown" markerWidth="6" markerHeight="6" refX="3" refY="5" orient="auto"><path d="M0,0 L6,0 L3,5 Z" fill="{NEUTRAL}"/></marker></defs>')
    parts.append(_svg_close())
    return "".join(parts)


def svg_limit_up_down() -> str:
    """涨停/跌停示意图: K线触及涨停价/跌停价。"""
    w, h = 480, 220
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 涨停区域 (左半)
    parts.append(_text(60, 18, "涨停封板", 11, BULL))
    # 涨停价水平线
    parts.append(f'<line x1="10" y1="35" x2="220" y2="35" stroke="{BULL}" stroke-width="0.8" stroke-dasharray="4,2"/>')
    parts.append(_label_box(200, 35, "+10%", BULL))
    # K线: 大阳线触及涨停
    parts.append(_candle(40, 8, 10, 10, 7.8, 8, 115))
    parts.append(_candle(60, 9, 10, 10, 8.5, 8, 115, 5))
    parts.append(_candle(80, 9.5, 10, 10, 9, 8, 115, 5))
    parts.append(_candle(100, 9.8, 10, 10, 9.5, 8, 115, 5))
    parts.append(_candle(120, 9.9, 10, 10, 9.8, 8, 115, 5))
    parts.append(_candle(140, 9.95, 10, 10, 9.9, 8, 115, 5))
    parts.append(_candle(160, 9.97, 10, 10, 9.95, 8, 115, 5))
    parts.append(_candle(180, 9.98, 10, 10, 9.97, 8, 115, 5))
    # 封单标识
    parts.append(f'<rect x="30" y="150" width="160" height="25" fill="rgba(199,64,64,0.1)" stroke="{BULL}" stroke-width="0.5" rx="3"/>')
    parts.append(_text(110, 167, "巨量买单封死涨停", 10, BULL, "middle"))

    # 分隔线
    parts.append(f'<line x1="240" y1="10" x2="240" y2="210" stroke="{BORDER}" stroke-width="0.5"/>')

    # 跌停区域 (右半)
    parts.append(_text(310, 18, "跌停封板", 11, BEAR))
    parts.append(f'<line x1="250" y1="180" x2="460" y2="180" stroke="{BEAR}" stroke-width="0.8" stroke-dasharray="4,2"/>')
    parts.append(_label_box(415, 180, "-10%", BEAR))
    # K线: 大阴线触及跌停
    parts.append(_candle(280, 10, 8, 10.2, 7.8, 8, 215))
    parts.append(_candle(300, 8.5, 8, 8.5, 8, 8, 215, 5))
    parts.append(_candle(320, 8.2, 8, 8.2, 8, 8, 215, 5))
    parts.append(_candle(340, 8.1, 8, 8.1, 8, 8, 215, 5))
    parts.append(_candle(360, 8.05, 8, 8.05, 8, 8, 215, 5))
    parts.append(_candle(380, 8.03, 8, 8.03, 8, 8, 215, 5))
    parts.append(_candle(400, 8.02, 8, 8.02, 8, 8, 215, 5))
    parts.append(_candle(420, 8.01, 8, 8.01, 8, 8, 215, 5))
    # 封单
    parts.append(f'<rect x="270" y="45" width="160" height="25" fill="rgba(45,155,101,0.1)" stroke="{BEAR}" stroke-width="0.5" rx="3"/>')
    parts.append(_text(350, 62, "巨量卖单封死跌停", 10, BEAR, "middle"))

    parts.append(_svg_close())
    return "".join(parts)


def svg_auction_timeline() -> str:
    """集合竞价时间轴。"""
    w, h = 500, 180
    parts = [_svg_open(w, h)]
    # 时间轴
    axis_y = 100
    parts.append(f'<line x1="30" y1="{axis_y}" x2="470" y2="{axis_y}" stroke="{NEUTRAL}" stroke-width="1.5"/>')
    # 时间节点
    nodes = [
        (50, "9:15", "可接收\n可撤销", ARROW_GREEN),
        (140, "9:20", "可接收\n不可撤销", HIGHLIGHT),
        (230, "9:25", "撮合\n开盘", BULL),
        (350, "14:57", "收盘集合\n竞价开始", ARROW),
        (440, "15:00", "收盘\n撮合", BEAR),
    ]
    for x, time, label, color in nodes:
        parts.append(f'<circle cx="{x}" cy="{axis_y}" r="5" fill="{color}"/>')
        parts.append(_text(x, axis_y + 20, time, 10, TEXT, "middle"))
        for i, line in enumerate(label.split("\n")):
            parts.append(_text(x, axis_y - 20 - i * 13, line, 9, color, "middle"))
    # 上午交易时段
    parts.append(f'<rect x="240" y="95" width="100" height="10" fill="rgba(59,130,246,0.15)" rx="2"/>')
    parts.append(_text(290, 90, "连续竞价 (9:30-11:30/13:00-14:57)", 9, TEXT_LIGHT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_t_plus_1() -> str:
    """T+1交易制度示意: 买入日→次日卖出。"""
    w, h = 500, 160
    parts = [_svg_open(w, h)]
    # T日
    parts.append(f'<rect x="30" y="30" width="160" height="80" fill="rgba(59,130,246,0.08)" stroke="{BORDER}" stroke-width="1" rx="6"/>')
    parts.append(_text(110, 50, "T日 (买入日)", 12, ARROW, "middle"))
    parts.append(_text(110, 70, "✓ 可以买入", 10, TEXT, "middle"))
    parts.append(_text(110, 86, "✗ 不能卖出", 10, BEAR, "middle"))
    parts.append(_text(110, 102, "(T+1制度限制)", 9, TEXT_LIGHT, "middle"))
    # 箭头
    parts.append(f'<line x1="190" y1="70" x2="280" y2="70" stroke="{NEUTRAL}" stroke-width="1.5" marker-end="url(#arr1)"/>')
    parts.append(f'<defs><marker id="arr1" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="{NEUTRAL}"/></marker></defs>')
    parts.append(_text(235, 62, "隔夜", 9, TEXT_LIGHT, "middle"))
    # T+1日
    parts.append(f'<rect x="280" y="30" width="160" height="80" fill="rgba(199,64,64,0.08)" stroke="{BULL}" stroke-width="1" rx="6"/>')
    parts.append(_text(360, 50, "T+1日 (次日)", 12, BULL, "middle"))
    parts.append(_text(360, 70, "✓ 可以卖出", 10, BULL, "middle"))
    parts.append(_text(360, 86, "✓ 可以买入", 10, TEXT, "middle"))
    parts.append(_text(360, 102, "(资金T+1到账)", 9, TEXT_LIGHT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_ex_dividend() -> str:
    """除权除息示意: 分红后股价下调。"""
    w, h = 480, 220
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 除权前价格
    parts.append(f'<line x1="10" y1="50" x2="240" y2="50" stroke="{BULL}" stroke-width="0.6" stroke-dasharray="3,2"/>')
    parts.append(_label_box(10, 38, "20.00元", BULL))
    # K线: 除权前正常波动
    candles_before = [(19.5,20,20.2,19.3),(19.8,20.1,20.3,19.6),(19.9,20,20.2,19.7),(20,19.8,20.1,19.6)]
    parts.append(_candles_series(candles_before, 40, 30, 12, 290, 5))
    # 除权日缺口
    parts.append(f'<line x1="160" y1="10" x2="160" y2="210" stroke="{HIGHLIGHT}" stroke-width="1" stroke-dasharray="4,3"/>')
    parts.append(_text(165, 20, "除权除息日", 10, HIGHLIGHT))
    # 缺口区域 (从除权前价格 Y≈50 到除权后价格 Y≈74)
    parts.append(f'<rect x="160" y="50" width="4" height="24" fill="{HIGHLIGHT}" opacity="0.3"/>')
    # 除权后价格
    parts.append(f'<line x1="160" y1="74" x2="460" y2="74" stroke="{BEAR}" stroke-width="0.6" stroke-dasharray="3,2"/>')
    parts.append(_label_box(380, 74, "18.00元", BEAR))
    # K线: 除权后
    candles_after = [(18.2,18,18.3,17.8),(18.1,18.2,18.4,18),(18,18.1,18.3,17.9),(18.1,18,18.2,17.8)]
    parts.append(_candles_series(candles_after, 190, 30, 12, 290, 5))
    # 标注
    parts.append(_text(80, 200, "除权前", 10, TEXT, "middle"))
    parts.append(_text(310, 200, "除权后 (价格下调10%)", 10, TEXT, "middle"))
    # 箭头表示下调
    parts.append(f'<path d="M 155 52 L 155 72" stroke="{HIGHLIGHT}" stroke-width="1.5" fill="none" marker-end="url(#arrDown)"/>')
    parts.append(f'<defs><marker id="arrDown" markerWidth="6" markerHeight="6" refX="3" refY="5" orient="auto"><path d="M0,0 L6,0 L3,5 Z" fill="{HIGHLIGHT}"/></marker></defs>')
    parts.append(_svg_close())
    return "".join(parts)


def svg_margin_trading() -> str:
    """融资融券示意: 杠杆放大效应。"""
    w, h = 480, 200
    parts = [_svg_open(w, h)]
    # 融资 (左)
    parts.append(f'<rect x="20" y="20" width="200" height="160" fill="rgba(199,64,64,0.06)" stroke="{BORDER}" stroke-width="1" rx="6"/>')
    parts.append(_text(120, 40, "融资 (做多)", 12, BULL, "middle"))
    # 自有资金
    parts.append(f'<rect x="40" y="55" width="70" height="30" fill="{BULL}" opacity="0.3" rx="3"/>')
    parts.append(_text(75, 74, "自有资金", 9, TEXT, "middle"))
    # 借入资金
    parts.append(f'<rect x="120" y="55" width="70" height="30" fill="{BULL}" opacity="0.15" stroke="{BULL}" stroke-width="0.8" rx="3"/>')
    parts.append(_text(155, 74, "借入资金", 9, BULL, "middle"))
    parts.append(f'<line x1="115" y1="70" x2="120" y2="70" stroke="{BULL}" stroke-width="1"/>')
    # 杠杆效果
    parts.append(_text(120, 110, "杠杆放大收益", 10, HIGHLIGHT, "middle"))
    # 箭头向上
    parts.append(f'<path d="M 120 125 L 120 155" stroke="{BULL}" stroke-width="2" fill="none" marker-end="url(#arrUp1)"/>')
    parts.append(f'<defs><marker id="arrUp1" markerWidth="8" markerHeight="8" refX="4" refY="0" orient="auto"><path d="M0,8 L4,0 L8,8 Z" fill="{BULL}"/></marker></defs>')
    parts.append(_text(145, 145, "涨→盈利放大", 9, BULL))
    parts.append(_text(145, 160, "跌→亏损放大", 9, BEAR))

    # 融券 (右)
    parts.append(f'<rect x="260" y="20" width="200" height="160" fill="rgba(45,155,101,0.06)" stroke="{BORDER}" stroke-width="1" rx="6"/>')
    parts.append(_text(360, 40, "融券 (做空)", 12, BEAR, "middle"))
    # 借股票卖出
    parts.append(f'<rect x="280" y="55" width="70" height="30" fill="{BEAR}" opacity="0.3" rx="3"/>')
    parts.append(_text(315, 74, "借入股票", 9, TEXT, "middle"))
    parts.append(f'<rect x="360" y="55" width="70" height="30" fill="{BEAR}" opacity="0.15" stroke="{BEAR}" stroke-width="0.8" rx="3"/>')
    parts.append(_text(395, 74, "卖出得资", 9, BEAR, "middle"))
    parts.append(f'<line x1="355" y1="70" x2="360" y2="70" stroke="{BEAR}" stroke-width="1"/>')
    parts.append(_text(360, 110, "高位卖出→低位买回", 10, HIGHLIGHT, "middle"))
    parts.append(f'<path d="M 360 125 L 360 155" stroke="{BEAR}" stroke-width="2" fill="none" marker-end="url(#arrDown2)"/>')
    parts.append(f'<defs><marker id="arrDown2" markerWidth="8" markerHeight="8" refX="4" refY="8" orient="auto"><path d="M0,0 L4,8 L8,0 Z" fill="{BEAR}"/></marker></defs>')
    parts.append(_text(385, 145, "跌→获利", 9, BEAR))
    parts.append(_text(385, 160, "涨→亏损", 9, BULL))
    parts.append(_svg_close())
    return "".join(parts)


def svg_market_cap() -> str:
    """总市值 vs 流通市值示意。"""
    w, h = 480, 200
    parts = [_svg_open(w, h)]
    # 总股本 (大圆)
    parts.append(f'<circle cx="150" cy="100" r="80" fill="rgba(59,130,246,0.08)" stroke="{BORDER}" stroke-width="1.5"/>')
    parts.append(_text(150, 40, "总股本", 12, TEXT, "middle"))
    parts.append(_text(150, 170, "总市值", 10, ARROW, "middle"))
    # 流通股本 (内圆)
    parts.append(f'<circle cx="150" cy="100" r="45" fill="rgba(199,64,64,0.12)" stroke="{BULL}" stroke-width="1.5"/>')
    parts.append(_text(150, 104, "流通股本", 11, BULL, "middle"))
    # 限售股标注
    parts.append(_text(215, 80, "限售股", 9, TEXT_LIGHT))
    parts.append(f'<line x1="195" y1="83" x2="180" y2="90" stroke="{NEUTRAL}" stroke-width="0.5"/>')
    # 公式
    parts.append(_text(330, 60, "总市值", 11, ARROW))
    parts.append(_text(330, 78, "= 总股本 × 股价", 10, TEXT))
    parts.append(_text(330, 110, "流通市值", 11, BULL))
    parts.append(_text(330, 128, "= 流通股本 × 股价", 10, TEXT))
    # 分隔
    parts.append(f'<line x1="260" y1="50" x2="260" y2="160" stroke="{BORDER}" stroke-width="0.5" stroke-dasharray="3,2"/>')
    parts.append(_svg_close())
    return "".join(parts)


def svg_turnover_rate() -> str:
    """换手率示意: 不同活跃度的K线+成交量。"""
    w, h = 480, 220
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 左: 低换手 (标题放在K线上方, 用背景遮挡)
    parts.append(f'<rect x="50" y="8" width="60" height="12" fill="{DARK_BG}" opacity="0.9" rx="2"/>')
    parts.append(_text(80, 17, "低换手 (<1%)", 9, NEUTRAL, "middle"))
    candles1 = [(10,10.2,10.3,9.9),(10.1,10,10.2,9.9),(10,10.1,10.3,9.9),(10.05,10,10.2,9.95)]
    parts.append(_candles_series(candles1, 30, 25, 15, 170, 4))
    # 小量成交量
    for i in range(4):
        parts.append(f'<rect x="{25+i*25:.0f}" y="195" width="10" height="3" fill="{NEUTRAL}" opacity="0.5"/>')
    parts.append(_text(80, 215, "低迷", 9, TEXT_LIGHT, "middle"))

    # 中: 正常换手
    parts.append(f'<rect x="210" y="8" width="60" height="12" fill="{DARK_BG}" opacity="0.9" rx="2"/>')
    parts.append(_text(240, 17, "正常 (3-7%)", 9, ARROW, "middle"))
    candles2 = [(10,10.5,10.6,9.9),(10.4,10.2,10.7,10.1),(10.2,10.6,10.8,10.1),(10.5,10.3,10.7,10.2)]
    parts.append(_candles_series(candles2, 190, 25, 15, 170, 4))
    for i in range(4):
        parts.append(f'<rect x="{185+i*25:.0f}" y="{190-i*2:.0f}" width="10" height="{5+i*2}" fill="{ARROW}" opacity="0.6"/>')
    parts.append(_text(240, 215, "活跃", 9, TEXT_LIGHT, "middle"))

    # 右: 高换手
    parts.append(f'<rect x="370" y="8" width="60" height="12" fill="{DARK_BG}" opacity="0.9" rx="2"/>')
    parts.append(_text(400, 17, "高换手 (>15%)", 9, HIGHLIGHT, "middle"))
    candles3 = [(10,11,11.2,9.8),(10.8,9.5,11,9.3),(9.6,10.8,11,9.5),(10.5,9.8,11,9.6)]
    parts.append(_candles_series(candles3, 350, 25, 15, 170, 4))
    for i in range(4):
        parts.append(f'<rect x="{345+i*25:.0f}" y="{180-i*4:.0f}" width="10" height="{10+i*4}" fill="{HIGHLIGHT}" opacity="0.7"/>')
    parts.append(_text(400, 215, "异常活跃", 9, TEXT_LIGHT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_board_rotation() -> str:
    """板块轮动示意: 资金在不同板块间流动。"""
    w, h = 500, 200
    parts = [_svg_open(w, h)]
    # 板块方块
    boards = [
        (30, "科技", ARROW),
        (130, "医药", BEAR),
        (230, "金融", HIGHLIGHT),
        (330, "新能源", BULL),
        (430, "消费", NEUTRAL),
    ]
    for x, name, color in boards:
        parts.append(f'<rect x="{x}" y="60" width="60" height="40" fill="rgba(255,255,255,0.05)" stroke="{color}" stroke-width="1.2" rx="4"/>')
        parts.append(_text(x+30, 85, name, 10, color, "middle"))
    # 轮动箭头 (弧线)
    for i in range(len(boards)-1):
        x1 = boards[i][0] + 60
        x2 = boards[i+1][0]
        parts.append(f'<path d="M {x1} 80 Q {(x1+x2)/2} 40 {x2} 80" stroke="{NEUTRAL}" stroke-width="1" fill="none" marker-end="url(#arrR)"/>')
    parts.append(f'<defs><marker id="arrR" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="{NEUTRAL}"/></marker></defs>')
    # 回流箭头
    parts.append(f'<path d="M 460 100 Q 250 170 60 100" stroke="{NEUTRAL}" stroke-width="0.8" fill="none" stroke-dasharray="4,3" marker-end="url(#arrR)"/>')
    parts.append(_text(250, 155, "资金轮动", 10, TEXT_LIGHT, "middle"))
    # 时间轴
    parts.append(f'<line x1="30" y1="130" x2="490" y2="130" stroke="{BORDER}" stroke-width="0.5"/>')
    parts.append(_text(60, 145, "Day1", 8, TEXT_LIGHT, "middle"))
    parts.append(_text(160, 145, "Day2", 8, TEXT_LIGHT, "middle"))
    parts.append(_text(260, 145, "Day3", 8, TEXT_LIGHT, "middle"))
    parts.append(_text(360, 145, "Day4", 8, TEXT_LIGHT, "middle"))
    parts.append(_text(460, 145, "Day5", 8, TEXT_LIGHT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


# ============================================================
# 3. 技术指标插图
# ============================================================

def svg_ma_lines() -> str:
    """MA均线: 金叉/死叉示意。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # K线序列 (简化为小K线)
    candles = [
        (10,10.5,10.6,9.8),(10.4,10.2,10.7,10),(10.1,10.8,11,10),
        (10.7,11.2,11.3,10.5),(11.1,10.8,11.4,10.6),(10.7,11.5,11.6,10.5),
        (11.4,12,12.1,11.2),(11.8,11.5,12.2,11.3),(11.4,12.3,12.4,11.2),
        (12.2,12.8,13,12),
    ]
    parts.append(_candles_series(candles, 30, 40, 14, 200, 5))
    # MA5 折线 (黄)
    ma5_points = [None,None,None,None,(10.5+10.2+10.8+11.2+10.8)/5,
                  (10.2+10.8+11.2+10.8+11.5)/5,(10.8+11.2+10.8+11.5+12)/5,
                  (11.2+10.8+11.5+12+11.5)/5,(10.8+11.5+12+11.5+12.3)/5,
                  (11.5+12+11.5+12.3+12.8)/5]
    ma5_pts = []
    for i, v in enumerate(ma5_points):
        if v is not None:
            ma5_pts.append(f"{30+i*40:.0f},{200-v*14:.1f}")
    if len(ma5_pts) >= 2:
        parts.append(f'<polyline points="{" ".join(ma5_pts)}" fill="none" stroke="{MA5}" stroke-width="1.5" stroke-opacity="0.9"/>')
    # MA10 折线 (蓝) — 用前10根K线收盘均值的趋势线
    ma10_pts = []
    for i in range(len(candles)):
        if i < 9:
            # 前9根用已有K线的累计均值近似
            s = sum(c[1] for c in candles[:i+1]) / (i + 1)
        else:
            s = sum(c[1] for c in candles[i-9:i+1]) / 10
        ma10_pts.append((30 + i * 40, 200 - s * 14))
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.1f}" for x,y in ma10_pts)}" fill="none" stroke="{MA10}" stroke-width="1.5" stroke-opacity="0.9"/>')
    # 金叉点
    parts.append(f'<circle cx="150" cy="54" r="4" fill="{HIGHLIGHT}" stroke="#FFF" stroke-width="1"/>')
    parts.append(_text(155, 46, "金叉 (MA5上穿MA10)", 9, HIGHLIGHT))
    # 图例 (放在左上角, 避开MA线)
    parts.append(f'<rect x="8" y="8" width="62" height="32" fill="{DARK_BG}" opacity="0.85" rx="3"/>')
    parts.append(f'<line x1="12" y1="18" x2="28" y2="18" stroke="{MA5}" stroke-width="2"/>')
    parts.append(_text(32, 21, "MA5", 9, MA5))
    parts.append(f'<line x1="12" y1="32" x2="28" y2="32" stroke="{MA10}" stroke-width="2"/>')
    parts.append(_text(32, 35, "MA10", 9, MA10))
    parts.append(_svg_close())
    return "".join(parts)


def svg_macd() -> str:
    """MACD: DIF/DEA线 + 柱线 + 金叉/死叉。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 零轴
    parts.append(f'<line x1="10" y1="120" x2="490" y2="120" stroke="{NEUTRAL}" stroke-width="0.8"/>')
    parts.append(_text(15, 115, "0", 9, TEXT_LIGHT))
    # DIF线 (蓝)
    dif_pts = [(30,120-20),(60,120-15),(90,120-8),(120,120-3),(150,120+5),
               (180,120+15),(210,120+22),(240,120+18),(270,120+10),(300,120+3),
               (330,120-5),(360,120-12),(390,120-18),(420,120-15),(450,120-8)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in dif_pts)}" fill="none" stroke="{MA10}" stroke-width="1.5"/>')
    # DEA线 (黄)
    dea_pts = [(30,120-15),(60,120-12),(90,120-8),(120,120-4),(150,120+1),
               (180,120+8),(210,120+15),(240,120+17),(270,120+14),(300,120+8),
               (330,120+1),(360,120-6),(390,120-12),(420,120-14),(450,120-11)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in dea_pts)}" fill="none" stroke="{MA5}" stroke-width="1.5"/>')
    # MACD柱 (柱值=DIF-DEA, 从零轴y=120绘制)
    zero_y = 120
    for i, (x, _) in enumerate(dif_pts):
        dif_y = dif_pts[i][1]
        dea_y = dea_pts[i][1]
        # 柱高度 ∝ (DIF - DEA), y越小=值越大, 所以 dif_y-dea_y < 0 表示DIF在DEA上方=正值
        hist = dea_y - dif_y  # 正值表示DIF>DEA → 红柱(零轴上方)
        if abs(hist) < 1:
            continue
        color = BULL if hist > 0 else BEAR
        if hist > 0:
            # 红柱: 从零轴向上(y减小方向)
            top = zero_y - hist
            parts.append(f'<rect x="{x-3}" y="{top:.0f}" width="6" height="{hist:.0f}" fill="{color}" opacity="0.6"/>')
        else:
            # 绿柱: 从零轴向下(y增大方向)
            parts.append(f'<rect x="{x-3}" y="{zero_y}" width="6" height="{abs(hist):.0f}" fill="{color}" opacity="0.6"/>')
    # 金叉标注
    parts.append(f'<circle cx="150" cy="120" r="4" fill="{HIGHLIGHT}" stroke="#FFF" stroke-width="1"/>')
    parts.append(_text(155, 112, "金叉", 9, HIGHLIGHT))
    # 死叉标注
    parts.append(f'<circle cx="300" cy="120" r="4" fill="{BEAR}" stroke="#FFF" stroke-width="1"/>')
    parts.append(_text(305, 145, "死叉", 9, BEAR))
    # 图例
    parts.append(f'<line x1="380" y1="20" x2="400" y2="20" stroke="{MA10}" stroke-width="2"/>')
    parts.append(_text(405, 23, "DIF", 9, MA10))
    parts.append(f'<line x1="380" y1="35" x2="400" y2="35" stroke="{MA5}" stroke-width="2"/>')
    parts.append(_text(405, 38, "DEA", 9, MA5))
    parts.append(f'<rect x="380" y="45" width="12" height="8" fill="{BULL}" opacity="0.6"/>')
    parts.append(_text(397, 52, "MACD柱", 9, BULL))
    parts.append(_svg_close())
    return "".join(parts)


def svg_rsi() -> str:
    """RSI: 超买超卖区间。"""
    w, h = 500, 240
    parts = [_svg_open(w, h)]
    # 超买区 (80-100)
    parts.append(f'<rect x="0" y="20" width="{w}" height="40" fill="rgba(199,64,64,0.08)"/>')
    parts.append(f'<line x1="0" y1="60" x2="{w}" y2="60" stroke="{BULL}" stroke-width="0.6" stroke-dasharray="3,2"/>')
    parts.append(_text(10, 35, "超买区 (>80)", 10, BULL))
    parts.append(_text(470, 57, "80", 9, TEXT_LIGHT, "end"))
    # 中性区
    parts.append(f'<line x1="0" y1="120" x2="{w}" y2="120" stroke="{NEUTRAL}" stroke-width="0.5" stroke-dasharray="2,2"/>')
    parts.append(_text(470, 117, "50", 9, TEXT_LIGHT, "end"))
    # 超卖区 (0-20)
    parts.append(f'<rect x="0" y="180" width="{w}" height="40" fill="rgba(45,155,101,0.08)"/>')
    parts.append(f'<line x1="0" y1="180" x2="{w}" y2="180" stroke="{BEAR}" stroke-width="0.6" stroke-dasharray="3,2"/>')
    parts.append(_text(10, 215, "超卖区 (<20)", 10, BEAR))
    parts.append(_text(470, 177, "20", 9, TEXT_LIGHT, "end"))
    # RSI曲线
    rsi_pts = [(30,140),(60,125),(90,100),(120,75),(150,55),(180,45),
               (210,50),(240,65),(270,90),(300,115),(330,145),(360,170),
               (390,185),(420,175),(450,155)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in rsi_pts)}" fill="none" stroke="{ARROW}" stroke-width="2"/>')
    # 标注超买点
    parts.append(f'<circle cx="180" cy="45" r="4" fill="{BULL}"/>')
    parts.append(_text(190, 40, "触超买→回调", 9, BULL))
    # 标注超卖点
    parts.append(f'<circle cx="390" cy="185" r="4" fill="{BEAR}"/>')
    parts.append(_text(260, 200, "触超卖→反弹", 9, BEAR))
    parts.append(_svg_close())
    return "".join(parts)


def svg_kdj() -> str:
    """KDJ: K/D线 + J线。"""
    w, h = 500, 240
    parts = [_svg_open(w, h)]
    # 80/20 线
    parts.append(f'<line x1="0" y1="48" x2="{w}" y2="48" stroke="{BULL}" stroke-width="0.5" stroke-dasharray="3,2"/>')
    parts.append(_text(470, 45, "80", 9, TEXT_LIGHT, "end"))
    parts.append(f'<line x1="0" y1="192" x2="{w}" y2="192" stroke="{BEAR}" stroke-width="0.5" stroke-dasharray="3,2"/>')
    parts.append(_text(470, 189, "20", 9, TEXT_LIGHT, "end"))
    parts.append(f'<line x1="0" y1="120" x2="{w}" y2="120" stroke="{NEUTRAL}" stroke-width="0.3" stroke-dasharray="2,2"/>')
    # K线 (蓝)
    k_pts = [(30,160),(60,140),(90,100),(120,70),(150,55),(180,60),
             (210,80),(240,110),(270,140),(300,165),(330,180),(360,190),
             (390,175),(420,150),(450,120)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in k_pts)}" fill="none" stroke="{MA10}" stroke-width="1.5"/>')
    # D线 (黄)
    d_pts = [(30,170),(60,155),(90,125),(120,95),(150,75),(180,72),
             (210,85),(240,105),(270,130),(300,155),(330,172),(360,182),
             (390,178),(420,160),(450,135)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in d_pts)}" fill="none" stroke="{MA5}" stroke-width="1.5"/>')
    # J线 (紫) - 更极端
    j_pts = [(30,150),(60,120),(90,75),(120,45),(150,35),(180,45),
             (210,70),(240,105),(270,145),(300,175),(330,190),(360,200),
             (390,170),(420,135),(450,95)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in j_pts)}" fill="none" stroke="{MA20}" stroke-width="1.5"/>')
    # 金叉
    parts.append(f'<circle cx="90" cy="110" r="4" fill="{HIGHLIGHT}" stroke="#FFF" stroke-width="1"/>')
    parts.append(_text(95, 88, "金叉", 9, HIGHLIGHT))
    # 死叉
    parts.append(f'<circle cx="270" cy="135" r="4" fill="{BEAR}" stroke="#FFF" stroke-width="1"/>')
    parts.append(_text(275, 155, "死叉", 9, BEAR))
    # 图例
    parts.append(f'<line x1="370" y1="15" x2="390" y2="15" stroke="{MA10}" stroke-width="2"/>')
    parts.append(_text(395, 18, "K", 9, MA10))
    parts.append(f'<line x1="410" y1="15" x2="430" y2="15" stroke="{MA5}" stroke-width="2"/>')
    parts.append(_text(435, 18, "D", 9, MA5))
    parts.append(f'<line x1="370" y1="30" x2="390" y2="30" stroke="{MA20}" stroke-width="2"/>')
    parts.append(_text(395, 33, "J=3K-2D", 9, MA20))
    parts.append(_svg_close())
    return "".join(parts)


def svg_boll() -> str:
    """布林带: 上中下三轨 + 价格通道。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 上轨
    upper = [(30,40),(60,38),(90,42),(120,45),(150,42),(180,38),(210,35),
             (240,32),(270,35),(300,42),(330,50),(360,55),(390,52),(420,48),(450,45)]
    # 中轨 (MA20)
    mid = [(30,100),(60,98),(90,95),(120,92),(150,90),(180,88),(210,85),
           (240,82),(270,85),(300,90),(330,95),(360,100),(390,102),(420,100),(450,98)]
    # 下轨
    lower = [(30,160),(60,158),(90,155),(120,150),(150,148),(180,145),(210,142),
             (240,140),(270,145),(300,150),(330,155),(360,160),(390,165),(420,162),(450,158)]
    # 通道填充
    channel_pts = [p for p in upper] + [p for p in reversed(lower)]
    parts.append(f'<polygon points="{" ".join(f"{x},{y}" for x,y in channel_pts)}" fill="rgba(59,130,246,0.05)"/>')
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in upper)}" fill="none" stroke="{BEAR}" stroke-width="1"/>')
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in mid)}" fill="none" stroke="{MA5}" stroke-width="1" stroke-dasharray="3,2"/>')
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in lower)}" fill="none" stroke="{BULL}" stroke-width="1"/>')
    # K线
    candles = [(10.2,10.5,10.6,10),(10.4,10.3,10.7,10.1),(10.3,10.6,10.8,10.2),
               (10.5,10.9,11,10.4),(10.8,10.7,11.1,10.5),(10.6,11,11.2,10.5),
               (10.9,11.2,11.3,10.8),(11,10.8,11.3,10.7),(10.7,11,11.2,10.6),
               (10.9,10.7,11.1,10.5),(10.6,10.9,11,10.5),(10.8,10.6,11,10.4)]
    parts.append(_candles_series(candles, 40, 34, 12, 200, 4))
    # 缩口标注
    parts.append(f'<circle cx="240" cy="82" r="5" fill="none" stroke="{HIGHLIGHT}" stroke-width="1.5"/>')
    parts.append(_text(250, 75, "缩口→变盘", 9, HIGHLIGHT))
    # 图例
    parts.append(f'<line x1="370" y1="15" x2="390" y2="15" stroke="{BEAR}" stroke-width="2"/>')
    parts.append(_text(395, 18, "上轨", 9, BEAR))
    parts.append(f'<line x1="370" y1="30" x2="390" y2="30" stroke="{MA5}" stroke-width="2" stroke-dasharray="3,2"/>')
    parts.append(_text(395, 33, "中轨(MA20)", 9, MA5))
    parts.append(f'<line x1="370" y1="45" x2="390" y2="45" stroke="{BULL}" stroke-width="2"/>')
    parts.append(_text(395, 48, "下轨", 9, BULL))
    parts.append(_svg_close())
    return "".join(parts)


def svg_volume_price() -> str:
    """量价关系: 价涨量增/价涨量缩对比。"""
    w, h = 500, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 左半: 价涨量增 (健康)
    parts.append(_text(80, 18, "价涨量增 (健康)", 10, BULL))
    candles1 = [(10,10.3,10.4,9.9),(10.2,10.6,10.7,10.1),(10.5,10.9,11,10.4),
                (10.8,11.2,11.3,10.7),(11,11.5,11.6,10.9)]
    parts.append(_candles_series(candles1, 30, 30, 18, 180, 5))
    vols1 = [8, 12, 18, 25, 32]
    for i, v in enumerate(vols1):
        parts.append(f'<rect x="{25+i*30:.0f}" y="{240-v}" width="10" height="{v}" fill="{BULL}" opacity="0.6"/>')
    # 右半: 价涨量缩 (背离)
    parts.append(_text(340, 18, "价涨量缩 (背离)", 10, HIGHLIGHT))
    candles2 = [(10,10.3,10.4,9.9),(10.2,10.6,10.7,10.1),(10.5,10.9,11,10.4),
                (10.8,11.2,11.3,10.7),(11,11.5,11.6,10.9)]
    parts.append(_candles_series(candles2, 290, 30, 18, 180, 5))
    vols2 = [30, 25, 18, 12, 8]
    for i, v in enumerate(vols2):
        parts.append(f'<rect x="{285+i*30:.0f}" y="{240-v}" width="10" height="{v}" fill="{HIGHLIGHT}" opacity="0.6"/>')
    # 分隔线
    parts.append(f'<line x1="260" y1="10" x2="260" y2="250" stroke="{BORDER}" stroke-width="0.5" stroke-dasharray="3,2"/>')
    # 量能标签
    parts.append(_text(130, 255, "量", 9, TEXT_LIGHT))
    parts.append(_text(410, 255, "量", 9, TEXT_LIGHT))
    parts.append(_svg_close())
    return "".join(parts)


def svg_volume_ratio() -> str:
    """量比: 对比今日与历史平均每分钟成交量。"""
    w, h = 480, 200
    parts = [_svg_open(w, h)]
    # 过去5日平均 (左)
    parts.append(f'<rect x="30" y="40" width="150" height="120" fill="rgba(113,113,122,0.08)" stroke="{BORDER}" stroke-width="1" rx="4"/>')
    parts.append(_text(105, 30, "过去5日", 10, TEXT, "middle"))
    # 小柱状
    for i in range(5):
        parts.append(f'<rect x="{45+i*28:.0f}" y="{130-i*8:.0f}" width="16" height="{i*8+20:.0f}" fill="{NEUTRAL}" opacity="0.5" rx="2"/>')
    parts.append(_text(105, 175, "平均每分钟量", 9, TEXT_LIGHT, "middle"))

    # 今日 (右)
    parts.append(f'<rect x="250" y="40" width="200" height="120" fill="rgba(245,158,11,0.08)" stroke="{HIGHLIGHT}" stroke-width="1" rx="4"/>')
    parts.append(_text(350, 30, "今日", 10, HIGHLIGHT, "middle"))
    # 大柱状
    for i in range(5):
        parts.append(f'<rect x="{270+i*35:.0f}" y="{130-i*18:.0f}" width="22" height="{i*18+20:.0f}" fill="{HIGHLIGHT}" opacity="0.7" rx="2"/>')
    parts.append(_text(350, 175, "平均每分钟量 (显著放大)", 9, HIGHLIGHT, "middle"))

    # 量比公式
    parts.append(f'<rect x="100" y="180" width="280" height="18" fill="rgba(59,130,246,0.1)" stroke="{ARROW}" stroke-width="0.5" rx="3"/>')
    parts.append(_text(240, 193, "量比 = 今日均量 / 5日均量", 10, ARROW, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_atr() -> str:
    """ATR: 波动幅度与止损位。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # K线
    candles = [(10,10.5,11,9.5),(10.4,10.2,10.8,9.8),(10.1,10.8,11.2,9.9),
               (10.7,11.3,11.5,10.4),(11.2,10.9,11.6,10.6),(10.8,11.6,11.8,10.5),
               (11.4,11.1,12,11),(11,11.8,12.1,10.8)]
    parts.append(_candles_series(candles, 40, 50, 15, 220, 6))
    # ATR止损线 (入场价 - 2×ATR)
    entry_y = 220 - 10.7 * 15  # 入场价约10.7
    atr_stop_y = entry_y + 2 * 15 * 0.8  # 2倍ATR下方
    parts.append(f'<line x1="190" y1="{atr_stop_y:.0f}" x2="460" y2="{atr_stop_y:.0f}" stroke="{ARROW_RED}" stroke-width="1" stroke-dasharray="4,2"/>')
    parts.append(_label_box(380, atr_stop_y, "2×ATR止损", ARROW_RED))
    # 入场点
    parts.append(f'<circle cx="190" cy="{entry_y:.0f}" r="4" fill="{ARROW}"/>')
    parts.append(_text(195, entry_y - 8, "入场", 9, ARROW))
    # 波动范围标注
    parts.append(f'<line x1="465" y1="{entry_y:.0f}" x2="465" y2="{atr_stop_y:.0f}" stroke="{NEUTRAL}" stroke-width="0.8"/>')
    parts.append(_text(472, (entry_y + atr_stop_y) / 2, "ATR", 9, TEXT_LIGHT))
    parts.append(_svg_close())
    return "".join(parts)


def svg_ema_vs_sma() -> str:
    """EMA vs SMA 灵敏度对比。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # K线
    candles = [(10,10.2,10.3,9.8),(10.1,10,10.4,9.7),(9.9,10.5,10.6,9.8),
               (10.4,11,11.1,10.3),(10.9,10.7,11.2,10.5),(10.6,11.3,11.4,10.5),
               (11.2,11,11.5,10.8),(10.9,11.6,11.7,10.8)]
    parts.append(_candles_series(candles, 30, 50, 15, 210, 5))
    # SMA (灰, 滞后)
    sma_pts = [(30,210-10.1*15),(80,210-10.2*15),(130,210-10.4*15),
               (180,210-10.7*15),(230,210-10.9*15),(280,210-11.0*15),
               (330,210-11.1*15),(380,210-11.2*15)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.1f}" for x,y in sma_pts)}" fill="none" stroke="{NEUTRAL}" stroke-width="1.5"/>')
    # EMA (蓝, 灵敏)
    ema_pts = [(30,210-10.1*15),(80,210-10.3*15),(130,210-10.7*15),
               (180,210-11.0*15),(230,210-11.1*15),(280,210-11.2*15),
               (330,210-11.3*15),(380,210-11.4*15)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.1f}" for x,y in ema_pts)}" fill="none" stroke="{MA10}" stroke-width="1.5"/>')
    # 差距标注
    parts.append(f'<line x1="130" y1="{210-10.4*15:.1f}" x2="130" y2="{210-10.7*15:.1f}" stroke="{HIGHLIGHT}" stroke-width="1"/>')
    parts.append(_text(135, 85, "EMA更灵敏", 9, HIGHLIGHT))
    # 图例
    parts.append(f'<line x1="370" y1="15" x2="390" y2="15" stroke="{MA10}" stroke-width="2"/>')
    parts.append(_text(395, 18, "EMA", 9, MA10))
    parts.append(f'<line x1="370" y1="30" x2="390" y2="30" stroke="{NEUTRAL}" stroke-width="2"/>')
    parts.append(_text(395, 33, "SMA", 9, NEUTRAL))
    parts.append(_svg_close())
    return "".join(parts)


def svg_sar() -> str:
    """SAR抛物线: 止损点跟随。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 上涨段K线
    candles_up = [(10,10.3,10.4,9.9),(10.2,10.5,10.6,10.1),(10.4,10.8,10.9,10.3),
                  (10.7,11,11.1,10.6),(10.9,11.2,11.3,10.8)]
    parts.append(_candles_series(candles_up, 30, 35, 18, 200, 5))
    # SAR点 (在K线下方, 逐步上移)
    sar_up = [(30,185),(65,178),(100,170),(135,162),(170,155)]
    for x, y in sar_up:
        parts.append(f'<circle cx="{x}" cy="{y}" r="3" fill="{BULL}"/>')
    # 顶部翻转
    parts.append(f'<circle cx="205" cy="150" r="4" fill="{HIGHLIGHT}" stroke="#FFF" stroke-width="1"/>')
    parts.append(_text(210, 145, "SAR翻转", 9, HIGHLIGHT))
    # 下跌段K线
    candles_dn = [(11.2,10.9,11.3,10.8),(11,10.7,11.1,10.6),(10.8,10.5,10.9,10.4),
                  (10.6,10.3,10.7,10.2),(10.4,10.1,10.5,10)]
    parts.append(_candles_series(candles_dn, 205, 35, 18, 200, 5))
    # SAR点 (在K线上方, 逐步下移)
    sar_dn = [(205,135),(240,145),(275,155),(310,165),(345,175)]
    for x, y in sar_dn:
        parts.append(f'<circle cx="{x}" cy="{y}" r="3" fill="{BEAR}"/>')
    # 标注
    parts.append(_text(100, 210, "多头持仓 (SAR在下方)", 9, BULL, "middle"))
    parts.append(_text(310, 210, "空头持仓 (SAR在上方)", 9, BEAR, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


# ============================================================
# 4. K线形态插图
# ============================================================

def svg_hammer() -> str:
    """锤子线: 长下影线小实体。"""
    w, h = 300, 280
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 前几根下跌K线
    candles = [(10,9.5,10,9.3),(9.6,9.2,9.7,9),(9.3,8.8,9.4,8.6)]
    parts.append(_candles_series(candles, 40, 50, 25, 260, 6))
    # 锤子线
    parts.append(_candle(190, 9.0, 9.1, 9.2, 8.3, 25, 260, 7))
    # 标注
    parts.append(f'<line x1="210" y1="32" x2="230" y2="32" stroke="{HIGHLIGHT}" stroke-width="1"/>')
    parts.append(_text(235, 35, "上影线极短", 9, HIGHLIGHT))
    parts.append(f'<line x1="210" y1="40" x2="230" y2="40" stroke="{TEXT}" stroke-width="1"/>')
    parts.append(_text(235, 43, "小实体", 9, TEXT))
    parts.append(f'<line x1="210" y1="50" x2="230" y2="50" stroke="{BULL}" stroke-width="1"/>')
    parts.append(_text(235, 53, "长下影线 (≥2倍实体)", 9, BULL))
    # 箭头
    parts.append(f'<path d="M 190 270 L 190 240" stroke="{BULL}" stroke-width="1.5" fill="none" marker-end="url(#arrH)"/>')
    parts.append(f'<defs><marker id="arrH" markerWidth="6" markerHeight="6" refX="3" refY="0" orient="auto"><path d="M0,6 L3,0 L6,6 Z" fill="{BULL}"/></marker></defs>')
    parts.append(_text(150, 275, "底部反转信号", 10, BULL, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_hanging_man() -> str:
    """上吊线: 上涨末端的锤子形态。"""
    w, h = 300, 280
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 前几根上涨K线
    candles = [(9,9.5,9.6,8.9),(9.4,9.8,9.9,9.3),(9.7,10.2,10.3,9.6)]
    parts.append(_candles_series(candles, 40, 50, 25, 260, 6))
    # 上吊线 (实体在y≈260-10.2*25=5, 下影线到y≈260-9.4*25=25)
    parts.append(_candle(190, 10.1, 10.2, 10.3, 9.4, 25, 260, 7))
    # 标注 (放在右侧, 避开K线和文字)
    parts.append(f'<line x1="205" y1="8" x2="225" y2="8" stroke="{HIGHLIGHT}" stroke-width="1"/>')
    parts.append(_text(230, 11, "上影线极短", 9, HIGHLIGHT))
    parts.append(f'<line x1="205" y1="15" x2="225" y2="15" stroke="{TEXT}" stroke-width="1"/>')
    parts.append(_text(230, 18, "小实体", 9, TEXT))
    parts.append(f'<line x1="205" y1="25" x2="225" y2="25" stroke="{BEAR}" stroke-width="1"/>')
    parts.append(_text(230, 28, "长下影线", 9, BEAR))
    # 箭头向下 (从K线下方向下指, 表示反转)
    parts.append(f'<path d="M 190 35 L 190 70" stroke="{BEAR}" stroke-width="1.5" fill="none" marker-end="url(#arrHM)"/>')
    parts.append(f'<defs><marker id="arrHM" markerWidth="6" markerHeight="6" refX="3" refY="5" orient="auto"><path d="M0,0 L6,0 L3,5 Z" fill="{BEAR}"/></marker></defs>')
    parts.append(_text(150, 90, "顶部反转信号", 10, BEAR, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_engulfing() -> str:
    """吞没形态: 看涨吞没 + 看跌吞没。"""
    w, h = 500, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 看涨吞没 (左)
    parts.append(_text(120, 18, "看涨吞没", 11, BULL, "middle"))
    # 下跌趋势
    candles1 = [(10,9.5,10.1,9.3),(9.6,9.2,9.7,9)]
    parts.append(_candles_series(candles1, 40, 35, 22, 230, 5))
    # 小阴线
    parts.append(_candle(110, 9.3, 9.0, 9.4, 8.9, 22, 230, 6))
    # 大阳线吞没
    parts.append(_candle(150, 8.9, 9.6, 9.7, 8.8, 22, 230, 8))
    # 标注
    parts.append(f'<rect x="103" y="13" width="55" height="28" fill="none" stroke="{BULL}" stroke-width="1.5" stroke-dasharray="3,2" rx="2"/>')
    parts.append(_text(120, 250, "阳线实体覆盖阴线", 9, BULL, "middle"))

    # 分隔
    parts.append(f'<line x1="250" y1="10" x2="250" y2="255" stroke="{BORDER}" stroke-width="0.5"/>')

    # 看跌吞没 (右)
    parts.append(_text(370, 18, "看跌吞没", 11, BEAR, "middle"))
    # 上涨趋势
    candles2 = [(9,9.5,9.6,8.9),(9.4,9.8,9.9,9.3)]
    parts.append(_candles_series(candles2, 270, 35, 22, 230, 5))
    # 小阳线
    parts.append(_candle(340, 9.7, 10.0, 10.1, 9.6, 22, 230, 6))
    # 大阴线吞没
    parts.append(_candle(380, 10.0, 9.3, 10.1, 9.2, 22, 230, 8))
    # 标注
    parts.append(f'<rect x="333" y="4" width="55" height="28" fill="none" stroke="{BEAR}" stroke-width="1.5" stroke-dasharray="3,2" rx="2"/>')
    parts.append(_text(370, 250, "阴线实体覆盖阳线", 9, BEAR, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_doji() -> str:
    """十字星: 四种类型。"""
    w, h = 500, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    types = [
        (60, "普通十字星", "多空均衡"),
        (180, "长腿十字星", "剧烈争夺"),
        (300, "蜻蜓线(T字)", "底部信号"),
        (420, "墓碑线(倒T)", "顶部信号"),
    ]
    for x, name, desc in types:
        parts.append(_text(x, 18, name, 10, TEXT, "middle"))
        parts.append(_text(x, 240, desc, 9, HIGHLIGHT, "middle"))
        if "蜻蜓" in name:
            # T字: 只有下影线
            parts.append(f'<line x1="{x}" y1="80" x2="{x}" y2="180" stroke="{BULL}" stroke-width="1"/>')
            parts.append(f'<rect x="{x-3}" y="78" width="6" height="4" fill="{BULL}"/>')
        elif "墓碑" in name:
            # 倒T: 只有上影线
            parts.append(f'<line x1="{x}" y1="80" x2="{x}" y2="180" stroke="{BEAR}" stroke-width="1"/>')
            parts.append(f'<rect x="{x-3}" y="176" width="6" height="4" fill="{BEAR}"/>')
        elif "长腿" in name:
            # 长上下影线
            parts.append(f'<line x1="{x}" y1="60" x2="{x}" y2="200" stroke="{NEUTRAL}" stroke-width="1"/>')
            parts.append(f'<rect x="{x-3}" y="128" width="6" height="4" fill="{NEUTRAL}"/>')
        else:
            # 普通十字星
            parts.append(f'<line x1="{x}" y1="80" x2="{x}" y2="180" stroke="{NEUTRAL}" stroke-width="1"/>')
            parts.append(f'<line x1="{x-8}" y1="130" x2="{x+8}" y2="130" stroke="{NEUTRAL}" stroke-width="2"/>')
    parts.append(_svg_close())
    return "".join(parts)


def svg_morning_star() -> str:
    """早晨之星: 三K线底部反转。"""
    w, h = 400, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 第一根: 大阴线
    parts.append(_candle(60, 11, 9.5, 11.1, 9.3, 22, 240, 8))
    parts.append(_text(60, 250, "1.大阴线", 9, BEAR, "middle"))
    # 第二根: 小实体 (向下跳空)
    parts.append(_candle(140, 9.0, 9.1, 9.2, 8.8, 22, 240, 5))
    parts.append(_text(140, 250, "2.小实体", 9, NEUTRAL, "middle"))
    # 跳空缺口
    parts.append(f'<rect x="100" y="100" width="40" height="15" fill="rgba(245,158,11,0.1)" stroke="{HIGHLIGHT}" stroke-width="0.5" rx="2"/>')
    parts.append(_text(120, 112, "缺口", 8, HIGHLIGHT, "middle"))
    # 第三根: 大阳线 (深入第一根实体)
    parts.append(_candle(220, 9.2, 10.5, 10.6, 9.1, 22, 240, 8))
    parts.append(_text(220, 250, "3.大阳线", 9, BULL, "middle"))
    # 深入标注 (放在顶部, 避开K线)
    parts.append(_text(140, 15, "深入阴线50%+", 9, HIGHLIGHT, "middle"))
    # 箭头
    parts.append(f'<path d="M 280 200 L 280 100" stroke="{BULL}" stroke-width="2" fill="none" marker-end="url(#arrMS)"/>')
    parts.append(f'<defs><marker id="arrMS" markerWidth="8" markerHeight="8" refX="4" refY="0" orient="auto"><path d="M0,8 L4,0 L8,8 Z" fill="{BULL}"/></marker></defs>')
    parts.append(_text(320, 150, "反转\n向上", 10, BULL))
    parts.append(_svg_close())
    return "".join(parts)


def svg_evening_star() -> str:
    """黄昏之星: 三K线顶部反转。"""
    w, h = 400, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 第一根: 大阳线
    parts.append(_candle(60, 9, 10.5, 10.6, 8.9, 22, 240, 8))
    parts.append(_text(60, 250, "1.大阳线", 9, BULL, "middle"))
    # 第二根: 小实体 (向上跳空)
    parts.append(_candle(140, 10.7, 10.8, 10.9, 10.7, 22, 240, 5))
    parts.append(_text(140, 250, "2.小实体", 9, NEUTRAL, "middle"))
    # 跳空缺口
    parts.append(f'<rect x="100" y="90" width="40" height="15" fill="rgba(245,158,11,0.1)" stroke="{HIGHLIGHT}" stroke-width="0.5" rx="2"/>')
    parts.append(_text(120, 102, "缺口", 8, HIGHLIGHT, "middle"))
    # 第三根: 大阴线 (深入第一根实体)
    parts.append(_candle(220, 10.5, 9.2, 10.6, 9.1, 22, 240, 8))
    parts.append(_text(220, 250, "3.大阴线", 9, BEAR, "middle"))
    # 深入标注 (放在顶部, 避开K线)
    parts.append(_text(140, 15, "深入阳线50%+", 9, HIGHLIGHT, "middle"))
    # 箭头向下
    parts.append(f'<path d="M 280 100 L 280 200" stroke="{BEAR}" stroke-width="2" fill="none" marker-end="url(#arrES)"/>')
    parts.append(f'<defs><marker id="arrES" markerWidth="8" markerHeight="8" refX="4" refY="8" orient="auto"><path d="M0,0 L4,8 L8,0 Z" fill="{BEAR}"/></marker></defs>')
    parts.append(_text(320, 150, "反转\n向下", 10, BEAR))
    parts.append(_svg_close())
    return "".join(parts)


def svg_three_crows() -> str:
    """三只乌鸦: 连续三根阴线。"""
    w, h = 400, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 上涨趋势
    candles_up = [(9,9.5,9.6,8.9),(9.4,9.8,9.9,9.3),(9.7,10.2,10.3,9.6)]
    parts.append(_candles_series(candles_up, 30, 30, 22, 240, 5))
    # 三只乌鸦
    candles_dn = [(10.1,9.7,10.2,9.6),(9.8,9.3,9.9,9.2),(9.4,8.9,9.5,8.8)]
    parts.append(_candles_series(candles_dn, 150, 40, 22, 240, 6))
    # 标注
    parts.append(f'<rect x="143" y="8" width="100" height="55" fill="rgba(45,155,101,0.06)" stroke="{BEAR}" stroke-width="1" stroke-dasharray="4,2" rx="4"/>')
    parts.append(_text(193, 3, "三只乌鸦", 11, BEAR, "middle"))
    # 逐日收盘走低标注 (标记收盘价)
    for i in range(3):
        x = 156 + i * 40
        parts.append(f'<circle cx="{x}" cy="{240-candles_dn[i][1]*22:.0f}" r="3" fill="{BEAR}"/>')
    parts.append(_text(210, 250, "逐日收盘走低 → 强烈看跌", 9, BEAR, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_three_soldiers() -> str:
    """红三兵: 连续三根阳线。"""
    w, h = 400, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 下跌趋势
    candles_dn = [(10,9.5,10.1,9.3),(9.6,9.2,9.7,9),(9.3,8.8,9.4,8.6)]
    parts.append(_candles_series(candles_dn, 30, 30, 22, 240, 5))
    # 红三兵
    candles_up = [(8.9,9.3,9.4,8.8),(9.2,9.7,9.8,9.1),(9.6,10.1,10.2,9.5)]
    parts.append(_candles_series(candles_up, 150, 40, 22, 240, 6))
    # 标注
    parts.append(f'<rect x="143" y="8" width="100" height="55" fill="rgba(199,64,64,0.06)" stroke="{BULL}" stroke-width="1" stroke-dasharray="4,2" rx="4"/>')
    parts.append(_text(193, 3, "红三兵", 11, BULL, "middle"))
    # 逐日收盘走高标注 (标记收盘价)
    for i in range(3):
        x = 156 + i * 40
        parts.append(f'<circle cx="{x}" cy="{240-candles_up[i][1]*22:.0f}" r="3" fill="{BULL}"/>')
    parts.append(_text(210, 250, "逐日收盘走高 → 强烈看涨", 9, BULL, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_harami() -> str:
    """孕线: 小实体被大实体包含。"""
    w, h = 400, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 看涨孕线 (左)
    parts.append(_text(100, 18, "看涨孕线", 10, BULL, "middle"))
    # 大阴线
    parts.append(_candle(60, 10.5, 9, 10.6, 8.9, 22, 240, 8))
    # 小阳线 (在阴线实体内)
    parts.append(_candle(120, 9.3, 9.5, 9.6, 9.2, 22, 240, 4))
    # 包含框
    parts.append(f'<rect x="114" y="26" width="12" height="14" fill="none" stroke="{HIGHLIGHT}" stroke-width="1" stroke-dasharray="3,2"/>')
    parts.append(_text(100, 250, "小实体在大实体内", 9, HIGHLIGHT, "middle"))

    # 分隔
    parts.append(f'<line x1="200" y1="10" x2="200" y2="255" stroke="{BORDER}" stroke-width="0.5"/>')

    # 看跌孕线 (右)
    parts.append(_text(310, 250, "看跌孕线", 10, BEAR, "middle"))
    # 大阳线
    parts.append(_candle(240, 9, 10.5, 10.6, 8.9, 22, 240, 8))
    # 小阴线 (在阳线实体内)
    parts.append(_candle(300, 10.2, 10.0, 10.3, 9.9, 22, 240, 4))
    # 包含框
    parts.append(f'<rect x="294" y="11" width="12" height="14" fill="none" stroke="{HIGHLIGHT}" stroke-width="1" stroke-dasharray="3,2"/>')
    parts.append(_text(310, 250, "小实体在大实体内", 9, HIGHLIGHT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_long_shadow() -> str:
    """长上影线 / 长下影线。"""
    w, h = 400, 280
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 长上影线 (左) — 标题放底部避免与K线重叠
    parts.append(_text(80, 270, "长上影线", 10, BEAR, "middle"))
    parts.append(_candle(80, 10, 10.1, 11, 9.9, 22, 260, 7))
    parts.append(f'<line x1="100" y1="22" x2="120" y2="22" stroke="{BEAR}" stroke-width="1"/>')
    parts.append(_text(125, 25, "上影线长", 9, BEAR))
    parts.append(f'<line x1="100" y1="39" x2="120" y2="39" stroke="{TEXT}" stroke-width="1"/>')
    parts.append(_text(125, 42, "小实体", 9, TEXT))
    parts.append(_text(80, 250, "上方抛压重", 9, BEAR, "middle"))

    # 分隔
    parts.append(f'<line x1="200" y1="10" x2="200" y2="275" stroke="{BORDER}" stroke-width="0.5"/>')

    # 长下影线 (右)
    parts.append(_text(320, 18, "长下影线", 10, BULL, "middle"))
    parts.append(_candle(320, 10, 10.1, 10.2, 9.1, 22, 260, 7))
    parts.append(f'<line x1="340" y1="39" x2="360" y2="39" stroke="{TEXT}" stroke-width="1"/>')
    parts.append(_text(365, 42, "小实体", 9, TEXT))
    parts.append(f'<line x1="340" y1="58" x2="360" y2="58" stroke="{BULL}" stroke-width="1"/>')
    parts.append(_text(365, 61, "下影线长", 9, BULL))
    parts.append(_text(320, 250, "下方支撑强", 9, BULL, "middle"))
    parts.append(_svg_close())
    return "".join(parts)

