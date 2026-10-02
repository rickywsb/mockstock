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


def place(ticker: str, side: str, mode: str, qty: float | None = None, amount: float | None = None,
          reason: str = "") -> tuple[dict | None, str]:
    """返回 (成交记录, 提示)。按股数或按金额（向下取整到整股）下单；检查现金与持仓。"""
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
    fill = px * (1 + a["slippage"]) if side == "buy" else px * (1 - a["slippage"])
    if qty is None:
        qty = math.floor((amount or 0) / fill)
    qty = float(qty)
    if qty <= 0:
        return None, "数量为 0"
    trades = ledger.load_trades("manual")
    if side == "buy":
        c = ledger.cash(trades, a["initial_cash"])
        if qty * fill > c + 1e-6:
            return None, f"现金不足：需要 ${qty * fill:,.0f}，可用 ${c:,.0f}"
    else:
        held = ledger.open_positions(trades).get(t, {}).get("qty", 0)
        if qty > held + 1e-9:
            return None, f"持股不足：持有 {held:g} 股"
    tr = ledger.make_trade("manual", date, t, side, qty, fill, mode, reason)
    ledger.append_trades([tr])
    return tr, f"已{'买入' if side == 'buy' else '卖出'} {t} {qty:g} 股 @ ${fill:,.2f}（{'最新价' if mode == 'latest' else '收盘价'}，含滑点）"
