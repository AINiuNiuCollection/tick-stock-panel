
# ---- 以下为新增 K 线形态 ----

def svg_shooting_star() -> str:
    """射击之星: 顶部反转, 长上影线小实体。"""
    w, h = 300, 280
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 前几根上涨K线
    candles = [(9,9.5,9.6,8.9),(9.4,9.8,9.9,9.3),(9.7,10.2,10.3,9.6)]
    parts.append(_candles_series(candles, 40, 50, 25, 260, 6))
    # 射击之星 (倒锤子: 小实体在上部, 长上影线)
    parts.append(_candle(190, 10.1, 10.2, 11.0, 10.0, 25, 260, 7))
    # 标注
    parts.append(f'<line x1="210" y1="8" x2="230" y2="8" stroke="{BEAR}" stroke-width="1"/>')
    parts.append(_text(235, 11, "长上影线 (≥2倍实体)", 9, BEAR))
    parts.append(f'<line x1="210" y1="22" x2="230" y2="22" stroke="{TEXT}" stroke-width="1"/>')
    parts.append(_text(235, 25, "小实体 (上部)", 9, TEXT))
    parts.append(f'<line x1="210" y1="35" x2="230" y2="35" stroke="{HIGHLIGHT}" stroke-width="1"/>')
    parts.append(_text(235, 38, "下影线极短", 9, HIGHLIGHT))
    # 箭头向下
    parts.append(f'<path d="M 190 50 L 190 80" stroke="{BEAR}" stroke-width="1.5" fill="none" marker-end="url(#arrSS)"/>')
    parts.append(f'<defs><marker id="arrSS" markerWidth="6" markerHeight="6" refX="3" refY="5" orient="auto"><path d="M0,0 L6,0 L3,5 Z" fill="{BEAR}"/></marker></defs>')
    parts.append(_text(150, 270, "顶部反转信号", 10, BEAR, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_duo_fang_pao() -> str:
    """多方炮: 两阳夹一阴, 看涨组合。"""
    w, h = 400, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    parts.append(_text(200, 18, "多方炮 (两阳夹一阴)", 11, BULL, "middle"))
    # 趋势线 (下跌后)
    parts.append(f'<polyline points="30,200 80,185 130,170 180,160 230,140 280,120 330,100" fill="none" stroke="{NEUTRAL}" stroke-width="0.8" stroke-dasharray="3,2"/>')
    # 三根K线: 大阳 + 小阴 + 大阳
    parts.append(_candle(130, 9.5, 10.2, 10.3, 9.4, 22, 220, 10))
    parts.append(_candle(190, 10.0, 9.7, 10.1, 9.5, 22, 220, 8))
    parts.append(_candle(250, 9.8, 10.6, 10.7, 9.7, 22, 220, 10))
    # 标注 (放在K线下方, 避免超出视图)
    parts.append(_label_box(105, 220 - 9.4*22 + 12, "阳1", BULL, 8))
    parts.append(_label_box(180, 220 - 9.5*22 + 12, "阴", BEAR, 8))
    parts.append(_label_box(225, 220 - 9.7*22 + 12, "阳2", BULL, 8))
    # 括号框
    parts.append(f'<rect x="115" y="15" width="160" height="210" fill="none" stroke="{HIGHLIGHT}" stroke-width="1" stroke-dasharray="4,2" rx="4"/>')
    parts.append(_text(195, 250, "阳2收盘 > 阳1收盘 → 看涨", 9, BULL, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_kong_fang_pao() -> str:
    """空方炮: 两阴夹一阳, 看跌组合。"""
    w, h = 400, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    parts.append(_text(200, 18, "空方炮 (两阴夹一阳)", 11, BEAR, "middle"))
    # 趋势线 (上涨后)
    parts.append(f'<polyline points="30,100 80,110 130,125 180,140 230,155 280,170 330,185" fill="none" stroke="{NEUTRAL}" stroke-width="0.8" stroke-dasharray="3,2"/>')
    # 三根K线: 大阴 + 小阳 + 大阴
    parts.append(_candle(130, 10.5, 9.8, 10.6, 9.7, 22, 220, 10))
    parts.append(_candle(190, 10.0, 10.3, 10.4, 9.9, 22, 220, 8))
    parts.append(_candle(250, 10.2, 9.4, 10.3, 9.3, 22, 220, 10))
    # 标注 (放在K线下方, 避免超出视图)
    parts.append(_label_box(105, 220 - 9.7*22 + 12, "阴1", BEAR, 8))
    parts.append(_label_box(180, 220 - 9.9*22 + 12, "阳", BULL, 8))
    parts.append(_label_box(225, 220 - 9.3*22 + 12, "阴2", BEAR, 8))
    # 括号框
    parts.append(f'<rect x="115" y="15" width="160" height="210" fill="none" stroke="{HIGHLIGHT}" stroke-width="1" stroke-dasharray="4,2" rx="4"/>')
    parts.append(_text(195, 250, "阴2收盘 < 阴1收盘 → 看跌", 9, BEAR, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_top_fractal() -> str:
    """顶分形: 三根K线, 中间最高, 顶部信号。"""
    w, h = 400, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    parts.append(_text(200, 18, "顶分形", 11, BEAR, "middle"))
    # 上涨趋势
    candles = [(9.0,9.3,9.4,8.9),(9.2,9.6,9.7,9.1),(9.5,9.8,9.9,9.4),
               (9.7,10.1,10.2,9.6),(10.0,9.7,10.1,9.5),(9.6,9.3,9.7,9.1),(9.2,8.9,9.3,8.7)]
    parts.append(_candles_series(candles, 50, 45, 22, 230, 6))
    # 顶分形标注: 第4根(中间最高)
    parts.append(f'<circle cx="185" cy="{230-10.2*22:.0f}" r="6" fill="none" stroke="{BEAR}" stroke-width="1.5"/>')
    # 连接三根高点
    x1, x2, x3 = 140, 185, 230
    y1 = 230 - 9.9 * 22
    y2 = 230 - 10.2 * 22
    y3 = 230 - 10.1 * 22
    parts.append(f'<polyline points="{x1},{y1:.0f} {x2},{y2:.0f} {x3},{y3:.0f}" fill="none" stroke="{BEAR}" stroke-width="1.2"/>')
    parts.append(_text(250, 25, "中间高点最高", 9, BEAR))
    parts.append(_text(250, 38, "→ 顶分形", 9, BEAR))
    # 下跌箭头
    parts.append(f'<path d="M 185 {y2+15:.0f} L 185 {y2+40:.0f}" stroke="{BEAR}" stroke-width="1.5" fill="none" marker-end="url(#arrTF)"/>')
    parts.append(f'<defs><marker id="arrTF" markerWidth="6" markerHeight="6" refX="3" refY="5" orient="auto"><path d="M0,0 L6,0 L3,5 Z" fill="{BEAR}"/></marker></defs>')
    parts.append(_text(185, 250, "趋势可能向下", 9, BEAR, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_bottom_fractal() -> str:
    """底分形: 三根K线, 中间最低, 底部信号。"""
    w, h = 400, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    parts.append(_text(200, 18, "底分形", 11, BULL, "middle"))
    # 下跌趋势
    candles = [(10.0,9.7,10.1,9.6),(9.8,9.4,9.9,9.3),(9.5,9.2,9.6,9.1),
               (9.3,9.0,9.4,8.8),(9.1,9.4,9.5,9.0),(9.4,9.7,9.8,9.3),(9.7,10.0,10.1,9.6)]
    parts.append(_candles_series(candles, 50, 45, 22, 230, 6))
    # 底分形标注: 第4根(中间最低)
    parts.append(f'<circle cx="185" cy="{230-8.8*22:.0f}" r="6" fill="none" stroke="{BULL}" stroke-width="1.5"/>')
    # 连接三根低点
    x1, x2, x3 = 140, 185, 230
    y1 = 230 - 9.1 * 22
    y2 = 230 - 8.8 * 22
    y3 = 230 - 9.0 * 22
    parts.append(f'<polyline points="{x1},{y1:.0f} {x2},{y2:.0f} {x3},{y3:.0f}" fill="none" stroke="{BULL}" stroke-width="1.2"/>')
    parts.append(_text(250, y2 - 8, "中间低点最低", 9, BULL))
    parts.append(_text(250, y2 + 6, "→ 底分形", 9, BULL))
    # 上涨箭头
    parts.append(f'<path d="M 185 {y2-15:.0f} L 185 {y2-40:.0f}" stroke="{BULL}" stroke-width="1.5" fill="none" marker-end="url(#arrBF)"/>')
    parts.append(f'<defs><marker id="arrBF" markerWidth="6" markerHeight="6" refX="3" refY="0" orient="auto"><path d="M0,6 L3,0 L6,6 Z" fill="{BULL}"/></marker></defs>')
    parts.append(_text(185, 250, "趋势可能向上", 9, BULL, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_piercing_line() -> str:
    """刺透形态: 阴线后阳线深入阴线实体一半以上。"""
    w, h = 350, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    parts.append(_text(175, 18, "刺透形态 (Piercing Line)", 11, BULL, "middle"))
    # 前几根下跌K线
    candles_pre = [(10,9.6,10.1,9.5),(9.7,9.2,9.8,9.0),(9.3,8.8,9.4,8.6)]
    parts.append(_candles_series(candles_pre, 40, 45, 22, 230, 5))
    # 大阴线
    parts.append(_candle(175, 8.9, 8.2, 9.0, 8.0, 22, 230, 8))
    # 阳线: 开盘低于阴线最低价, 收盘深入阴线实体一半以上
    parts.append(_candle(225, 7.9, 8.7, 8.8, 7.8, 22, 230, 8))
    # 50%线
    mid_y = 230 - (8.9 + 8.2) / 2 * 22
    parts.append(f'<line x1="155" y1="{mid_y:.0f}" x2="260" y2="{mid_y:.0f}" stroke="{HIGHLIGHT}" stroke-width="0.8" stroke-dasharray="3,2"/>')
    parts.append(_text(265, mid_y + 3, "50%线", 9, HIGHLIGHT))
    # 标注
    parts.append(_label_box(148, 230 - 9.0*22 - 10, "阴线", BEAR, 8))
    parts.append(_label_box(218, 230 - 8.8*22 - 10, "阳线", BULL, 8))
    parts.append(_text(175, 250, "阳线收盘深入阴线实体50%以上", 9, BULL, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_dark_cloud() -> str:
    """乌云盖顶: 阳线后阴线深入阳线实体一半以下。"""
    w, h = 350, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    parts.append(_text(175, 250, "乌云盖顶 (Dark Cloud Cover)", 11, BEAR, "middle"))
    # 前几根上涨K线
    candles_pre = [(9.0,9.4,9.5,8.9),(9.3,9.7,9.8,9.2),(9.6,10.0,10.1,9.5)]
    parts.append(_candles_series(candles_pre, 40, 45, 22, 230, 5))
    # 大阳线
    parts.append(_candle(175, 10.0, 10.7, 10.8, 9.9, 22, 230, 8))
    # 阴线: 开盘高于阳线最高价, 收盘深入阳线实体一半以下
    parts.append(_candle(225, 10.9, 10.2, 11.0, 10.1, 22, 230, 8))
    # 50%线
    mid_y = 230 - (10.0 + 10.7) / 2 * 22
    parts.append(f'<line x1="155" y1="{mid_y:.0f}" x2="260" y2="{mid_y:.0f}" stroke="{HIGHLIGHT}" stroke-width="0.8" stroke-dasharray="3,2"/>')
    parts.append(_text(265, mid_y + 3, "50%线", 9, HIGHLIGHT))
    # 标注
    parts.append(_label_box(148, 230 - 9.9*22 + 12, "阳线", BULL, 8))
    parts.append(_label_box(218, 230 - 10.1*22 + 12, "阴线", BEAR, 8))
    parts.append(_text(175, 240, "阴线收盘深入阳线实体50%以下", 9, BEAR, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_two_crows() -> str:
    """双飞乌鸦: 阳线后两根阴线, 顶部信号。"""
    w, h = 400, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    parts.append(_text(200, 18, "双飞乌鸦 (Two Crows)", 11, BEAR, "middle"))
    # 上涨趋势
    candles_pre = [(9.0,9.4,9.5,8.9),(9.3,9.7,9.8,9.2),(9.6,10.0,10.1,9.5)]
    parts.append(_candles_series(candles_pre, 40, 40, 22, 230, 5))
    # 大阳线
    parts.append(_candle(160, 10.0, 10.5, 10.6, 9.9, 22, 230, 8))
    # 第一根阴线: 高开低走
    parts.append(_candle(210, 10.7, 10.3, 10.8, 10.2, 22, 230, 7))
    # 第二根阴线: 再次高开低走, 收盘低于前阴线
    parts.append(_candle(260, 10.5, 9.9, 10.6, 9.8, 22, 230, 7))
    # 标注
    parts.append(_label_box(138, 230 - 9.9*22 + 12, "阳线", BULL, 8))
    parts.append(_label_box(188, 230 - 10.2*22 + 12, "阴1", BEAR, 8))
    parts.append(_label_box(238, 230 - 9.8*22 + 12, "阴2", BEAR, 8))
    # 框
    parts.append(f'<rect x="145" y="15" width="140" height="210" fill="none" stroke="{HIGHLIGHT}" stroke-width="1" stroke-dasharray="4,2" rx="4"/>')
    parts.append(_text(200, 250, "两阴吃掉阳线涨幅 → 看跌", 9, BEAR, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


# ============================================================
# 5. 战法插图
# ============================================================

def svg_zhangting_board() -> str:
    """打板战法: 涨停→次日溢价。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # Day1: 涨停
    parts.append(_text(80, 15, "Day1: 涨停买入", 10, BULL))
    candles_d1 = [(9,9.5,9.6,8.9),(9.4,9.8,9.9,9.3),(9.7,10,10,9.6)]
    parts.append(_candles_series(candles_d1, 30, 30, 18, 200, 5))
    # 涨停价线
    parts.append(f'<line x1="20" y1="{200-10*18:.0f}" x2="140" y2="{200-10*18:.0f}" stroke="{BULL}" stroke-width="0.8" stroke-dasharray="3,2"/>')
    parts.append(_label_box(95, 200-10*18+12, "涨停", BULL))
    # 买入箭头
    parts.append(f'<path d="M 80 215 L 80 195" stroke="{ARROW}" stroke-width="2" fill="none" marker-end="url(#arrB1)"/>')
    parts.append(f'<defs><marker id="arrB1" markerWidth="6" markerHeight="6" refX="3" refY="0" orient="auto"><path d="M0,6 L3,0 L6,6 Z" fill="{ARROW}"/></marker></defs>')
    parts.append(_text(80, 230, "买入", 9, ARROW, "middle"))

    # 分隔
    parts.append(f'<line x1="160" y1="10" x2="160" y2="235" stroke="{BORDER}" stroke-width="0.5" stroke-dasharray="3,2"/>')

    # Day2: 高开溢价
    parts.append(_text(320, 18, "Day2: 高开卖出", 10, HIGHLIGHT))
    candles_d2 = [(10.3,10.8,11,10.2),(10.7,10.5,10.9,10.4)]
    parts.append(_candles_series(candles_d2, 200, 40, 18, 200, 5))
    # 高开缺口 (从涨停价 Y=20 到 Day2 第一根开盘价 Y≈14)
    parts.append(f'<rect x="160" y="14" width="4" height="6" fill="{HIGHLIGHT}" opacity="0.3"/>')
    parts.append(_text(170, 40, "高开溢价", 9, HIGHLIGHT))
    # 卖出箭头
    parts.append(f'<path d="M 280 170 L 280 195" stroke="{BULL}" stroke-width="2" fill="none" marker-end="url(#arrS1)"/>')
    parts.append(f'<defs><marker id="arrS1" markerWidth="6" markerHeight="6" refX="3" refY="5" orient="auto"><path d="M0,0 L6,0 L3,5 Z" fill="{BULL}"/></marker></defs>')
    parts.append(_text(280, 210, "卖出", 9, BULL, "middle"))
    # 收益标注
    parts.append(f'<rect x="360" y="170" width="120" height="20" fill="rgba(199,64,64,0.1)" stroke="{BULL}" stroke-width="0.5" rx="3"/>')
    parts.append(_text(420, 184, "收益 ≈ +8%", 10, BULL, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_low_buy() -> str:
    """低吸战法: 回调到支撑买入。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 上涨通道K线
    candles = [(10,10.5,10.6,9.9),(10.4,10.8,10.9,10.3),(10.7,11.2,11.3,10.6),
               (11.1,10.8,11.4,10.5),(10.7,10.5,11,10.3),(10.4,10.9,11,10.2),
               (10.8,11.3,11.4,10.7),(11.2,11.6,11.7,11.1),(11.5,12,12.1,11.4)]
    parts.append(_candles_series(candles, 30, 45, 14, 220, 5))
    # MA10 线
    ma_pts = [(30,220-10.3*14),(75,220-10.6*14),(120,220-10.9*14),
              (165,220-11.0*14),(210,220-10.9*14),(255,220-10.8*14),
              (300,220-11.0*14),(345,220-11.3*14),(390,220-11.6*14)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.1f}" for x,y in ma_pts)}" fill="none" stroke="{MA10}" stroke-width="1.5"/>')
    # 回调到MA10 (低吸点)
    parts.append(f'<circle cx="210" cy="{220-10.9*14:.0f}" r="5" fill="{HIGHLIGHT}" stroke="#FFF" stroke-width="1"/>')
    parts.append(_text(220, 85, "回调到MA10", 9, HIGHLIGHT))
    parts.append(_text(220, 98, "→ 低吸买入", 9, BULL))
    # 支撑标注
    parts.append(f'<line x1="165" y1="{220-10.9*14:.0f}" x2="390" y2="{220-10.9*14:.0f}" stroke="{HIGHLIGHT}" stroke-width="0.6" stroke-dasharray="3,2"/>')
    parts.append(_text(395, 85, "MA10支撑", 9, HIGHLIGHT))
    # 图例
    parts.append(f'<line x1="380" y1="15" x2="400" y2="15" stroke="{MA10}" stroke-width="2"/>')
    parts.append(_text(405, 18, "MA10", 9, MA10))
    parts.append(_svg_close())
    return "".join(parts)


def svg_breakthrough() -> str:
    """突破战法: 突破平台/前高。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 横盘K线
    candles = [(10,10.2,10.3,9.9),(10.1,10,10.4,9.8),(10,10.3,10.5,9.9),
               (10.2,10,10.4,9.8),(10.1,10.2,10.3,9.9),(10,10.1,10.4,9.8),
               (10.2,10.3,10.5,10),(10.3,10.5,10.6,10.2),(10.4,10.8,11,10.3),
               (10.7,11.2,11.4,10.6),(11.1,11.5,11.6,11)]
    parts.append(_candles_series(candles, 30, 40, 16, 210, 5))
    # 平台压力线
    parts.append(f'<line x1="10" y1="{210-10.5*16:.0f}" x2="300" y2="{210-10.5*16:.0f}" stroke="{ARROW_RED}" stroke-width="1" stroke-dasharray="4,2"/>')
    parts.append(_label_box(150, 210-10.5*16, "平台压力", ARROW_RED))
    # 突破点
    parts.append(f'<circle cx="310" cy="{210-10.8*16:.0f}" r="5" fill="{BULL}" stroke="#FFF" stroke-width="1"/>')
    parts.append(_text(320, 25, "放量突破!", 10, BULL))
    # 突破后上涨
    parts.append(f'<path d="M 310 45 L 380 20" stroke="{BULL}" stroke-width="1.5" fill="none" marker-end="url(#arrBT)"/>')
    parts.append(f'<defs><marker id="arrBT" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="{BULL}"/></marker></defs>')
    # 量能柱 (突破日放量)
    vols = [6, 5, 7, 5, 6, 5, 8, 10, 20, 25, 22]
    for i, v in enumerate(vols):
        x = 25 + i * 40
        color = BULL if v > 15 else NEUTRAL
        parts.append(f'<rect x="{x}" y="{235-v}" width="10" height="{v}" fill="{color}" opacity="0.6"/>')
    parts.append(_text(345, 220, "放量", 9, BULL, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_macd_divergence() -> str:
    """MACD底背离: 价格新低但MACD不新低。"""
    w, h = 500, 280
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 上半: 价格K线 (创新低)
    parts.append(_text(250, 15, "价格 (创新低)", 10, TEXT, "middle"))
    candles = [(10.5,10.2,10.6,10),(10.3,10.5,10.7,10.2),(10.4,10,10.5,9.8),
               (10.1,9.5,10.2,9.3),(9.6,10,10.1,9.4),(9.8,9.2,10,9),
               (9.3,8.8,9.5,8.6)]
    parts.append(_candles_series(candles, 30, 60, 12, 150, 5))
    # 价格低点标注
    parts.append(f'<circle cx="30" cy="{150-9.3*12:.0f}" r="3" fill="{BEAR}"/>')
    parts.append(f'<circle cx="390" cy="{150-8.6*12:.0f}" r="3" fill="{BEAR}"/>')
    parts.append(f'<line x1="30" y1="{150-9.3*12:.0f}" x2="390" y2="{150-8.6*12:.0f}" stroke="{BEAR}" stroke-width="1" stroke-dasharray="3,2"/>')
    parts.append(_text(200, 115, "价格创新低", 9, BEAR, "middle"))

    # 下半: MACD (不创新低)
    parts.append(f'<line x1="0" y1="220" x2="{w}" y2="220" stroke="{NEUTRAL}" stroke-width="0.5"/>')
    parts.append(_text(250, 170, "MACD (未创新低)", 10, TEXT, "middle"))
    # DIF线
    dif_pts = [(30,210),(90,205),(150,200),(210,215),(270,200),(330,195),(390,205)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in dif_pts)}" fill="none" stroke="{MA10}" stroke-width="1.5"/>')
    # 低点
    parts.append(f'<circle cx="150" cy="200" r="3" fill="{HIGHLIGHT}"/>')
    parts.append(f'<circle cx="330" cy="195" r="3" fill="{HIGHLIGHT}"/>')
    parts.append(f'<line x1="150" y1="200" x2="330" y2="195" stroke="{BULL}" stroke-width="1" stroke-dasharray="3,2"/>')
    parts.append(_text(240, 195, "MACD未创新低", 9, BULL, "middle"))
    # 背离标注
    parts.append(f'<rect x="350" y="250" width="140" height="20" fill="rgba(199,64,64,0.1)" stroke="{BULL}" stroke-width="0.5" rx="3"/>')
    parts.append(_text(420, 264, "底背离 → 见底信号", 10, BULL, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_grid_trading() -> str:
    """网格交易: 区间内分批买卖。"""
    w, h = 500, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 6)]
    # 网格线
    grid_prices = [10.0, 10.5, 11.0, 11.5, 12.0, 12.5]
    for i, p in enumerate(grid_prices):
        y = 240 - i * 35
        parts.append(f'<line x1="30" y1="{y}" x2="470" y2="{y}" stroke="{BORDER}" stroke-width="0.5"/>')
        parts.append(_text(15, y+3, f"{p:.1f}", 8, TEXT_LIGHT))
    # 价格曲线 (在网格间震荡)
    curve = [(50,240-2*35),(90,240-3*35),(130,240-1*35),(170,240-2*35),
             (210,240-4*35),(250,240-3*35),(290,240-1*35),(330,240-2*35),
             (370,240-4*35),(410,240-3*35),(450,240-2*35)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in curve)}" fill="none" stroke="{ARROW}" stroke-width="1.5"/>')
    # 买入点 (价格下穿网格, 低位)
    buy_points = [(130, 240-1*35), (290, 240-1*35), (410, 240-3*35), (450, 240-2*35)]
    for x, y in buy_points:
        parts.append(f'<circle cx="{x}" cy="{y}" r="4" fill="{BULL}"/>')
        parts.append(_text(x, y+15, "买", 8, BULL, "middle"))
    # 卖出点 (价格上穿网格, 高位)
    sell_points = [(90, 240-3*35), (210, 240-4*35), (330, 240-2*35), (370, 240-4*35)]
    for x, y in sell_points:
        parts.append(f'<circle cx="{x}" cy="{y}" r="4" fill="{BEAR}"/>')
        parts.append(_text(x, y-10, "卖", 8, BEAR, "middle"))
    # 区间标注
    parts.append(f'<line x1="470" y1="240-5*35" x2="480" y2="240-5*35" stroke="{NEUTRAL}" stroke-width="1"/>')
    parts.append(_text(485, 240-5*35+3, "上", 8, TEXT_LIGHT))
    parts.append(f'<line x1="470" y1="240-0*35" x2="480" y2="240-0*35" stroke="{NEUTRAL}" stroke-width="1"/>')
    parts.append(_text(485, 240-0*35+3, "下", 8, TEXT_LIGHT))
    parts.append(_svg_close())
    return "".join(parts)


# ============================================================
# 6. 风控插图
# ============================================================

def svg_stop_loss() -> str:
    """止损: 入场价下方设止损。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # K线
    candles = [(10,10.3,10.4,9.9),(10.2,10.5,10.6,10.1),(10.4,10.2,10.7,10),
               (10.1,10.5,10.6,10),(10.3,10,10.4,9.8),(10,9.7,10.1,9.5),
               (9.8,9.3,10,9.2)]
    parts.append(_candles_series(candles, 30, 55, 16, 210, 5))
    # 入场线
    entry_y = 210 - 10.2 * 16
    parts.append(f'<line x1="20" y1="{entry_y:.0f}" x2="470" y2="{entry_y:.0f}" stroke="{ARROW}" stroke-width="0.8" stroke-dasharray="3,2"/>')
    parts.append(_label_box(420, entry_y, "入场 10.2", ARROW, 8))
    # 止损线
    stop_y = 210 - 9.5 * 16
    parts.append(f'<line x1="20" y1="{stop_y:.0f}" x2="470" y2="{stop_y:.0f}" stroke="{ARROW_RED}" stroke-width="1" stroke-dasharray="4,2"/>')
    parts.append(_label_box(420, stop_y, "止损 9.5 (-7%)", ARROW_RED, 8))
    # 止损区间
    parts.append(f'<rect x="20" y="{entry_y:.0f}" width="450" height="{stop_y-entry_y:.0f}" fill="rgba(239,68,68,0.05)"/>')
    parts.append(_text(120, (entry_y+stop_y)/2, "最大亏损区间", 9, ARROW_RED, "middle"))
    # 触发止损箭头
    parts.append(f'<circle cx="360" cy="{210-9.2*16:.0f}" r="4" fill="{ARROW_RED}"/>')
    parts.append(_text(370, 56, "跌破止损→执行", 9, ARROW_RED))
    parts.append(_svg_close())
    return "".join(parts)


def svg_position_management() -> str:
    """仓位管理: 金字塔加仓。"""
    w, h = 480, 240
    parts = [_svg_open(w, h)]
    # 金字塔分层 (从底到顶逐层递减)
    levels = [
        (180, 200, 300, "底仓 40%", ARROW, "rgba(59,130,246,0.15)"),
        (180, 160, 240, "加仓1 25%", MA10, "rgba(59,130,246,0.12)"),
        (180, 120, 180, "加仓2 20%", MA5, "rgba(234,179,8,0.12)"),
        (180, 80, 120, "加仓3 15%", HIGHLIGHT, "rgba(245,158,11,0.12)"),
    ]
    for i, (cx, y, width, label, color, fill) in enumerate(levels):
        x1 = cx - width / 2
        parts.append(f'<rect x="{x1:.0f}" y="{y-15}" width="{width:.0f}" height="30" fill="{fill}" stroke="{color}" stroke-width="1" rx="2"/>')
        parts.append(_text(cx, y+4, label, 10, color, "middle"))

    # 箭头 (逐层递减)
    parts.append(_text(240, 30, "金字塔加仓 (越加越少)", 11, TEXT, "middle"))
    parts.append(f'<path d="M 240 50 L 240 65" stroke="{NEUTRAL}" stroke-width="1" fill="none" marker-end="url(#arrP)"/>')
    parts.append(f'<defs><marker id="arrP" markerWidth="6" markerHeight="6" refX="3" refY="5" orient="auto"><path d="M0,0 L6,0 L3,5 Z" fill="{NEUTRAL}"/></marker></defs>')
    parts.append(_svg_close())
    return "".join(parts)


def svg_loss_recovery() -> str:
    """亏损与回本: 亏损50%需盈利100%。"""
    w, h = 480, 240
    parts = [_svg_open(w, h)]
    # 柱状图: 亏损幅度 vs 需要盈利
    data = [(10, 11), (20, 25), (30, 43), (40, 67), (50, 100), (60, 150), (70, 233)]
    bar_w = 45
    gap = 10
    x0 = 40
    max_h = 160
    max_val = 233
    # 轴
    parts.append(f'<line x1="30" y1="{200}" x2="430" y2="200" stroke="{NEUTRAL}" stroke-width="1"/>')
    parts.append(f'<line x1="30" y1="40" x2="30" y2="200" stroke="{NEUTRAL}" stroke-width="1"/>')
    parts.append(_text(15, 45, "需盈利%", 9, TEXT_LIGHT))
    parts.append(_text(430, 215, "亏损%", 9, TEXT_LIGHT))
    for i, (loss, need) in enumerate(data):
        x = x0 + i * (bar_w + gap)
        h_loss = loss / max_val * max_h
        h_need = need / max_val * max_h
        # 亏损柱 (绿)
        parts.append(f'<rect x="{x}" y="{200-h_loss:.0f}" width="{bar_w/2-1}" height="{h_loss:.0f}" fill="{BEAR}" opacity="0.6"/>')
        # 需要盈利柱 (红)
        parts.append(f'<rect x="{x+bar_w/2+1}" y="{200-h_need:.0f}" width="{bar_w/2-1}" height="{h_need:.0f}" fill="{BULL}" opacity="0.6"/>')
        # 标签
        parts.append(_text(x + bar_w/2, 215, f"-{loss}%", 8, BEAR, "middle"))
        if need >= 100:
            parts.append(_text(x + bar_w/2, 200-h_need-5, f"+{need}%", 8, HIGHLIGHT, "middle"))
        else:
            parts.append(_text(x + bar_w/2, 200-h_need-5, f"+{need}%", 8, TEXT, "middle"))
    # 图例
    parts.append(f'<rect x="340" y="15" width="12" height="10" fill="{BEAR}" opacity="0.6"/>')
    parts.append(_text(356, 23, "亏损幅度", 9, TEXT))
    parts.append(f'<rect x="340" y="30" width="12" height="10" fill="{BULL}" opacity="0.6"/>')
    parts.append(_text(356, 38, "回本需要", 9, TEXT))
    # 关键标注
    parts.append(f'<rect x="30" y="50" width="170" height="20" fill="rgba(245,158,11,0.1)" stroke="{HIGHLIGHT}" stroke-width="0.5" rx="3"/>')
    parts.append(_text(115, 64, "亏50% → 需涨100%!", 10, HIGHLIGHT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_emotion_control() -> str:
    """情绪控制: 情绪→行为→后果。"""
    w, h = 500, 240
    parts = [_svg_open(w, h)]
    emotions = [
        (30, "贪婪", "加仓追高", "利润回吐", BULL),
        (130, "恐惧", "不敢买入", "错失机会", NEUTRAL),
        (230, "后悔", "报复交易", "扩大亏损", BEAR),
        (330, "自信", "加大仓位", "一次性亏光", HIGHLIGHT),
    ]
    for x, emotion, action, result, color in emotions:
        # 情绪
        parts.append(f'<rect x="{x}" y="30" width="80" height="35" fill="rgba(255,255,255,0.05)" stroke="{color}" stroke-width="1" rx="4"/>')
        parts.append(_text(x+40, 52, emotion, 11, color, "middle"))
        # 箭头
        parts.append(f'<path d="M {x+40} 68 L {x+40} 85" stroke="{NEUTRAL}" stroke-width="1" fill="none" marker-end="url(#arrE)"/>')
        # 行为
        parts.append(f'<rect x="{x}" y="90" width="80" height="30" fill="rgba(255,255,255,0.03)" stroke="{BORDER}" stroke-width="0.8" rx="3"/>')
        parts.append(_text(x+40, 109, action, 9, TEXT, "middle"))
        # 箭头
        parts.append(f'<path d="M {x+40} 123 L {x+40} 140" stroke="{NEUTRAL}" stroke-width="1" fill="none" marker-end="url(#arrE)"/>')
        # 后果
        parts.append(f'<rect x="{x}" y="145" width="80" height="30" fill="rgba(239,68,68,0.08)" stroke="{ARROW_RED}" stroke-width="0.8" rx="3"/>')
        parts.append(_text(x+40, 164, result, 9, ARROW_RED, "middle"))
    parts.append(f'<defs><marker id="arrE" markerWidth="6" markerHeight="6" refX="3" refY="5" orient="auto"><path d="M0,0 L6,0 L3,5 Z" fill="{NEUTRAL}"/></marker></defs>')
    # 底部建议
    parts.append(f'<rect x="60" y="195" width="380" height="30" fill="rgba(59,130,246,0.08)" stroke="{ARROW}" stroke-width="0.5" rx="4"/>')
    parts.append(_text(250, 214, "应对: 交易计划 + 严格执行 + 交易日志 + 适当休息", 10, ARROW, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


# ============================================================
# 7. 术语插图
# ============================================================

def svg_support_resistance() -> str:
    """支撑位/压力位: 角色转换。"""
    w, h = 500, 260
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # K线序列: 测试压力→突破→回踩(变支撑)
    candles = [
        (10,10.2,10.5,9.9),(10.1,10,10.3,9.8),(10,10.4,10.6,9.9),
        (10.3,10.1,10.5,9.9),(10.2,10.5,10.7,10),(10.4,10.2,10.6,10),
        (10.3,10.8,11,10.2),  # 突破
        (10.7,10.5,10.9,10.3),(10.4,10.7,10.8,10.2),  # 回踩
        (10.6,11,11.1,10.5),(10.9,11.3,11.4,10.8)
    ]
    parts.append(_candles_series(candles, 30, 40, 14, 230, 5))
    # 压力→支撑线
    sr_y = 230 - 10.6 * 14
    parts.append(f'<line x1="10" y1="{sr_y:.0f}" x2="270" y2="{sr_y:.0f}" stroke="{ARROW_RED}" stroke-width="1" stroke-dasharray="4,2"/>')
    parts.append(_label_box(150, sr_y, "压力位", ARROW_RED, 8))
    parts.append(f'<line x1="270" y1="{sr_y:.0f}" x2="470" y2="{sr_y:.0f}" stroke="{BULL}" stroke-width="1" stroke-dasharray="4,2"/>')
    parts.append(_label_box(420, sr_y, "支撑位", BULL, 8))
    # 突破点
    parts.append(f'<circle cx="270" cy="{sr_y:.0f}" r="5" fill="{HIGHLIGHT}" stroke="#FFF" stroke-width="1"/>')
    parts.append(_text(275, sr_y - 15, "突破后角色转换", 9, HIGHLIGHT))
    # 箭头
    parts.append(f'<path d="M 250 {sr_y+5} L 290 {sr_y+5}" stroke="{HIGHLIGHT}" stroke-width="1.5" fill="none" marker-end="url(#arrSR)"/>')
    parts.append(f'<defs><marker id="arrSR" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="{HIGHLIGHT}"/></marker></defs>')
    parts.append(_svg_close())
    return "".join(parts)


def svg_gap_types() -> str:
    """缺口类型: 普通/突破/中继/衰竭。"""
    w, h = 500, 280
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    types = [
        (0, "普通缺口", NEUTRAL, "盘整中, 短期回补"),
        (1, "突破缺口", BULL, "突破盘整, 趋势启动"),
        (2, "中继缺口", ARROW, "趋势中途, 方向延续"),
        (3, "衰竭缺口", BEAR, "趋势末端, 即将反转"),
    ]
    for idx, (row, name, color, desc) in enumerate(types):
        y_base = 50 + row * 55
        parts.append(_text(10, y_base - 5, name, 9, color))
        # 两根K线 + 缺口 (scale=4, base_y=y_base+45 保证K线在行内)
        x1 = 120
        x2 = 170
        sc = 4
        by = y_base + 45
        if row == 0:  # 普通: 小K线, 小缺口
            parts.append(_candle(x1, 10, 10.1, 10.2, 9.9, sc, by, 5))
            parts.append(_candle(x2, 10.2, 10.3, 10.4, 10.1, sc, by, 5))
            gap_y1 = by - 10.1 * sc
            gap_y2 = by - 10.2 * sc
        elif row == 1:  # 突破: 大阳线跳空
            parts.append(_candle(x1, 10, 10.2, 10.3, 9.9, sc, by, 5))
            parts.append(_candle(x2, 10.8, 11.2, 11.3, 10.7, sc, by, 6))
            gap_y1 = by - 10.3 * sc
            gap_y2 = by - 10.8 * sc
        elif row == 2:  # 中继: 上涨中跳空
            parts.append(_candle(x1, 11, 11.2, 11.3, 10.9, sc, by, 5))
            parts.append(_candle(x2, 11.5, 11.8, 11.9, 11.4, sc, by, 6))
            gap_y1 = by - 11.3 * sc
            gap_y2 = by - 11.5 * sc
        else:  # 衰竭: 高位跳空后收阴
            parts.append(_candle(x1, 12, 12.3, 12.4, 11.9, sc, by, 5))
            parts.append(_candle(x2, 12.5, 12.2, 12.6, 12.1, sc, by, 6))
            gap_y1 = by - 12.4 * sc
            gap_y2 = by - 12.5 * sc
        # 缺口区域 (确保最小高度1px可见)
        gap_h = max(abs(gap_y2 - gap_y1), 1)
        parts.append(f'<rect x="{x1+3}" y="{min(gap_y1,gap_y2):.0f}" width="{x2-x1-6}" height="{gap_h:.0f}" fill="{color}" opacity="0.2"/>')
        parts.append(_text(200, y_base + 10, desc, 9, TEXT_LIGHT))
    parts.append(_svg_close())
    return "".join(parts)


def svg_locked_in() -> str:
    """套牢/解套: 亏损状态与脱困。"""
    w, h = 480, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # K线: 高位买入后下跌
    candles = [
        (10,10.5,10.6,9.9),(10.4,10.8,10.9,10.3),(10.7,11,11.1,10.6),
        (10.9,10.5,11,10.4),(10.4,10,10.5,9.8),(10,9.5,10.1,9.3),
        (9.6,9.2,9.8,9),(9.3,8.8,9.5,8.6)
    ]
    parts.append(_candles_series(candles, 30, 50, 14, 210, 5))
    # 买入点
    buy_y = 210 - 10.8 * 14
    parts.append(f'<circle cx="130" cy="{buy_y:.0f}" r="5" fill="{ARROW}"/>')
    parts.append(_text(140, buy_y - 8, "买入 10.8", 9, ARROW))
    # 套牢区间 (buy_y < current_y in screen coords, so rect goes from buy_y to current_y)
    current_y = 210 - 8.8 * 14
    parts.append(f'<rect x="20" y="{buy_y:.0f}" width="440" height="{current_y-buy_y:.0f}" fill="rgba(239,68,68,0.06)"/>')
    parts.append(_text(120, (buy_y+current_y)/2, "套牢区间 (-18%)", 10, ARROW_RED, "middle"))
    # 当前价格
    parts.append(f'<line x1="20" y1="{current_y:.0f}" x2="460" y2="{current_y:.0f}" stroke="{BEAR}" stroke-width="0.8" stroke-dasharray="3,2"/>')
    parts.append(_label_box(410, current_y, "现价 8.8", BEAR, 8))
    # 解套方法标注
    methods = ["持股等待", "补仓摊薄", "做T降本", "止损换股"]
    for i, m in enumerate(methods):
        x = 60 + i * 100
        parts.append(f'<rect x="{x}" y="195" width="85" height="20" fill="rgba(59,130,246,0.08)" stroke="{BORDER}" stroke-width="0.5" rx="3"/>')
        parts.append(_text(x+42, 209, m, 9, ARROW, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_leader_stock() -> str:
    """龙头股: 板块中领涨。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 龙头股K线 (大幅上涨)
    candles_leader = [(10,10.5,10.6,9.9),(10.4,11,11.1,10.3),(10.8,11.5,11.6,10.7),
                      (11.3,12,12.1,11.2),(11.8,12.5,12.6,11.7)]
    parts.append(_candles_series(candles_leader, 30, 40, 13, 210, 5))
    parts.append(_text(110, 20, "龙头股 +25%", 10, BULL, "middle"))
    # 跟风股K线 (小幅上涨)
    candles_follower = [(10,10.2,10.3,9.9),(10.1,10.4,10.5,10),(10.3,10.6,10.7,10.2),
                        (10.5,10.8,10.9,10.4),(10.7,11,11.1,10.6)]
    parts.append(_candles_series(candles_follower, 250, 40, 13, 210, 5))
    parts.append(_text(330, 20, "跟风股 +10%", 10, NEUTRAL, "middle"))
    # 对比箭头
    parts.append(f'<path d="M 200 130 L 240 130" stroke="{HIGHLIGHT}" stroke-width="1.5" fill="none" marker-end="url(#arrL)"/>')
    parts.append(f'<defs><marker id="arrL" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="{HIGHLIGHT}"/></marker></defs>')
    parts.append(_text(220, 122, "对比", 9, HIGHLIGHT, "middle"))
    # 特征
    parts.append(_text(110, 200, "涨幅最大 · 封板最快 · 辨识度最高", 9, BULL, "middle"))
    parts.append(_text(330, 200, "涨幅较小 · 跟风上涨", 9, NEUTRAL, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_bias() -> str:
    """乖离率: 价格偏离均线。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # K线
    candles = [(10,10.3,10.4,9.9),(10.2,10.6,10.7,10.1),(10.5,11,11.1,10.4),
               (10.8,11.4,11.5,10.7),(11.2,11.8,12,11.1),(11.6,12.2,12.3,11.5)]
    parts.append(_candles_series(candles, 30, 65, 12, 220, 5))
    # MA20 线
    ma_y = 220 - 10.5 * 12
    parts.append(f'<line x1="20" y1="{ma_y:.0f}" x2="460" y2="{ma_y:.0f}" stroke="{MA5}" stroke-width="1.5" stroke-dasharray="4,2"/>')
    parts.append(_label_box(420, ma_y, "MA20", MA5, 8))
    # 价格当前位置
    current_y = 220 - 12.2 * 12
    parts.append(f'<line x1="350" y1="{current_y:.0f}" x2="460" y2="{current_y:.0f}" stroke="{BULL}" stroke-width="0.8" stroke-dasharray="3,2"/>')
    parts.append(_label_box(420, current_y, "现价 12.2", BULL, 8))
    # 乖离距离标注
    parts.append(f'<line x1="430" y1="{current_y:.0f}" x2="430" y2="{ma_y:.0f}" stroke="{HIGHLIGHT}" stroke-width="1.5"/>')
    parts.append(_text(440, (current_y + ma_y) / 2, "乖离", 9, HIGHLIGHT))
    # 计算公式
    parts.append(f'<rect x="100" y="180" width="300" height="22" fill="rgba(59,130,246,0.1)" stroke="{ARROW}" stroke-width="0.5" rx="3"/>')
    parts.append(_text(250, 195, "BIAS = (12.2 - 10.5) / 10.5 × 100% = +16.2%", 10, ARROW, "middle"))
    # 超买标注
    parts.append(f'<rect x="100" y="150" width="300" height="22" fill="rgba(245,158,11,0.1)" stroke="{HIGHLIGHT}" stroke-width="0.5" rx="3"/>')
    parts.append(_text(250, 165, "乖离过大 → 回调风险高", 10, HIGHLIGHT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_dragon_tiger() -> str:
    """龙虎榜: 买卖前5席位。"""
    w, h = 500, 260
    parts = [_svg_open(w, h)]
    # 标题
    parts.append(_text(250, 20, "龙虎榜 (买卖前5席位)", 12, TEXT, "middle"))
    # 买入方 (左)
    parts.append(f'<rect x="20" y="35" width="220" height="200" fill="rgba(199,64,64,0.06)" stroke="{BULL}" stroke-width="1" rx="6"/>')
    parts.append(_text(130, 52, "买入 TOP5", 11, BULL, "middle"))
    buyers = ["机构专用", "知名游资A", "量化基金", "游资B", "营业部X"]
    for i, name in enumerate(buyers):
        y = 65 + i * 30
        color = ARROW if "机构" in name else (HIGHLIGHT if "游资" in name else NEUTRAL)
        parts.append(f'<rect x="35" y="{y}" width="190" height="25" fill="rgba(255,255,255,0.03)" stroke="{BORDER}" stroke-width="0.5" rx="3"/>')
        parts.append(_text(45, y + 17, f"{i+1}. {name}", 10, color))
        amount = ["8000万", "5000万", "3000万", "2000万", "1000万"][i]
        parts.append(_text(215, y + 17, amount, 9, TEXT_LIGHT, "end"))

    # 卖出方 (右)
    parts.append(f'<rect x="260" y="35" width="220" height="200" fill="rgba(45,155,101,0.06)" stroke="{BEAR}" stroke-width="1" rx="6"/>')
    parts.append(_text(370, 52, "卖出 TOP5", 11, BEAR, "middle"))
    sellers = ["游资C", "营业部Y", "量化基金", "机构专用", "营业部Z"]
    for i, name in enumerate(sellers):
        y = 65 + i * 30
        color = ARROW if "机构" in name else (HIGHLIGHT if "游资" in name else NEUTRAL)
        parts.append(f'<rect x="275" y="{y}" width="190" height="25" fill="rgba(255,255,255,0.03)" stroke="{BORDER}" stroke-width="0.5" rx="3"/>')
        parts.append(_text(285, y + 17, f"{i+1}. {name}", 10, color))
        amount = ["6000万", "4000万", "2500万", "1500万", "800万"][i]
        parts.append(_text(455, y + 17, amount, 9, TEXT_LIGHT, "end"))
    parts.append(_svg_close())
    return "".join(parts)


# ============================================================
# 7. 宏观经济插图
# ============================================================

def svg_fed_rate() -> str:
    """美联储加息/降息周期示意。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 利率曲线
    # 加息周期 (左) → 利率上升
    # 高点 → 降息周期 (右) → 利率下降
    pts = [(30,200),(60,195),(90,185),(120,170),(150,150),(180,125),
           (210,100),(240,85),(270,80),(300,85),(330,100),
           (360,120),(390,145),(420,165),(450,180),(480,190)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in pts)}" fill="none" stroke="{ARROW}" stroke-width="2"/>')
    # 加息区间标注
    parts.append(f'<rect x="30" y="20" width="210" height="220" fill="rgba(199,64,64,0.04)" stroke="none"/>')
    parts.append(_text(135, 25, "加息周期", 10, BULL, "middle"))
    parts.append(f'<path d="M 60 195 L 240 80" stroke="{BULL}" stroke-width="0" />')
    # 降息区间标注
    parts.append(f'<rect x="260" y="20" width="220" height="220" fill="rgba(45,155,101,0.04)" stroke="none"/>')
    parts.append(_text(370, 25, "降息周期", 10, BEAR, "middle"))
    # 峰值标注
    parts.append(f'<circle cx="270" cy="80" r="4" fill="{HIGHLIGHT}" stroke="#FFF" stroke-width="1"/>')
    parts.append(_text(270, 68, "利率峰值", 9, HIGHLIGHT, "middle"))
    # Y轴标注
    parts.append(_text(10, 45, "高", 8, TEXT_LIGHT))
    parts.append(_text(10, 200, "低", 8, TEXT_LIGHT))
    parts.append(_text(490, 215, "时间", 8, TEXT_LIGHT))
    # 箭头
    parts.append(f'<path d="M 100 160 L 150 130" stroke="{BULL}" stroke-width="1.5" fill="none" marker-end="url(#arrFed1)"/>')
    parts.append(f'<defs><marker id="arrFed1" markerWidth="6" markerHeight="6" refX="3" refY="0" orient="auto"><path d="M0,6 L3,0 L6,6 Z" fill="{BULL}"/></marker></defs>')
    parts.append(_text(85, 140, "加息", 9, BULL))
    parts.append(f'<path d="M 320 110 L 370 150" stroke="{BEAR}" stroke-width="1.5" fill="none" marker-end="url(#arrFed2)"/>')
    parts.append(f'<defs><marker id="arrFed2" markerWidth="6" markerHeight="6" refX="3" refY="5" orient="auto"><path d="M0,0 L6,0 L3,5 Z" fill="{BEAR}"/></marker></defs>')
    parts.append(_text(335, 140, "降息", 9, BEAR))
    parts.append(_svg_close())
    return "".join(parts)


def svg_nonfarm() -> str:
    """非农就业数据示意: 就业人数变化柱状图。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 柱状图: 6个月非农数据
    data = [(-30, "3月"), (180, "4月"), (150, "5月"), (200, "6月"), (-70, "7月"), (120, "8月")]
    bar_w = 45
    gap = 20
    x0 = 40
    zero_y = 130
    max_val = 250
    max_h = 90
    # 零轴
    parts.append(f'<line x1="20" y1="{zero_y}" x2="480" y2="{zero_y}" stroke="{NEUTRAL}" stroke-width="1"/>')
    parts.append(_text(15, zero_y + 3, "0", 8, TEXT_LIGHT, "end"))
    # 柱子
    for i, (val, label) in enumerate(data):
        x = x0 + i * (bar_w + gap)
        bar_h = abs(val) / max_val * max_h
        if val >= 0:
            color = BULL
            parts.append(f'<rect x="{x}" y="{zero_y - bar_h:.0f}" width="{bar_w}" height="{bar_h:.0f}" fill="{color}" opacity="0.7" rx="2"/>')
            parts.append(_text(x + bar_w/2, zero_y - bar_h - 5, f"+{val}K", 8, BULL, "middle"))
        else:
            color = BEAR
            parts.append(f'<rect x="{x}" y="{zero_y}" width="{bar_w}" height="{bar_h:.0f}" fill="{color}" opacity="0.7" rx="2"/>')
            parts.append(_text(x + bar_w/2, zero_y + bar_h + 12, f"{val}K", 8, BEAR, "middle"))
        parts.append(_text(x + bar_w/2, 225, label, 9, TEXT, "middle"))
    # 标题
    parts.append(_text(250, 18, "非农就业人数变化 (千人)", 11, TEXT, "middle"))
    # 预期线
    parts.append(f'<line x1="20" y1="{zero_y - 150/250*90:.0f}" x2="480" y2="{zero_y - 150/250*90:.0f}" stroke="{HIGHLIGHT}" stroke-width="0.8" stroke-dasharray="4,3"/>')
    parts.append(_text(475, zero_y - 150/250*90 - 5, "预期 +150K", 8, HIGHLIGHT, "end"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_pmi() -> str:
    """PMI 景气指数: 围绕50荣枯线波动。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 50荣枯线
    y50 = 120
    parts.append(f'<line x1="20" y1="{y50}" x2="480" y2="{y50}" stroke="{HIGHLIGHT}" stroke-width="1" stroke-dasharray="5,3"/>')
    parts.append(_text(475, y50 - 5, "50 荣枯线", 9, HIGHLIGHT, "end"))
    # PMI 曲线 (围绕50波动)
    pts = [(30,160),(70,150),(110,135),(150,115),(190,95),(230,85),
           (270,90),(310,105),(350,125),(390,140),(430,150),(470,145)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in pts)}" fill="none" stroke="{ARROW}" stroke-width="2"/>')
    # 扩张区间 (>50) 阴影
    parts.append(f'<rect x="20" y="20" width="460" height="{y50-20}" fill="rgba(199,64,64,0.05)" />')
    parts.append(_text(40, 35, "扩张区 (>50)", 9, BULL))
    # 收缩区间 (<50) 阴影
    parts.append(f'<rect x="20" y="{y50}" width="460" height="200-{y50}" fill="rgba(45,155,101,0.05)" />')
    parts.append(_text(40, 220, "收缩区 (<50)", 9, BEAR))
    # 数据点标注
    parts.append(f'<circle cx="230" cy="85" r="3" fill="{BULL}"/>')
    parts.append(_text(230, 75, "52.6", 8, BULL, "middle"))
    parts.append(f'<circle cx="390" cy="140" r="3" fill="{BEAR}"/>')
    parts.append(_text(390, 155, "49.1", 8, BEAR, "middle"))
    # Y轴
    parts.append(_text(15, 45, "54", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 85, "52", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 160, "48", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 200, "46", 8, TEXT_LIGHT, "end"))
    # 标题
    parts.append(_text(250, 14, "PMI 走势", 11, TEXT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_m1_m2() -> str:
    """M1/M2 货币供应量增速走势。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # M2 (蓝线) — 平稳增长
    m2_pts = [(30,170),(70,165),(110,155),(150,145),(190,135),(230,120),
              (270,110),(310,105),(350,100),(390,95),(430,90),(470,85)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in m2_pts)}" fill="none" stroke="{MA10}" stroke-width="2"/>')
    # M1 (红线) — 波动较大
    m1_pts = [(30,190),(70,180),(110,165),(150,150),(190,140),(230,155),
              (270,175),(310,165),(350,145),(390,130),(430,120),(470,110)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in m1_pts)}" fill="none" stroke="{BULL}" stroke-width="2"/>')
    # 剪刀差标注 (M2增速 - M1增速)
    parts.append(f'<rect x="200" y="140" width="60" height="30" fill="rgba(245,158,11,0.1)" stroke="{HIGHLIGHT}" stroke-width="0.5" rx="2"/>')
    parts.append(_text(230, 158, "剪刀差", 8, HIGHLIGHT, "middle"))
    # 图例
    parts.append(f'<line x1="350" y1="20" x2="370" y2="20" stroke="{MA10}" stroke-width="2"/>')
    parts.append(_text(375, 23, "M2增速", 9, MA10))
    parts.append(f'<line x1="350" y1="35" x2="370" y2="35" stroke="{BULL}" stroke-width="2"/>')
    parts.append(_text(375, 38, "M1增速", 9, BULL))
    # Y轴
    parts.append(_text(15, 45, "15%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 120, "10%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 200, "5%", 8, TEXT_LIGHT, "end"))
    # 标题
    parts.append(_text(250, 14, "M1 / M2 增速走势", 11, TEXT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_cpi_ppi() -> str:
    """CPI / PPI 通胀指标走势。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 零轴
    zero_y = 120
    parts.append(f'<line x1="20" y1="{zero_y}" x2="480" y2="{zero_y}" stroke="{NEUTRAL}" stroke-width="1"/>')
    parts.append(_text(15, zero_y + 3, "0", 8, TEXT_LIGHT, "end"))
    # CPI (红线) — 在零轴上方波动
    cpi_pts = [(30,90),(70,75),(110,65),(150,55),(190,70),(230,85),
               (270,100),(310,115),(350,125),(390,130),(430,120),(470,110)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in cpi_pts)}" fill="none" stroke="{BULL}" stroke-width="2"/>')
    # PPI (蓝线) — 更低，可能为负
    ppi_pts = [(30,110),(70,125),(110,140),(150,155),(190,160),(230,150),
               (270,135),(310,125),(350,130),(390,140),(430,135),(470,125)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in ppi_pts)}" fill="none" stroke="{MA10}" stroke-width="2"/>')
    # 通胀区标注
    parts.append(f'<rect x="20" y="20" width="460" height="{zero_y-20}" fill="rgba(199,64,64,0.04)" />')
    parts.append(_text(40, 35, "通胀 (CPI > 0)", 9, BULL))
    parts.append(f'<rect x="20" y="{zero_y}" width="460" height="100" fill="rgba(45,155,101,0.04)" />')
    parts.append(_text(40, 220, "通缩 (CPI < 0)", 9, BEAR))
    # 图例
    parts.append(f'<line x1="350" y1="20" x2="370" y2="20" stroke="{BULL}" stroke-width="2"/>')
    parts.append(_text(375, 23, "CPI", 9, BULL))
    parts.append(f'<line x1="350" y1="35" x2="370" y2="35" stroke="{MA10}" stroke-width="2"/>')
    parts.append(_text(375, 38, "PPI", 9, MA10))
    # 标题
    parts.append(_text(250, 14, "CPI / PPI 同比走势", 11, TEXT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_social_financing() -> str:
    """社融规模: 新增社融与存量增速。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 柱状图: 季度新增社融 (万亿)
    quarters = [("Q1", 12), ("Q2", 8), ("Q3", 7), ("Q4", 5), ("Q1", 15), ("Q2", 9)]
    bar_w = 50
    gap = 18
    x0 = 35
    max_val = 16
    max_h = 140
    base_y = 210
    for i, (q, val) in enumerate(quarters):
        x = x0 + i * (bar_w + gap)
        bh = val / max_val * max_h
        color = ARROW if i < 4 else HIGHLIGHT
        parts.append(f'<rect x="{x}" y="{base_y - bh:.0f}" width="{bar_w}" height="{bh:.0f}" fill="{color}" opacity="0.6" rx="2"/>')
        parts.append(_text(x + bar_w/2, base_y - 5, f"{val}", 8, "#FFFFFF", "middle"))
        parts.append(_text(x + bar_w/2, base_y + 15, q, 8, TEXT_LIGHT, "middle"))
    # 存量增速线 (右轴)
    growth_pts = [(60,180),(128,170),(196,160),(264,155),(332,145),(400,140)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in growth_pts)}" fill="none" stroke="{BULL}" stroke-width="2" stroke-dasharray="4,2"/>')
    parts.append(_text(410, 138, "存量增速", 8, BULL))
    # 标题
    parts.append(_text(250, 14, "新增社融 (万亿)", 11, TEXT, "middle"))
    parts.append(_text(15, 40, "16", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 210, "0", 8, TEXT_LIGHT, "end"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_lpr() -> str:
    """LPR 利率: 1年期与5年期走势。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 1年期LPR (红线) — 从3.85%降到3.10%
    lpr1_pts = [(30,60),(70,65),(110,72),(150,80),(190,90),(230,100),
                (270,110),(310,120),(350,130),(390,140),(430,150),(470,155)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in lpr1_pts)}" fill="none" stroke="{BULL}" stroke-width="2"/>')
    # 5年期LPR (蓝线) — 从4.65%降到3.60%
    lpr5_pts = [(30,30),(70,35),(110,42),(150,52),(190,65),(230,78),
                (270,92),(310,105),(350,118),(390,128),(430,138),(470,145)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in lpr5_pts)}" fill="none" stroke="{MA10}" stroke-width="2"/>')
    # 降幅标注
    parts.append(f'<path d="M 480 60 L 480 145" stroke="{HIGHLIGHT}" stroke-width="0.8" fill="none"/>')
    parts.append(_text(485, 100, "↓", 12, HIGHLIGHT, "middle"))
    # 图例
    parts.append(f'<line x1="320" y1="20" x2="340" y2="20" stroke="{BULL}" stroke-width="2"/>')
    parts.append(_text(345, 23, "1年期LPR", 9, BULL))
    parts.append(f'<line x1="320" y1="35" x2="340" y2="35" stroke="{MA10}" stroke-width="2"/>')
    parts.append(_text(345, 38, "5年期LPR", 9, MA10))
    # Y轴
    parts.append(_text(15, 30, "4.8%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 120, "3.8%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 200, "2.8%", 8, TEXT_LIGHT, "end"))
    # 标题
    parts.append(_text(250, 14, "LPR 利率走势", 11, TEXT, "middle"))
    parts.append(_text(470, 220, "时间", 8, TEXT_LIGHT))
    parts.append(_svg_close())
    return "".join(parts)


def svg_rmb_exchange() -> str:
    """人民币汇率: 美元/人民币走势。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 汇率曲线: 美元/人民币 (升值→贬值→升值)
    pts = [(30,170),(60,160),(90,150),(120,140),(150,130),(180,120),
           (210,110),(240,100),(270,95),(300,100),(330,115),
           (360,135),(390,155),(420,165),(450,155),(480,140)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in pts)}" fill="none" stroke="{ARROW}" stroke-width="2"/>')
    # 升值区标注
    parts.append(f'<rect x="20" y="20" width="250" height="220" fill="rgba(199,64,64,0.04)" stroke="none"/>')
    parts.append(_text(145, 25, "人民币升值", 9, BULL, "middle"))
    # 贬值区标注
    parts.append(f'<rect x="270" y="20" width="210" height="220" fill="rgba(45,155,101,0.04)" stroke="none"/>')
    parts.append(_text(375, 25, "人民币贬值", 9, BEAR, "middle"))
    # 关键点
    parts.append(f'<circle cx="270" cy="95" r="4" fill="{HIGHLIGHT}" stroke="#FFF" stroke-width="1"/>')
    parts.append(_text(270, 85, "6.20", 8, HIGHLIGHT, "middle"))
    parts.append(f'<circle cx="390" cy="155" r="4" fill="{HIGHLIGHT}" stroke="#FFF" stroke-width="1"/>')
    parts.append(_text(390, 170, "7.30", 8, HIGHLIGHT, "middle"))
    # Y轴标注
    parts.append(_text(15, 50, "7.5", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 120, "6.8", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 200, "6.0", 8, TEXT_LIGHT, "end"))
    # 标题
    parts.append(_text(250, 14, "美元/人民币汇率", 11, TEXT, "middle"))
    parts.append(_text(470, 220, "时间", 8, TEXT_LIGHT))
    parts.append(_svg_close())
    return "".join(parts)


def svg_quantitative_easing() -> str:
    """量化宽松: 央行资产负债表扩张。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 资产负债表规模 (面积图)
    pts = [(30,200),(60,198),(90,195),(120,190),(150,180),
           (180,150),(210,110),(240,80),(270,65),(300,70),
           (330,85),(360,95),(390,90),(420,80),(450,75),(480,78)]
    # 填充区域
    area_pts = pts + [(480, 210), (30, 210)]
    parts.append(f'<polygon points="{" ".join(f"{x},{y}" for x,y in area_pts)}" fill="{ARROW}" opacity="0.15"/>')
    parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in pts)}" fill="none" stroke="{ARROW}" stroke-width="2"/>')
    # QE阶段标注
    parts.append(f'<rect x="160" y="20" width="120" height="220" fill="rgba(245,158,11,0.06)" stroke="none"/>')
    parts.append(_text(220, 25, "QE 扩表", 9, HIGHLIGHT, "middle"))
    # 缩表阶段
    parts.append(f'<rect x="310" y="20" width="80" height="220" fill="rgba(45,155,101,0.06)" stroke="none"/>')
    parts.append(_text(350, 25, "QT 缩表", 9, BEAR, "middle"))
    # 峰值标注
    parts.append(f'<circle cx="270" cy="65" r="4" fill="{HIGHLIGHT}" stroke="#FFF" stroke-width="1"/>')
    parts.append(_text(270, 55, "峰值", 8, HIGHLIGHT, "middle"))
    # Y轴
    parts.append(_text(15, 45, "9万亿", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 120, "5万亿", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 200, "1万亿", 8, TEXT_LIGHT, "end"))
    # 标题
    parts.append(_text(250, 14, "央行资产负债表 (美元)", 11, TEXT, "middle"))
    parts.append(_text(470, 220, "时间", 8, TEXT_LIGHT))
    parts.append(_svg_close())
    return "".join(parts)


def svg_treasury_yield() -> str:
    """国债收益率曲线: 正常/倒挂。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 左半: 正常曲线 (向上倾斜)
    parts.append(_text(120, 18, "正常曲线", 10, BULL, "middle"))
    normal_pts = [(40,190),(70,160),(100,135),(130,115),(160,100),(190,88),(220,78)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in normal_pts)}" fill="none" stroke="{BULL}" stroke-width="2"/>')
    # 右半: 倒挂曲线 (向下倾斜)
    parts.append(_text(360, 18, "倒挂曲线", 10, BEAR, "middle"))
    inverted_pts = [(280,80),(310,85),(340,100),(370,120),(400,145),(430,165),(460,180)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in inverted_pts)}" fill="none" stroke="{BEAR}" stroke-width="2"/>')
    # 分隔线
    parts.append(f'<line x1="250" y1="10" x2="250" y2="230" stroke="{BORDER}" stroke-width="0.5" stroke-dasharray="3,2"/>')
    # X轴标注 (期限)
    for x, label in [(40,"1M"),(100,"1Y"),(160,"5Y"),(220,"30Y"),(280,"1M"),(340,"1Y"),(400,"5Y"),(460,"30Y")]:
        parts.append(_text(x, 225, label, 8, TEXT_LIGHT, "middle"))
    # Y轴
    parts.append(_text(15, 45, "5%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 120, "3%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 200, "1%", 8, TEXT_LIGHT, "end"))
    # 箭头
    parts.append(_text(135, 140, "长期>短期", 8, BULL, "middle"))
    parts.append(_text(375, 110, "短期>长期", 8, BEAR, "middle"))
    # 标题
    parts.append(_text(250, 14, "国债收益率曲线", 11, TEXT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


# ---- 以下为新增宏观经济指标 ----

def svg_dxy() -> str:
    """美元指数: 一篮子货币加权的美元强弱。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 100 基准线
    y100 = 90
    parts.append(f'<line x1="20" y1="{y100}" x2="480" y2="{y100}" stroke="{HIGHLIGHT}" stroke-width="0.8" stroke-dasharray="4,3"/>')
    parts.append(_text(475, y100 - 5, "100", 9, HIGHLIGHT, "end"))
    # DXY 曲线: 先弱后强
    pts = [(30,170),(70,160),(110,145),(150,130),(190,110),(230,95),
           (270,80),(310,70),(350,65),(390,72),(430,85),(470,95)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in pts)}" fill="none" stroke="{ARROW}" stroke-width="2"/>')
    # 强弱区间
    parts.append(f'<rect x="20" y="20" width="460" height="{y100-20}" fill="rgba(199,64,64,0.04)"/>')
    parts.append(_text(40, 35, "强势区 (>100)", 9, BULL))
    parts.append(f'<rect x="20" y="{y100}" width="460" height="200-{y100}" fill="rgba(45,155,101,0.04)"/>')
    parts.append(_text(40, 215, "弱势区 (<100)", 9, BEAR))
    # 关键点标注
    parts.append(f'<circle cx="350" cy="65" r="3" fill="{BULL}"/>')
    parts.append(_text(350, 55, "114.5", 8, BULL, "middle"))
    parts.append(f'<circle cx="30" cy="170" r="3" fill="{BEAR}"/>')
    parts.append(_text(35, 185, "89.0", 8, BEAR))
    # Y轴
    parts.append(_text(15, 45, "115", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 215, "85", 8, TEXT_LIGHT, "end"))
    # 货币篮子
    parts.append(_text(250, 14, "美元指数 (DXY)", 11, TEXT, "middle"))
    parts.append(_text(250, 230, "EUR 57.6% · JPY 13.6% · GBP 11.9% · CAD 9.1% · SEK 4.2% · CHF 3.6%", 7, TEXT_LIGHT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_vix() -> str:
    """VIX 恐慌指数: 波动率与市场情绪。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 阈值线
    y20, y30 = 140, 100
    parts.append(f'<line x1="20" y1="{y20}" x2="480" y2="{y20}" stroke="{NEUTRAL}" stroke-width="0.6" stroke-dasharray="3,2"/>')
    parts.append(_text(475, y20 - 3, "20 正常偏高", 8, NEUTRAL, "end"))
    parts.append(f'<line x1="20" y1="{y30}" x2="480" y2="{y30}" stroke="{ARROW_RED}" stroke-width="0.8" stroke-dasharray="4,3"/>')
    parts.append(_text(475, y30 - 3, "30 恐慌", 8, ARROW_RED, "end"))
    # VIX 曲线: 长期低位 → 突然飙升
    pts = [(30,175),(70,170),(110,165),(150,160),(190,155),(220,150),
           (250,120),(270,70),(290,50),(310,60),(340,85),(370,110),(400,135),(430,150),(470,160)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in pts)}" fill="none" stroke="{ARROW}" stroke-width="2"/>')
    # 恐慌峰值标注
    parts.append(f'<circle cx="290" cy="50" r="4" fill="{ARROW_RED}"/>')
    parts.append(_text(290, 40, "VIX 80+", 8, ARROW_RED, "middle"))
    parts.append(_text(290, 30, "2008/2020 危机", 7, TEXT_LIGHT, "middle"))
    # 情绪区间标注
    parts.append(f'<rect x="20" y="155" width="460" height="45" fill="rgba(45,155,101,0.05)"/>')
    parts.append(_text(40, 220, "低波动 <15 (自满)", 8, BEAR))
    parts.append(f'<rect x="20" y="50" width="460" height="50" fill="rgba(239,68,68,0.05)"/>')
    parts.append(_text(350, 45, "高波动 >30 (恐慌)", 8, ARROW_RED))
    # Y轴
    parts.append(_text(15, 45, "80", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 120, "30", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 175, "15", 8, TEXT_LIGHT, "end"))
    parts.append(_text(250, 14, "VIX 恐慌指数", 11, TEXT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_credit_spread() -> str:
    """信用利差: 信用债与国债收益率之差。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 国债收益率 (蓝线, 稳定)
    treasury_pts = [(30,160),(70,158),(110,155),(150,153),(190,150),
                    (230,148),(270,145),(310,143),(350,142),(390,140),(430,138),(470,137)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in treasury_pts)}" fill="none" stroke="{MA10}" stroke-width="1.5"/>')
    # 高收益债收益率 (红线, 波动大)
    hy_pts = [(30,120),(70,115),(110,110),(150,105),(190,100),
              (230,80),(270,55),(310,45),(350,60),(390,80),(430,95),(470,105)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in hy_pts)}" fill="none" stroke="{BULL}" stroke-width="2"/>')
    # 信用利差填充
    spread_pts = treasury_pts + [(p[0], p[1]) for p in reversed(hy_pts)]
    parts.append(f'<polygon points="{" ".join(f"{x},{y:.0f}" for x,y in spread_pts)}" fill="rgba(245,158,11,0.1)"/>')
    # 利差标注
    parts.append(f'<line x1="290" y1="45" x2="290" y2="144" stroke="{HIGHLIGHT}" stroke-width="0.8"/>')
    parts.append(_text(300, 90, "利差扩大", 9, HIGHLIGHT))
    parts.append(_text(300, 103, "→ 风险厌恶", 8, ARROW_RED))
    # 图例
    parts.append(f'<line x1="330" y1="20" x2="350" y2="20" stroke="{MA10}" stroke-width="2"/>')
    parts.append(_text(355, 23, "国债", 9, MA10))
    parts.append(f'<line x1="330" y1="35" x2="350" y2="35" stroke="{BULL}" stroke-width="2"/>')
    parts.append(_text(355, 38, "高收益债", 9, BULL))
    # Y轴
    parts.append(_text(15, 45, "8%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 120, "4%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 210, "1%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(250, 14, "信用利差 (国债 vs 高收益债)", 11, TEXT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_oil_crude() -> str:
    """原油价格: WTI/Brent 走势与供需。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # WTI (红线)
    wti_pts = [(30,60),(70,70),(110,85),(150,100),(190,120),(230,140),
               (270,165),(310,180),(350,170),(390,145),(430,115),(470,90)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in wti_pts)}" fill="none" stroke="{BULL}" stroke-width="2"/>')
    # Brent (蓝线)
    brent_pts = [(30,55),(70,65),(110,78),(150,92),(190,112),(230,132),
                 (270,155),(310,170),(350,162),(390,138),(430,108),(470,85)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in brent_pts)}" fill="none" stroke="{MA10}" stroke-width="2"/>')
    # 负油价事件
    parts.append(f'<circle cx="310" cy="180" r="4" fill="{ARROW_RED}"/>')
    parts.append(_text(315, 195, "2020负油价", 7, ARROW_RED))
    # OPEC+ 减产标注
    parts.append(f'<line x1="350" y1="10" x2="350" y2="230" stroke="{HIGHLIGHT}" stroke-width="0.6" stroke-dasharray="3,2"/>')
    parts.append(_text(355, 20, "OPEC+减产", 8, HIGHLIGHT))
    # 图例
    parts.append(f'<line x1="40" y1="20" x2="60" y2="20" stroke="{BULL}" stroke-width="2"/>')
    parts.append(_text(65, 23, "WTI", 9, BULL))
    parts.append(f'<line x1="100" y1="20" x2="120" y2="20" stroke="{MA10}" stroke-width="2"/>')
    parts.append(_text(125, 23, "Brent", 9, MA10))
    # Y轴
    parts.append(_text(15, 45, "$120", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 120, "$60", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 210, "$0", 8, TEXT_LIGHT, "end"))
    parts.append(_text(250, 230, "供需驱动 · 地缘政治 · 美元计价", 8, TEXT_LIGHT, "middle"))
    parts.append(_text(250, 14, "原油价格走势", 11, TEXT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_gold_dollar() -> str:
    """黄金与美元负相关: 避险资产对比。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 美元指数 (蓝线, 从弱到强)
    dxy_pts = [(30,180),(70,170),(110,155),(150,140),(190,125),(230,110),
               (270,95),(310,85),(350,80),(390,85),(430,95),(470,105)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in dxy_pts)}" fill="none" stroke="{MA10}" stroke-width="2"/>')
    # 黄金 (红线, 与美元负相关)
    gold_pts = [(30,60),(70,70),(110,85),(150,100),(190,120),(230,140),
                (270,160),(310,175),(350,180),(390,170),(430,155),(470,135)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in gold_pts)}" fill="none" stroke="{BULL}" stroke-width="2"/>')
    # 负相关标注
    parts.append(f'<rect x="160" y="50" width="180" height="30" fill="rgba(245,158,11,0.1)" stroke="{HIGHLIGHT}" stroke-width="0.5" rx="3"/>')
    parts.append(_text(250, 68, "美元↑ → 黄金↓ (负相关)", 9, HIGHLIGHT, "middle"))
    # 避险事件标注
    parts.append(f'<line x1="350" y1="10" x2="350" y2="230" stroke="{NEUTRAL}" stroke-width="0.6" stroke-dasharray="3,2"/>')
    parts.append(_text(355, 18, "避险事件", 8, NEUTRAL))
    parts.append(_text(355, 30, "两者同涨", 7, TEXT_LIGHT))
    # 图例
    parts.append(f'<line x1="40" y1="20" x2="60" y2="20" stroke="{BULL}" stroke-width="2"/>')
    parts.append(_text(65, 23, "黄金", 9, BULL))
    parts.append(f'<line x1="100" y1="20" x2="120" y2="20" stroke="{MA10}" stroke-width="2"/>')
    parts.append(_text(125, 23, "美元指数", 9, MA10))
    # Y轴
    parts.append(_text(15, 45, "高", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 210, "低", 8, TEXT_LIGHT, "end"))
    parts.append(_text(250, 14, "黄金 vs 美元 (负相关)", 11, TEXT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_initial_claims() -> str:
    """初请失业金人数: 高频劳动力市场指标。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 正常水平线
    y_normal = 160
    parts.append(f'<line x1="20" y1="{y_normal}" x2="480" y2="{y_normal}" stroke="{NEUTRAL}" stroke-width="0.6" stroke-dasharray="3,2"/>')
    parts.append(_text(475, y_normal - 3, "25万 正常", 8, NEUTRAL, "end"))
    # 危机阈值线
    y_crisis = 80
    parts.append(f'<line x1="20" y1="{y_crisis}" x2="480" y2="{y_crisis}" stroke="{ARROW_RED}" stroke-width="0.8" stroke-dasharray="4,3"/>')
    parts.append(_text(475, y_crisis - 3, "50万 危机", 8, ARROW_RED, "end"))
    # 初请人数柱状图
    data = [220,230,210,225,240,260,350,680,520,380,280,250]
    bar_w = 32
    gap = 6
    x0 = 30
    max_val = 700
    max_h = 150
    base_y = 220
    for i, val in enumerate(data):
        x = x0 + i * (bar_w + gap)
        bh = val / max_val * max_h
        color = ARROW_RED if val > 400 else (HIGHLIGHT if val > 300 else BULL)
        parts.append(f'<rect x="{x}" y="{base_y - bh:.0f}" width="{bar_w}" height="{bh:.0f}" fill="{color}" opacity="0.7" rx="2"/>')
        if val > 400:
            parts.append(_text(x + bar_w/2, base_y - bh - 5, f"{val}K", 7, ARROW_RED, "middle"))
    # 周标注
    for i in range(0, len(data), 3):
        x = x0 + i * (bar_w + gap) + bar_w / 2
        parts.append(_text(x, 235, f"W{i+1}", 7, TEXT_LIGHT, "middle"))
    # Y轴
    parts.append(_text(15, 45, "700K", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 120, "350K", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 220, "0", 8, TEXT_LIGHT, "end"))
    parts.append(_text(250, 14, "初请失业金人数 (周度)", 11, TEXT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_retail_sales() -> str:
    """零售销售: 消费者支出的月度指标。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 零售销售环比柱状图
    data = [0.3, -0.2, 0.5, 0.8, -0.1, 0.2, 0.4, 1.2, -0.3, 0.6, 0.1, 0.3]
    bar_w = 32
    gap = 6
    x0 = 30
    max_val = 1.5
    max_h = 70
    zero_y = 130
    months = ["1","2","3","4","5","6","7","8","9","10","11","12"]
    for i, val in enumerate(data):
        x = x0 + i * (bar_w + gap)
        bh = abs(val) / max_val * max_h
        if val >= 0:
            color = BULL
            parts.append(f'<rect x="{x}" y="{zero_y - bh:.0f}" width="{bar_w}" height="{bh:.0f}" fill="{color}" opacity="0.7" rx="2"/>')
        else:
            color = BEAR
            parts.append(f'<rect x="{x}" y="{zero_y}" width="{bar_w}" height="{bh:.0f}" fill="{color}" opacity="0.7" rx="2"/>')
        parts.append(_text(x + bar_w/2, 220, months[i], 7, TEXT_LIGHT, "middle"))
    # 零轴
    parts.append(f'<line x1="20" y1="{zero_y}" x2="480" y2="{zero_y}" stroke="{NEUTRAL}" stroke-width="1"/>')
    # 预期线
    parts.append(f'<line x1="20" y1="{zero_y - 0.4/max_val*max_h:.0f}" x2="480" y2="{zero_y - 0.4/max_val*max_h:.0f}" stroke="{HIGHLIGHT}" stroke-width="0.6" stroke-dasharray="4,3"/>')
    parts.append(_text(475, zero_y - 0.4/max_val*max_h - 3, "预期 +0.4%", 8, HIGHLIGHT, "end"))
    # Y轴
    parts.append(_text(15, 50, "+1.5%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 132, "0", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 200, "-1.5%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(250, 14, "零售销售环比 (%)", 11, TEXT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_housing() -> str:
    """房地产指标: 新屋开工与成屋销售。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 新屋开工 (红线)
    starts_pts = [(30,140),(70,130),(110,120),(150,110),(190,95),(230,85),
                  (270,90),(310,100),(350,115),(390,130),(430,140),(470,135)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in starts_pts)}" fill="none" stroke="{BULL}" stroke-width="2"/>')
    # 成屋销售 (蓝线)
    sales_pts = [(30,160),(70,155),(110,150),(150,140),(190,130),(230,120),
                 (270,125),(310,135),(350,145),(390,155),(430,165),(470,160)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in sales_pts)}" fill="none" stroke="{MA10}" stroke-width="2"/>')
    # 利率影响标注
    parts.append(f'<line x1="230" y1="10" x2="230" y2="230" stroke="{HIGHLIGHT}" stroke-width="0.6" stroke-dasharray="3,2"/>')
    parts.append(_text(235, 20, "加息周期开始", 8, HIGHLIGHT))
    # 影响箭头
    parts.append(_text(235, 35, "→ 销售降温", 8, BEAR))
    # 图例
    parts.append(f'<line x1="40" y1="20" x2="60" y2="20" stroke="{BULL}" stroke-width="2"/>')
    parts.append(_text(65, 23, "新屋开工", 9, BULL))
    parts.append(f'<line x1="150" y1="20" x2="170" y2="20" stroke="{MA10}" stroke-width="2"/>')
    parts.append(_text(175, 23, "成屋销售", 9, MA10))
    # Y轴
    parts.append(_text(15, 45, "高", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 210, "低", 8, TEXT_LIGHT, "end"))
    parts.append(_text(250, 14, "房地产指标", 11, TEXT, "middle"))
    parts.append(_text(250, 230, "利率敏感 · 经济先导", 8, TEXT_LIGHT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_fed_balance() -> str:
    """美联储资产负债表: 扩表与缩表。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 资产规模面积图 (从4万亿→9万亿→缩表)
    pts = [(30,180),(70,175),(110,168),(150,155),(190,135),(230,100),
           (270,70),(310,55),(350,50),(390,55),(430,65),(470,80)]
    area_pts = pts + [(470,220),(30,220)]
    parts.append(f'<polygon points="{" ".join(f"{x},{y:.0f}" for x,y in area_pts)}" fill="rgba(59,130,246,0.1)"/>')
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in pts)}" fill="none" stroke="{ARROW}" stroke-width="2"/>')
    # QE 阶段标注
    parts.append(f'<rect x="180" y="10" width="80" height="20" fill="rgba(199,64,64,0.15)" rx="2"/>')
    parts.append(_text(220, 24, "QE 扩表", 8, BULL, "middle"))
    # QT 阶段标注
    parts.append(f'<rect x="370" y="10" width="80" height="20" fill="rgba(45,155,101,0.15)" rx="2"/>')
    parts.append(_text(410, 24, "QT 缩表", 8, BEAR, "middle"))
    # 分界线
    parts.append(f'<line x1="350" y1="35" x2="350" y2="230" stroke="{HIGHLIGHT}" stroke-width="0.6" stroke-dasharray="3,2"/>')
    # 峰值标注
    parts.append(f'<circle cx="350" cy="50" r="4" fill="{HIGHLIGHT}"/>')
    parts.append(_text(345, 42, "$9万亿", 8, HIGHLIGHT, "middle"))
    # Y轴
    parts.append(_text(15, 50, "$9T", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 130, "$6T", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 220, "$4T", 8, TEXT_LIGHT, "end"))
    parts.append(_text(250, 14, "美联储资产负债表", 11, TEXT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_durable_goods() -> str:
    """耐用品订单: 企业投资与制造业领先指标。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 扣除运输的耐用品订单 (稳定增长线)
    core_pts = [(30,160),(70,150),(110,145),(150,135),(190,125),(230,115),
                (270,110),(310,105),(350,100),(390,95),(430,90),(470,88)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in core_pts)}" fill="none" stroke="{MA10}" stroke-width="1.5"/>')
    # 总耐用品订单 (波动大)
    total_pts = [(30,170),(70,120),(110,160),(150,100),(190,140),(230,80),
                 (270,130),(310,90),(350,125),(390,70),(430,110),(470,95)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in total_pts)}" fill="none" stroke="{BULL}" stroke-width="2"/>')
    # 波动标注
    parts.append(f'<rect x="320" y="170" width="120" height="22" fill="rgba(245,158,11,0.1)" stroke="{HIGHLIGHT}" stroke-width="0.5" rx="2"/>')
    parts.append(_text(380, 185, "运输项波动大", 8, HIGHLIGHT, "middle"))
    # 图例
    parts.append(f'<line x1="40" y1="20" x2="60" y2="20" stroke="{BULL}" stroke-width="2"/>')
    parts.append(_text(65, 23, "总订单", 9, BULL))
    parts.append(f'<line x1="140" y1="20" x2="160" y2="20" stroke="{MA10}" stroke-width="2"/>')
    parts.append(_text(165, 23, "扣除运输", 9, MA10))
    # Y轴
    parts.append(_text(15, 45, "+5%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 130, "0%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 210, "-5%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(250, 14, "耐用品订单环比", 11, TEXT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_pce() -> str:
    """PCE 通胀: 美联储最关注的通胀指标。"""
    w, h = 500, 240
    parts = [_svg_open(w, h), _grid_lines(w, h, 4)]
    # 2% 目标线
    y2 = 100
    parts.append(f'<line x1="20" y1="{y2}" x2="480" y2="{y2}" stroke="{HIGHLIGHT}" stroke-width="1" stroke-dasharray="5,3"/>')
    parts.append(_text(475, y2 - 5, "2% 目标", 9, HIGHLIGHT, "end"))
    # 核心 PCE (蓝线, 更平稳)
    core_pts = [(30,140),(70,130),(110,120),(150,105),(190,85),(230,70),
                (270,60),(310,55),(350,62),(390,72),(430,82),(470,88)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in core_pts)}" fill="none" stroke="{MA10}" stroke-width="2"/>')
    # 总 PCE (红线, 波动大)
    total_pts = [(30,155),(70,135),(110,115),(150,90),(190,65),(230,50),
                 (270,45),(310,52),(350,68),(390,80),(430,95),(470,110)]
    parts.append(f'<polyline points="{" ".join(f"{x},{y:.0f}" for x,y in total_pts)}" fill="none" stroke="{BULL}" stroke-width="2"/>')
    # 超标区域
    parts.append(f'<rect x="20" y="20" width="460" height="{y2-20}" fill="rgba(239,68,68,0.05)"/>')
    parts.append(_text(40, 35, "超标区 (>2%)", 8, ARROW_RED))
    # 峰值标注
    parts.append(f'<circle cx="270" cy="45" r="3" fill="{ARROW_RED}"/>')
    parts.append(_text(270, 35, "6.8%", 8, ARROW_RED, "middle"))
    # 图例
    parts.append(f'<line x1="330" y1="20" x2="350" y2="20" stroke="{BULL}" stroke-width="2"/>')
    parts.append(_text(355, 23, "PCE", 9, BULL))
    parts.append(f'<line x1="330" y1="35" x2="350" y2="35" stroke="{MA10}" stroke-width="2"/>')
    parts.append(_text(355, 38, "核心PCE", 9, MA10))
    # Y轴
    parts.append(_text(15, 45, "7%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 120, "2%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(15, 210, "0%", 8, TEXT_LIGHT, "end"))
    parts.append(_text(250, 14, "PCE 通胀指标", 11, TEXT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)


def svg_institutional_flow() -> str:
    """资金流向: 机构资金跨资产流动。"""
    w, h = 500, 240
    parts = [_svg_open(w, h)]
    # 中心: 资金池
    parts.append(f'<circle cx="250" cy="120" r="30" fill="rgba(59,130,246,0.15)" stroke="{ARROW}" stroke-width="1.5"/>')
    parts.append(_text(250, 118, "机构资金", 10, ARROW, "middle"))
    parts.append(_text(250, 130, "Risk On/Off", 8, TEXT_LIGHT, "middle"))
    # 四个方向: 股票/债券/黄金/现金
    targets = [
        (250, 30, "股票", BULL, "Risk On"),
        (430, 120, "债券", MA10, "Risk Off"),
        (250, 200, "黄金", HIGHLIGHT, "避险"),
        (70, 120, "现金/短债", NEUTRAL, "防御"),
    ]
    for tx, ty, label, color, mode in targets:
        # 箭头
        dx = tx - 250
        dy = ty - 120
        length = (dx**2 + dy**2) ** 0.5
        ux, uy = dx/length, dy/length
        x1 = 250 + ux * 32
        y1 = 120 + uy * 32
        x2 = tx - ux * 40
        y2 = ty - uy * 25
        parts.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="{color}" stroke-width="1.5" marker-end="url(#flow_{label})"/>')
        parts.append(f'<defs><marker id="flow_{label}" markerWidth="6" markerHeight="6" refX="3" refY="5" orient="auto"><path d="M0,0 L6,0 L3,5 Z" fill="{color}"/></marker></defs>')
        # 标签框
        parts.append(f'<rect x="{tx-35}" y="{ty-10}" width="70" height="20" fill="rgba(0,0,0,0.3)" stroke="{color}" stroke-width="0.8" rx="3"/>')
        parts.append(_text(tx, ty + 4, label, 9, color, "middle"))
        parts.append(_text(tx, ty + 22 if ty > 120 else ty - 18, mode, 7, TEXT_LIGHT, "middle"))
    # 标题
    parts.append(_text(250, 14, "机构资金跨资产流向", 11, TEXT, "middle"))
    parts.append(_text(250, 232, "经济周期决定 Risk On → Risk Off 切换", 8, TEXT_LIGHT, "middle"))
    parts.append(_svg_close())
    return "".join(parts)

