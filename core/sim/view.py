"""core/sim/view.py — 页面公共部分：行情缓存、账户初始化与补算、账户快照、净值曲线、表格"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import config
from core import daily_momentum as dm
from core.sim import ledger, strategy
from core.ui import pz_table, pct

COLORS = {"auto": "#3A86FF", "manual": "#FF4F7B", "SPY": "#A39DBA", "QQQ": "#FFBE0B"}


# ─── 行情 ─────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner="📡 正在加载全市场行情与信号（约 540 只，首次约 30 秒）…", ttl=21600)
def _market(close_day: str) -> dict:
    return strategy.market_data()


def last_close() -> str:
    from core.tracker import last_close_date
    return last_close_date() or config.market_today().isoformat()


def market() -> dict:
    """按最近收盘日缓存：新的交易日收盘后自动重新加载。"""
    return _market(last_close())


@st.cache_data(ttl=3600, show_spinner=False)
def _closes(tickers: tuple[str, ...], close_day: str) -> pd.DataFrame:
    data = dm.fetch_ohlcv_histories(list(tickers), period="2y", complete_bars_only=True)
    return pd.DataFrame({t: d["Close"] for t, d in data.items() if d is not None and not d.empty})


def closes_for(tickers, md: dict) -> pd.DataFrame:
    """收盘价矩阵：股票池里的直接取，池外的（手动买的小盘股、QQQ 等）单独下载。"""
    tickers = sorted(set(tickers))
    inside = [t for t in tickers if t in md["close"].columns]
    out = md["close"][inside].copy()
    extra = tuple(t for t in tickers if t not in md["close"].columns)
    if extra:
        ex = _closes(extra, str(md["close"].index[-1].date()))
        ex.index = pd.to_datetime(ex.index).tz_localize(None)
        out = out.join(ex, how="left") if not out.empty else ex.reindex(md["close"].index)
    return out


@st.cache_data(ttl=120, show_spinner=False)
def live_prices(tickers: tuple[str, ...]) -> dict[str, float]:
    """最新价（免费行情延迟数分钟），2 分钟缓存。"""
    if not tickers:
        return {}
    from core.tracker import live_quotes
    q = live_quotes(list(tickers))
    return dict(zip(q["ticker"], q["last"])) if not q.empty else {}


# ─── 账户 ─────────────────────────────────────────────────────────────────────

def ensure() -> tuple[dict, dict]:
    """没有账户就以最近收盘日为 Day 0 建两个账户；然后把自动账户补算到最近交易日。返回 (accounts, md)。"""
    md = market()
    accs = ledger.load_accounts()
    if not accs:
        accs = ledger.init_accounts(str(md["close"].index[-1].date()))
    key = f"_caught_{md['close'].index[-1].date()}"
    if not st.session_state.get(key):
        strategy.catch_up(md)
        st.session_state[key] = True
    return accs, md


def snapshot(account: str, accs: dict, md: dict, live: bool = True) -> dict:
    """账户当前状态：现金、持仓明细（最新价）、净值、Day 0 起收益、净值序列。"""
    a = accs[account]
    trades = ledger.load_trades(account)
    pos = ledger.open_positions(trades)
    c = ledger.cash(trades, a["initial_cash"])
    last_close_px = {t: float(md["close"][t].dropna().iloc[-1]) for t in pos
                     if t in md["close"].columns and md["close"][t].notna().any()}
    px = dict(last_close_px)
    if live and pos:
        px.update(live_prices(tuple(sorted(pos))))
    missing = [t for t in pos if t not in px]
    if missing:
        cl = closes_for(missing, md)
        px.update({t: float(cl[t].dropna().iloc[-1]) for t in cl.columns if cl[t].notna().any()})
    score_row = md["score"].iloc[-1]
    rows = []
    for t, p in pos.items():
        last = px.get(t, p["avg"])
        mv = p["qty"] * last                       # 空头为负
        d = 1 if p["qty"] > 0 else -1
        rows.append({"ticker": t, "name": md["names"].get(t, t), "qty": p["qty"], "avg": p["avg"], "last": last,
                     "dir": "做多" if d > 0 else "做空",
                     "mv": mv, "pnl": mv - p["cost"], "ret": (last / p["avg"] - 1) * d if p["avg"] else None,
                     "first_buy": p["first_buy"],
                     "score": float(score_row[t]) if t in score_row.index and pd.notna(score_row[t]) else None})
    mv_total = sum(r["mv"] for r in rows)
    nav = c + mv_total
    for r in rows:
        r["weight"] = abs(r["mv"]) / nav if nav else None
    held_ever = sorted({t["ticker"] for t in trades})
    cl = closes_for(held_ever, md) if held_ever else pd.DataFrame(index=md["close"].index)
    series = ledger.nav_series(trades, a["initial_cash"], a["day0"], cl) if held_ever else \
        pd.Series(a["initial_cash"], index=md["close"].index[md["close"].index >= pd.Timestamp(a["day0"])])
    return {"account": account, "name": ledger.ACCOUNT_NAMES[account], "initial": a["initial_cash"], "day0": a["day0"],
            "cash": c, "nav": nav, "ret": nav / a["initial_cash"] - 1, "positions": rows,
            "trades": trades, "series": series}


def bench_series(md: dict, day0: str, tickers=("SPY", "QQQ")) -> dict[str, pd.Series]:
    cl = closes_for(list(tickers), md)
    out = {}
    for t in tickers:
        if t in cl.columns:
            s = cl[t].dropna()
            s = s[s.index >= pd.Timestamp(day0)]
            if len(s):
                out[t] = s
    return out


# ─── 图表 ─────────────────────────────────────────────────────────────────────

def equity_chart(lines: dict[str, pd.Series], height: int = 340) -> go.Figure:
    """各条净值 / 价格序列从起点归一为累计收益%。"""
    fig = go.Figure()
    for name, s in lines.items():
        s = s.dropna()
        if s.empty:
            continue
        y = (s / s.iloc[0] - 1) * 100
        key = "auto" if name == ledger.ACCOUNT_NAMES["auto"] else "manual" if name == ledger.ACCOUNT_NAMES["manual"] else name
        bench = name in ("SPY", "QQQ")
        fig.add_trace(go.Scatter(x=s.index, y=y, name=name, mode="lines+markers" if len(s) < 15 else "lines",
                                 line=dict(color=COLORS.get(key, None), width=1.5 if bench else 2.4,
                                           dash="dot" if bench else "solid"),
                                 hovertemplate="%{x|%Y-%m-%d}<br>%{y:+.2f}%<extra>" + name + "</extra>"))
    fig.add_hline(y=0, line_color="#CFCBC0", line_width=1)
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=10, b=8), hovermode="x unified",
                      yaxis_ticksuffix="%", legend=dict(orientation="h", y=1.08, x=0),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    fig.update_yaxes(gridcolor="#ECEAE4")
    return fig


def drawdown_chart(nav: pd.Series, height: int = 200) -> go.Figure:
    dd = (nav / nav.cummax() - 1) * 100
    fig = go.Figure(go.Scatter(x=dd.index, y=dd, fill="tozeroy", line=dict(color="#B3362A", width=1.2),
                               hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f}%<extra>回撤</extra>"))
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=10, b=8), yaxis_ticksuffix="%",
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    fig.update_yaxes(gridcolor="#ECEAE4")
    return fig


# ─── 表格 ─────────────────────────────────────────────────────────────────────

def positions_table(snap: dict, key: str, md: dict) -> None:
    rows = [{"ticker": r["ticker"], "name": r["name"],
             "sub": " · ".join(x for x in [r["name"] if r["name"] != r["ticker"] else "", md["sectors"].get(r["ticker"]) or ""] if x),
             "dir": r["dir"], "qty": abs(r["qty"]), "avg": r["avg"], "last": r["last"], "mv": r["mv"], "pnl": r["pnl"],
             "ret": pct(r["ret"]), "weight": pct(r["weight"]),
             "score": int(r["score"]) if r["score"] is not None else None, "first_buy": r["first_buy"]}
            for r in snap["positions"]]
    cols = [
        {"key": "ticker", "label": "股票", "kind": "stock", "width": "minmax(140px,1.4fr)", "sortable": True},
        {"key": "dir", "label": "方向", "kind": "pill", "width": "64px"},
        {"key": "qty", "label": "股数", "kind": "num", "decimals": 0, "width": "64px", "align": "right"},
        {"key": "avg", "label": "成本", "kind": "num", "decimals": 2, "width": "84px", "align": "right"},
        {"key": "last", "label": "最新价", "kind": "num", "decimals": 2, "width": "84px", "align": "right"},
        {"key": "mv", "label": "市值", "kind": "num", "decimals": 0, "prefix": "$", "width": "96px",
         "align": "right", "sortable": True},
        {"key": "pnl", "label": "浮动盈亏", "kind": "num", "decimals": 0, "prefix": "$", "sign": True,
         "color": True, "width": "96px", "align": "right", "sortable": True},
        {"key": "ret", "label": "收益", "kind": "num", "decimals": 2, "suffix": "%", "sign": True, "color": True,
         "width": "80px", "align": "right", "sortable": True},
        {"key": "weight", "label": "仓位", "kind": "bar", "max": 30, "suffix": "%", "decimals": 1, "width": "120px",
         "sortable": True},
        {"key": "score", "label": "评分", "kind": "score", "width": "70px", "sortable": True},
        {"key": "first_buy", "label": "建仓日", "kind": "small", "width": "92px"},
    ]
    pz_table(rows, cols, key=key, sort="mv", empty="暂无持仓", min_width=960)


SIDE_TXT = {"buy": "买入", "sell": "卖出", "short": "做空", "cover": "平空"}
MODE_TXT = {"open": "次日开盘", "close": "收盘价", "latest": "最新价"}


def trades_table(trades: list[dict], key: str, md: dict, limit: int | None = None) -> None:
    tt = sorted(trades, key=lambda x: (x["date"], x.get("created_at", "")), reverse=True)
    if limit:
        tt = tt[:limit]
    rows = [{"ticker": t["ticker"], "name": md["names"].get(t["ticker"], t["ticker"]),
             "sub": md["names"].get(t["ticker"], "") if md["names"].get(t["ticker"], t["ticker"]) != t["ticker"] else "",
             "date": t["date"], "side": SIDE_TXT[t["side"]], "qty": t["qty"], "price": t["price"],
             "amount": t["qty"] * t["price"], "mode": MODE_TXT.get(t["mode"], t["mode"]), "reason": t.get("reason", "")}
            for t in tt]
    cols = [
        {"key": "date", "label": "成交日", "kind": "small", "width": "92px", "sortable": True},
        {"key": "ticker", "label": "股票", "kind": "stock", "width": "minmax(120px,1.2fr)", "sortable": True},
        {"key": "side", "label": "方向", "kind": "pill", "width": "64px"},
        {"key": "qty", "label": "股数", "kind": "num", "decimals": 0, "width": "64px", "align": "right"},
        {"key": "price", "label": "成交价", "kind": "num", "decimals": 2, "width": "84px", "align": "right"},
        {"key": "amount", "label": "金额", "kind": "num", "decimals": 0, "prefix": "$", "width": "92px", "align": "right"},
        {"key": "mode", "label": "成交方式", "kind": "small", "width": "76px"},
        {"key": "reason", "label": "理由", "kind": "small", "width": "minmax(180px,2fr)"},
    ]
    pz_table(rows, cols, key=key, sort="date", empty="暂无交易", min_width=900)


def today_signals(md: dict, held: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """
    最近交易日的买点 / 卖点（只用自动策略里的 A / B 级信号，降噪）：
      买点：评分 ≥ 门槛的美股，按评分排序；卖点：只看 held 里的股票（持仓）。
    """
    p = config.AUTO_STRATEGY
    ons, score = md["onsets"], md["score"]
    d = score.index[-1]
    row = score.loc[d]
    buys: dict[str, dict] = {}
    for s in p["buy_signals"]:
        if s not in ons:
            continue
        hit = ons[s].loc[d]
        for t in hit.index[hit.fillna(False).to_numpy(dtype=bool)]:
            sc = row.get(t)
            if "." in t or sc is None or sc != sc or sc < p["min_score"]:
                continue
            buys.setdefault(t, {"ticker": t, "signal": s, "score": int(sc)})
    sells = []
    for t in sorted(held or []):
        for s in p["sell_signals"]:
            if s in ons and t in ons[s].columns and bool(ons[s].at[d, t] == True):  # noqa: E712
                sells.append({"ticker": t, "signal": s, "score": int(row[t]) if pd.notna(row.get(t)) else None})
                break
    return sorted(buys.values(), key=lambda x: -x["score"]), sells


def signal_table(items: list[dict], key: str, md: dict, side: str, held: set[str] | None = None) -> None:
    cl = md["close"]
    rows = []
    for x in items:
        t = x["ticker"]
        c = cl[t].dropna() if t in cl.columns else pd.Series(dtype=float)
        rows.append({"ticker": t, "name": md["names"].get(t, t),
                     "sub": " · ".join(v for v in [md["names"].get(t, "") if md["names"].get(t, t) != t else "",
                                                     md["sectors"].get(t) or ""] if v),
                     "price_txt": f"{c.iloc[-1]:,.2f}" if len(c) else None,
                     "chg": pct(c.iloc[-1] / c.iloc[-2] - 1) if len(c) > 1 else None,
                     "score": x.get("score"), "signal": x["signal"],
                     "held": "已持仓" if held and t in held else "",
                     "spark": [float(v) for v in c.tail(20)]})
    cols = [
        {"key": "ticker", "label": "股票", "kind": "stock", "width": "minmax(140px,1.4fr)", "sortable": True},
        {"key": "price_txt", "label": "收盘 · 当日", "kind": "price", "chg": "chg", "width": "100px"},
        {"key": "score", "label": "评分", "kind": "score", "width": "70px", "sortable": True},
        {"key": "spark", "label": "20 日走势", "kind": "spark", "width": "92px"},
        {"key": "signal", "label": "买点信号" if side == "buy" else "卖点信号", "kind": "small",
         "width": "minmax(150px,1.5fr)"},
        {"key": "held", "label": "", "kind": "pill", "width": "70px"},
    ]
    pz_table(rows, cols, key=key, sort="score", empty="今天没有触发", min_width=700)


def money(v: float) -> str:
    return f"${v:,.0f}"
