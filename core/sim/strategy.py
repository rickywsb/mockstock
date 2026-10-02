"""core/sim/strategy.py — 自动策略与逐日撮合（自动账户与回测共用同一套代码）

每个交易日 d 收盘后决策，第二个交易日 d+1 开盘成交（避免用到当时还不知道的信息）：
  卖出：持仓触发卖点信号（放量跌破 50 日线 / 相对强弱转弱），或收盘价 ≤ 平均成本 ×（1 − 止损%）
  买入：触发买点信号（放量创 52 周新高 / 放量上涨 / 财报跳空 / 首次回踩 50 日线）且综合评分 ≥ 门槛，
        不在持仓中，按评分从高到低补满空位；每只目标仓位 = d 日收盘净值 ÷ 最多持仓数（受现金约束）
  成交价：d+1 开盘价 ×（1 ± 滑点）
最后一个交易日的决策没有下一日开盘价 → 作为「待成交」返回，下次补算时重新决策。
数据：core.rating.build 的全市场矩阵（约 540 只、2 年、复权价）+ core.signal_lab 的信号矩阵。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import config
from core import daily_momentum as dm
from core import rating, signal_lab
from core.sim import ledger


def market_data(period: str = "2y") -> dict:
    """全市场矩阵 + 各信号首次触发矩阵（约 25 秒；页面按天缓存）。"""
    if not config.PORTFOLIO_PATH.exists():
        ledger.write_portfolio_shim()
    held, watch, _ = rating._portfolio_sets()
    b = rating.build(held, watch, period=period)
    spy_df = dm.fetch_ohlcv_histories(["SPY"], period=period, complete_bars_only=True).get("SPY")
    spy = spy_df["Close"] if spy_df is not None else pd.Series(dtype=float)
    masks = signal_lab.signal_masks(b["panel"], b["feat"], b["score"], spy)
    table = rating.latest(b, set(), set())
    _refresh_saved(b, table)
    uni = b["universe"]
    return {"open": b["panel"]["open"], "close": b["panel"]["close"], "score": b["score"], "table": table,
            "onsets": {k: signal_lab.onsets(v) for k, v in masks.items()}, "spy": spy,
            "names": dict(zip(uni["ticker"], uni["name"])), "sectors": dict(zip(uni["ticker"], uni["sector"]))}


def _refresh_saved(b: dict, table: pd.DataFrame) -> None:
    """顺手更新 data/rating_latest.json 与 signal_lab*.json（个股弹窗、选股器用），已是最新则跳过。"""
    as_of = str(b["score"].index[-1].date())
    try:
        _, saved = rating.load_latest()
        if saved != as_of:
            rating.save_latest(table, as_of)
        if (signal_lab.load_latest().get("as_of") or "") != as_of:
            signal_lab.save(signal_lab.run(b), config.market_today().isoformat())
    except Exception:
        pass


def _is_true(df: pd.DataFrame, d, t) -> bool:
    try:
        v = df.at[d, t]
        return bool(v) and v == v
    except KeyError:
        return False


def simulate(md: dict, params: dict, account: str, start: str, end: str | None,
             initial: float, slippage: float, trades_in: list[dict]) -> tuple[list[dict], list[dict], str | None]:
    """
    从 start 决策日到 end（含）逐日模拟。返回 (新交易, 待成交订单, 最后一个已成交的决策日)。
    """
    close, opn, score, ons = md["close"], md["open"], md["score"], md["onsets"]
    dates = close.index
    us_ok = (lambda t: "." not in t) if params.get("us_only", True) else (lambda t: True)
    trades = list(trades_in)
    new: list[dict] = []
    pending: list[dict] = []
    last_done = None
    max_n, stop = int(params["max_positions"]), float(params["stop_loss"])

    for i, d in enumerate(dates):
        ds = d.date().isoformat()
        if ds < start or (end and ds > end):
            continue
        pos = ledger.open_positions(trades, ds)

        # ── 卖出决策 ──
        sells = []
        for t, p in pos.items():
            sig = next((s for s in params["sell_signals"] if s in ons and _is_true(ons[s], d, t)), None)
            c = close.at[d, t] if t in close.columns else None
            if sig:
                sells.append((t, p["qty"], f"卖点：{sig}", sig))
            elif c is not None and c == c and p["avg"] and c <= p["avg"] * (1 - stop):
                sells.append((t, p["qty"], f"止损：较成本 {c / p['avg'] - 1:+.1%}", f"止损 −{stop:.0%}"))

        # ── 买入决策 ──
        slots = max_n - (len(pos) - len(sells))
        cands: dict[str, str] = {}
        if slots > 0:
            row_score = score.loc[d] if d in score.index else pd.Series(dtype=float)
            for s in params["buy_signals"]:
                if s not in ons or d not in ons[s].index:
                    continue
                hit = ons[s].loc[d]
                for t in hit.index[hit.fillna(False).to_numpy(dtype=bool)]:
                    sc = row_score.get(t)
                    if t in pos or t in cands or not us_ok(t) or sc is None or sc != sc or sc < params["min_score"]:
                        continue
                    cands[t] = s
            ranked = sorted(cands, key=lambda t: -float(row_score.get(t)))[:slots]
        else:
            ranked = []

        # ── 次日开盘成交 ──
        if i + 1 >= len(dates):
            pending = ([{"side": "sell", "ticker": t, "qty": q, "reason": r, "signal": s, "decided": ds}
                        for t, q, r, s in sells]
                       + [{"side": "buy", "ticker": t, "reason": f"买点：{cands[t]}（评分 {int(score.at[d, t])}）",
                           "signal": cands[t], "decided": ds} for t in ranked])
            break
        d1 = dates[i + 1]
        d1s = d1.date().isoformat()

        def _open(t):
            v = opn.at[d1, t] if t in opn.columns else None
            if v is None or v != v:
                v = close.at[d1, t] if t in close.columns else None
            return None if v is None or v != v else float(v)

        day_new = []
        for t, q, r, s in sells:
            px = _open(t)
            if px:
                day_new.append(ledger.make_trade(account, d1s, t, "sell", q, px * (1 - slippage), "open", r, s))
        trades_after_sells = trades + day_new
        nav_d = ledger.cash(trades, initial, ds) + sum(
            p["qty"] * float(close.at[d, t]) for t, p in pos.items()
            if t in close.columns and close.at[d, t] == close.at[d, t])
        target = nav_d / max_n
        avail = ledger.cash(trades_after_sells, initial, d1s)
        for t in ranked:
            px = _open(t)
            if not px:
                continue
            px *= (1 + slippage)
            qty = math.floor(min(target, avail) / px)
            if qty >= 1:
                day_new.append(ledger.make_trade(account, d1s, t, "buy", qty, px, "open",
                                                 f"买点：{cands[t]}（评分 {int(score.at[d, t])}）", cands[t]))
                avail -= qty * px
        trades.extend(day_new)
        new.extend(day_new)
        last_done = ds
    return new, pending, last_done


def catch_up(md: dict, sync: bool = True) -> dict:
    """自动账户：从上次处理日的下一天补算到最近交易日；返回 {new, pending, last}。"""
    accs = ledger.load_accounts()
    if "auto" not in accs:
        return {"new": [], "pending": [], "last": None}
    a = accs["auto"]
    state = ledger.load_state()
    st = state.setdefault("auto", {"last_decision_day": None, "pending": []})
    last = st.get("last_decision_day")
    start = a["day0"] if not last else (pd.Timestamp(last) + pd.Timedelta(days=1)).date().isoformat()
    new, pending, done = simulate(md, config.AUTO_STRATEGY, "auto", start, None, a["initial_cash"], a["slippage"],
                                  ledger.load_trades("auto"))
    if new:
        ledger.append_trades(new, sync=sync)
    st["pending"] = pending
    if done:
        st["last_decision_day"] = done
    st["updated"] = config.market_today().isoformat()
    ledger.save_state(state, sync=sync and bool(new or done))
    return {"new": new, "pending": pending, "last": st.get("last_decision_day")}


def backtest(md: dict, params: dict, start: str, initial: float = config.SIM_INITIAL_CASH,
             slippage: float = config.SIM_SLIPPAGE) -> dict:
    """同一套撮合在历史区间上跑一遍：返回 {trades, nav, closes}。"""
    trades, _, _ = simulate(md, params, "backtest", start, None, initial, slippage, [])
    held = sorted({t["ticker"] for t in trades})
    closes = md["close"][held] if held else pd.DataFrame(index=md["close"].index)
    nav = ledger.nav_series(trades, initial, start, closes)
    return {"trades": trades, "nav": nav}
