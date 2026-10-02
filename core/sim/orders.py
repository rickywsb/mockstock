"""core/sim/orders.py — 我的账户：手动下单（最新价 / 收盘价）"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import config
from core import daily_momentum as dm
from core.sim import ledger


def quote(ticker: str, mode: str) -> tuple[float | None, str | None]:
    """mode="latest"：最新价（免费行情有数分钟延迟），成交日=今天；mode="close"：最近完整交易日收盘价。"""
    t = ticker.upper()
    if mode == "latest":
        from core.tracker import live_quotes
        q = live_quotes([t])
        if q.empty:
            return None, None
        return float(q.iloc[0]["last"]), str(q.iloc[0]["bar_date"])
    d = dm.fetch_ohlcv_histories([t], period="1mo", complete_bars_only=True).get(t)
    if d is None or d.empty:
        return None, None
    return float(d["Close"].iloc[-1]), d.index[-1].date().isoformat()


SIDE_TXT = {"buy": "买入", "sell": "卖出", "short": "做空", "cover": "平空"}


def buying_power(trades: list[dict], initial: float, prices: dict[str, float]) -> tuple[float, float]:
    """(净值, 可用额度)。不加杠杆：多头市值 + 空头市值 ≤ 净值。"""
    pos = ledger.open_positions(trades)
    c = ledger.cash(trades, initial)
    nav = c + sum(p["qty"] * prices.get(t, p["avg"]) for t, p in pos.items())
    gross = sum(abs(p["qty"]) * prices.get(t, p["avg"]) for t, p in pos.items())
    return nav, nav - gross


def place(ticker: str, side: str, mode: str, qty: float | None = None, amount: float | None = None,
          reason: str = "", prices: dict[str, float] | None = None) -> tuple[dict | None, str]:
    """
    side：buy 买入 / sell 卖出（平多）/ short 做空 / cover 平空。按股数或按金额（向下取整到整股）下单。
    开仓（买入 / 做空）受可用额度约束；平仓不能超过持仓；不允许一笔直接反手（先平再开）。
    prices：现有持仓的最新价（计算可用额度用），缺省按成本价。
    """
    t = ticker.upper().strip()
    if not t or "." in t:
        return None, "只支持美股代码（不带交易所后缀）"
    accs = ledger.load_accounts()
    if "manual" not in accs:
        return None, "账户尚未初始化"
    a = accs["manual"]
    px, date = quote(t, mode)
    if not px:
        return None, f"取不到 {t} 的价格"
    fill = px * (1 + a["slippage"]) if ledger.SIGN[side] > 0 else px * (1 - a["slippage"])
    if qty is None:
        qty = math.floor((amount or 0) / fill)
    qty = float(qty)
    if qty <= 0:
        return None, "数量为 0（金额不够买 1 股）"
    trades = ledger.load_trades("manual")
    held = ledger.open_positions(trades).get(t, {}).get("qty", 0.0)
    if side in ("buy", "short"):
        if (side == "buy" and held < -1e-9) or (side == "short" and held > 1e-9):
            return None, f"你持有 {t} 的{'空' if held < 0 else '多'}头，请先{'平空' if held < 0 else '卖出'}再反向开仓"
        prices = dict(prices or {})
        prices[t] = px
        _, bp = buying_power(trades, a["initial_cash"], prices)
        if qty * fill > bp + 1e-6:
            return None, f"额度不足：需要 ${qty * fill:,.0f}，可用 ${max(bp, 0):,.0f}（不加杠杆：多空总市值 ≤ 净值）"
    elif side == "sell" and qty > held + 1e-9:
        return None, f"多头持股不足：持有 {max(held, 0):g} 股"
    elif side == "cover" and qty > -held + 1e-9:
        return None, f"空头不足：空了 {max(-held, 0):g} 股"
    tr = ledger.make_trade("manual", date, t, side, qty, fill, mode, reason)
    ledger.append_trades([tr])
    return tr, f"已{SIDE_TXT[side]} {t} {qty:g} 股 @ ${fill:,.2f}（{'最新价' if mode == 'latest' else '收盘价'}，含滑点）"
