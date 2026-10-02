"""core/sim/game.py — 游戏层：你 vs 量化 记分牌、称号、成就、个股弹窗里的下单面板、选股大厅数据"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import config
from core import signal_lab
from core.sim import ledger, orders, view as V

YOU, QUANT, GOLD, INK = "#FF4F7B", "#3A86FF", "#FFBE0B", "#1E1442"

CSS = f"""
<style>
.block-container {{ padding-top: 4.2rem; max-width: 1400px; }}
.pz-title {{ font-family: "ZCOOL QingKe HuangYou", "Noto Sans SC", sans-serif; font-size: 40px; font-weight: 400;
            letter-spacing: 2px; color: {INK}; }}
.pz-sub {{ color: #6B6390; }}
[data-testid="stMetric"] {{ background: #FFFFFF; border: 2px solid {INK}; border-radius: 16px;
                           box-shadow: 4px 4px 0 {INK}; padding: 12px 16px; }}
[data-testid="stMetricValue"] {{ font-weight: 700; }}
.stButton button, [data-testid="stFormSubmitButton"] button, .stDownloadButton button, .stLinkButton a {{
    border: 2px solid {INK} !important; box-shadow: 3px 3px 0 {INK}; font-weight: 700; transition: transform .08s, box-shadow .08s; }}
.stButton button:hover, [data-testid="stFormSubmitButton"] button:hover {{ transform: translate(-1px,-1px); box-shadow: 4px 4px 0 {INK}; }}
.stButton button:active, [data-testid="stFormSubmitButton"] button:active {{ transform: translate(2px,2px); box-shadow: 1px 1px 0 {INK}; }}
[data-testid="stForm"] {{ background: #FFFFFF; border: 2px solid {INK} !important; box-shadow: 5px 5px 0 {INK}; border-radius: 18px; }}
[data-testid="stExpander"] details {{ border: 2px solid {INK}; border-radius: 14px; background: #FFFFFF; }}
[data-testid="stSidebarNav"] a span {{ font-weight: 600; }}
/* 记分牌 */
.vs {{ display: grid; grid-template-columns: 1fr auto 1fr; gap: 16px; align-items: stretch; margin: 2px 0 6px; }}
.vs-side {{ border: 2.5px solid {INK}; border-radius: 22px; padding: 14px 22px; box-shadow: 5px 5px 0 {INK}; color: #FFFFFF; }}
.vs-you {{ background: linear-gradient(135deg, {YOU} 0%, #FF8A5B 100%); }}
.vs-quant {{ background: linear-gradient(135deg, #8338EC 0%, {QUANT} 100%); text-align: right; }}
.vs-tag {{ font-size: 14px; font-weight: 700; opacity: .95; }}
.vs-ret {{ font-family: "IBM Plex Mono", monospace; font-size: 42px; font-weight: 700; line-height: 1.15; }}
.vs-nav {{ font-size: 13px; opacity: .92; }}
.vs-mid {{ display: flex; flex-direction: column; align-items: center; justify-content: center; min-width: 150px; }}
.vs-day {{ font-family: "IBM Plex Mono", monospace; font-size: 13px; font-weight: 700; background: {INK}; color: {GOLD};
          padding: 3px 12px; border-radius: 999px; letter-spacing: 1px; }}
.vs-vs {{ font-family: "ZCOOL QingKe HuangYou", sans-serif; font-size: 58px; line-height: 1.05; color: {GOLD};
         -webkit-text-stroke: 2px {INK}; text-shadow: 4px 4px 0 {INK}; transform: rotate(-8deg); }}
.vs-lead {{ font-size: 13px; font-weight: 700; color: {INK}; text-align: center; }}
.tug {{ height: 14px; border: 2px solid {INK}; border-radius: 999px; background: {QUANT}; overflow: hidden; margin: 10px 0 4px; }}
.tug-you {{ height: 100%; background: {YOU}; border-right: 3px solid {GOLD}; }}
.vs-foot {{ font-size: 12.5px; color: #6B6390; display: flex; gap: 18px; flex-wrap: wrap; }}
.vs-mini {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; border: 2px solid {INK}; border-radius: 999px;
           background: #FFFFFF; box-shadow: 3px 3px 0 {INK}; padding: 6px 16px; font-size: 14px; font-weight: 700; width: fit-content; }}
.vs-mini .y {{ color: {YOU}; }} .vs-mini .q {{ color: {QUANT}; }}
.vs-mini .m {{ font-family: "IBM Plex Mono", monospace; }}
/* 成就 / 标签 */
.badges {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px; }}
.badge {{ border: 2px solid {INK}; border-radius: 16px; padding: 10px 12px; background: #FFFFFF; box-shadow: 3px 3px 0 {INK}; }}
.badge.off {{ opacity: .38; box-shadow: none; border-style: dashed; filter: grayscale(1); }}
.badge b {{ display: block; font-size: 14px; }} .badge span {{ font-size: 12px; color: #6B6390; }}
.badge i {{ font-style: normal; font-size: 26px; }}
.chips {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
.chip {{ border: 2px solid {INK}; border-radius: 999px; padding: 3px 12px; font-size: 13px; font-weight: 700; background: #FFFFFF; }}
.chip.b {{ background: #D7F5EA; }} .chip.s {{ background: #FFE0E3; }}
.feed {{ border-left: 3px solid {INK}; padding-left: 14px; }}
.feed div {{ margin: 6px 0; font-size: 14px; }}
.feed .who-you {{ color: {YOU}; font-weight: 800; }} .feed .who-quant {{ color: {QUANT}; font-weight: 800; }}
.tp-box {{ border: 2.5px solid {INK}; border-radius: 18px; padding: 12px 16px; background: #FFF8EE; box-shadow: 4px 4px 0 {INK}; margin-bottom: 6px; }}
.tp-px {{ font-family: "IBM Plex Mono", monospace; font-size: 30px; font-weight: 700; }}
@media (max-width: 680px) {{
  .vs {{ grid-template-columns: 1fr; }} .vs-quant {{ text-align: left; }} .vs-ret {{ font-size: 32px; }}
  .vs-mid {{ flex-direction: row; gap: 12px; }} .vs-vs {{ font-size: 40px; }}
}}
</style>
"""


def inject() -> None:
    st.html(CSS)


# ─── 称号 / 胜负 / 成就 ───────────────────────────────────────────────────────

TITLES = [(-0.10, "🥬 韭菜"), (0.0, "🐣 新手"), (0.05, "📈 散户"), (0.15, "🦊 操盘手"), (0.30, "🐺 基金经理")]


def title(ret: float) -> str:
    for th, name in TITLES:
        if ret < th:
            return name
    return "🐉 股神"


def daily_record(you: pd.Series, quant: pd.Series) -> tuple[int, int, int]:
    """Day 0 之后每个交易日比日收益：(你赢, 量化赢, 平)。"""
    both = pd.concat([you.pct_change(), quant.pct_change()], axis=1).dropna()
    if both.empty:
        return 0, 0, 0
    d = both.iloc[:, 0] - both.iloc[:, 1]
    return int((d > 1e-6).sum()), int((d < -1e-6).sum()), int((d.abs() <= 1e-6).sum())


def achievements(you: dict, quant: dict) -> list[tuple[str, str, str, bool]]:
    tr = you["trades"]
    ct = ledger.closed_trades(tr)
    n_closed = len(ct)
    win = (ct["pnl"] > 0).mean() if n_closed else 0
    days = max(len(you["series"]) - 1, 0)
    dd = float((you["series"] / you["series"].cummax() - 1).min()) if len(you["series"]) > 1 else 0.0
    return [
        ("🎉", "开张大吉", "完成第一笔交易", len(tr) > 0),
        ("🩳", "空军上校", "第一次做空", any(t["side"] == "short" for t in tr)),
        ("💰", "落袋为安", "第一次盈利平仓", bool(n_closed and (ct["pnl"] > 0).any())),
        ("💯", "十倍股的开始", "单笔平仓收益 ≥ 10%", bool(n_closed and (ct["ret"] >= 0.10).any())),
        ("🏆", "人胜机器", "总收益领先量化", you["ret"] > quant["ret"] and len(tr) > 0),
        ("🧠", "神枪手", "≥5 笔平仓且胜率 ≥ 60%", n_closed >= 5 and win >= 0.6),
        ("🔟", "交易狂人", "累计 10 笔交易", len(tr) >= 10),
        ("🛡️", "铁壁防守", "坚持 20 个交易日且最大回撤 < 5%", days >= 20 and dd > -0.05),
        ("🚀", "起飞", "总收益 ≥ 10%", you["ret"] >= 0.10),
        ("🐉", "股神", "总收益 ≥ 30%", you["ret"] >= 0.30),
    ]


# ─── 记分牌 ───────────────────────────────────────────────────────────────────

def scoreboard(you: dict, quant: dict, spy_ret: float | None, compact: bool = False) -> None:
    diff = you["ret"] - quant["ret"]
    n_day = max(len(quant["series"]) - 1, 0)
    w, l, _ = daily_record(you["series"], quant["series"])
    if abs(diff) < 1e-4:
        lead = "势均力敌"
    else:
        lead = f"{'你' if diff > 0 else '量化'}领先 {abs(diff):.2%}"
    if compact:
        st.html(f'<div class="vs-mini"><span>DAY {n_day}</span>'
                f'<span class="y">🧑 你 <span class="m">{you["ret"]:+.2%}</span></span><span>VS</span>'
                f'<span class="q">🤖 量化 <span class="m">{quant["ret"]:+.2%}</span></span>'
                f'<span style="color:#6B6390">｜ {lead}</span></div>')
        return
    tug = 50 + max(-46, min(46, diff * 500))          # 领先 1% ≈ 绳子移动 5 格
    st.html(f"""
<div class="vs">
  <div class="vs-side vs-you"><div class="vs-tag">🧑 你 · {title(you['ret'])}</div>
    <div class="vs-ret">{you['ret']:+.2%}</div>
    <div class="vs-nav">{V.money(you['nav'])} ｜ 持仓 {len(you['positions'])} 只 ｜ {len(you['trades'])} 笔交易</div></div>
  <div class="vs-mid"><div class="vs-day">DAY {n_day}</div><div class="vs-vs">VS</div><div class="vs-lead">{lead}</div></div>
  <div class="vs-side vs-quant"><div class="vs-tag">🤖 量化 · O'Neil 信号策略</div>
    <div class="vs-ret">{quant['ret']:+.2%}</div>
    <div class="vs-nav">{V.money(quant['nav'])} ｜ 持仓 {len(quant['positions'])} 只 ｜ {len(quant['trades'])} 笔交易</div></div>
</div>
<div class="tug"><div class="tug-you" style="width:{tug:.1f}%"></div></div>
<div class="vs-foot"><span>📅 Day 0 = {you['day0']}</span><span>🥊 日胜负 你 {w} : {l} 量化</span>
  <span>📊 SPY {'—' if spy_ret is None else f'{spy_ret:+.2%}'}</span>
  <span>💵 每人本金 {V.money(you['initial'])} · 滑点 {config.SIM_SLIPPAGE:.2%} · 零佣金</span></div>
""")


# ─── 个股弹窗里的下单面板（core.stock_chart.TRADE_PANEL）────────────────────────

def _done(msg: str, first: bool) -> None:
    from core import stock_chart as SC
    st.session_state["_toast"] = msg
    if first:
        st.session_state["_balloons"] = True
    st.session_state.pop(SC._OPEN, None)
    V.live_prices.clear()
    st.rerun()


def trade_panel(ticker: str, name: str | None = None) -> None:
    t = ticker.upper()
    if "." in t:
        st.caption("🎮 模拟盘只交易美股，这只只能看不能买。")
        return
    accs = ledger.load_accounts()
    if "manual" not in accs:
        return
    trades = ledger.load_trades("manual")
    pos = ledger.open_positions(trades)
    prices = V.live_prices(tuple(sorted(set(pos) | {t})))
    nav, bp = orders.buying_power(trades, accs["manual"]["initial_cash"], prices)
    px = prices.get(t)
    held = pos.get(t)
    q_held = ledger.open_positions(ledger.load_trades("auto")).get(t)
    if held:
        side_txt = "多头" if held["qty"] > 0 else "空头"
        last = px or held["avg"]
        r = (last / held["avg"] - 1) * (1 if held["qty"] > 0 else -1)
        mine = (f'你持有 <b>{abs(held["qty"]):g} 股{side_txt}</b>，成本 {held["avg"]:,.2f}，'
                f'<b style="color:{"#06A77D" if r >= 0 else "#E63946"}">{r:+.2%}</b>')
    else:
        mine = "你还没有仓位"
    qtxt = f"🤖 量化持有 {q_held['qty']:g} 股" if q_held else "🤖 量化没有持有"
    st.html(f'<div class="tp-box"><div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px">'
            f'<span class="tp-px">{"—" if px is None else f"${px:,.2f}"}</span>'
            f'<span style="font-size:13px">{mine} ｜ {qtxt}</span></div>'
            f'<div style="font-size:12px;color:#6B6390">净值 {V.money(nav)} ｜ 可用额度 {V.money(max(bp, 0))}'
            f'（不加杠杆：多空总市值 ≤ 净值）｜ 价格为最新报价，可能延迟数分钟</div></div>')
    c = st.columns([1.6, 1.1])
    size = c[0].segmented_control("下单金额（占净值）", ["5%", "10%", "20%", "自定义"], default="10%", key="tp_size") or "10%"
    mode = c[1].segmented_control("成交价", ["最新价", "收盘价"], default="最新价", key="tp_mode") or "最新价"
    amount = (st.number_input("金额 $", min_value=0.0, value=round(nav * 0.1, -2), step=500.0, key="tp_amt")
              if size == "自定义" else nav * int(size[:-1]) / 100)
    m = "latest" if mode == "最新价" else "close"
    first = not trades
    b = st.columns(4)
    if b[0].button(f"🟢 买入 ${amount:,.0f}", key="tp_buy", type="primary", width="stretch",
                   disabled=bool(held and held["qty"] < 0)):
        tr, msg = orders.place(t, "buy", m, amount=amount, prices=prices, reason="选股大厅下单")
        _done("🟢 " + msg, first) if tr else st.error(msg)
    if b[1].button(f"🔴 做空 ${amount:,.0f}", key="tp_short", width="stretch",
                   disabled=bool(held and held["qty"] > 0)):
        tr, msg = orders.place(t, "short", m, amount=amount, prices=prices, reason="选股大厅下单")
        _done("🔴 " + msg, first) if tr else st.error(msg)
    if held:
        q = abs(held["qty"])
        close_side = "sell" if held["qty"] > 0 else "cover"
        word = "卖出" if close_side == "sell" else "平空"
        if b[2].button(f"✂️ {word}一半", key="tp_half", width="stretch", disabled=q < 2):
            tr, msg = orders.place(t, close_side, m, qty=q // 2, prices=prices)
            _done("✂️ " + msg, False) if tr else st.error(msg)
        if b[3].button(f"🏁 全部{word}", key="tp_all", width="stretch"):
            tr, msg = orders.place(t, close_side, m, qty=q, prices=prices)
            _done("🏁 " + msg, False) if tr else st.error(msg)


# ─── 选股大厅数据 ─────────────────────────────────────────────────────────────

def _grades() -> dict[str, str]:
    lab = signal_lab.load_summary()
    return dict(zip(lab["summary"]["信号"], lab["summary"]["grade"])) if lab else {}


def lobby_frame(md: dict) -> pd.DataFrame:
    """全市场（美股）一行一只：价格、涨跌、评分、量比、距 52 周高、今日 A/B 级买卖点。"""
    key = str(md["close"].index[-1].date())
    cache = st.session_state.setdefault("_lobby_cache", {})
    if key in cache:
        return cache[key]
    cl = md["close"].ffill()
    last = cl.iloc[-1]
    hi = cl.rolling(252, min_periods=120).max().iloc[-1]
    ret = lambda n: last / cl.iloc[-1 - n] - 1
    df = md["table"][["ticker", "name", "score", "score_5d", "vr", "action", "volume_state", "above50"]].copy()
    df = df[~df["ticker"].str.contains(r"\.", regex=True)]
    df["price"] = df["ticker"].map(last)
    df["chg"] = df["ticker"].map(ret(1))
    df["ret5"] = df["ticker"].map(ret(5))
    df["ret20"] = df["ticker"].map(ret(20))
    df["ret60"] = df["ticker"].map(ret(60))
    df["off_high"] = df["ticker"].map(last / hi - 1)
    df["sector"] = df["ticker"].map(md["sectors"]).fillna("")
    df["spark"] = df["ticker"].map(lambda t: [float(v) for v in cl[t].tail(20)] if t in cl.columns else [])
    g = _grades()
    good = {n for n, v in g.items() if str(v)[:1] in ("A", "B")}
    expect = {n: e for n, _, e, _ in signal_lab.SIGNALS}
    d = md["score"].index[-1]
    buy, sell = {}, {}
    for n, ev in md["onsets"].items():
        if n not in good and n != "上升趋势短线超卖":
            continue
        row = ev.loc[d]
        for t in row.index[row.fillna(False).to_numpy(dtype=bool)]:
            (buy if expect.get(n, 1) > 0 else sell).setdefault(t, []).append(n)
    hide = signal_lab.SUBSUMES
    clean = lambda names: [n for n in names if not any(n in hide.get(m, set()) for m in names)]
    df["buy_sig"] = df["ticker"].map(lambda t: " · ".join(clean(buy.get(t, []))))
    df["sell_sig"] = df["ticker"].map(lambda t: " · ".join(clean(sell.get(t, []))))
    cache.clear()
    cache[key] = df
    return df


PRESETS = {
    "🔥 今日买点": ("A/B 级买点信号今天首次触发", lambda df: df[df["buy_sig"] != ""]),
    "🚀 强势榜": ("综合评分 ≥ 90 的全市场前 10%", lambda df: df[df["score"] >= 90]),
    "🧊 做空雷达": ("今天触发 A/B 级卖点，或评分 ≤ 15 且跌破 50 日线",
                  lambda df: df[(df["sell_sig"] != "") | ((df["score"] <= 15) & (df["above50"] == 0))]),
    "🎢 超跌反弹": ("长期上升趋势中短线超卖（2 日 RSI < 10）",
                  lambda df: df[df["buy_sig"].str.contains("短线超卖")]),
    "⚡ 放量异动": ("今日量比 ≥ 2", lambda df: df[df["vr"] >= 2]),
    "🌐 全部": ("全部美股（S&P 500 ∪ Nasdaq-100）", lambda df: df),
}


def lucky(df: pd.DataFrame) -> str | None:
    return random.choice(list(df["ticker"])) if len(df) else None
