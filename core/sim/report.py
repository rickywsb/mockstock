"""core/sim/report.py — 账户表现指标（自动账户 / 我的账户 / 回测共用）"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.sim import ledger


def perf(nav: pd.Series, bench: pd.Series | None = None) -> dict:
    """净值序列 → 收益、年化、最大回撤、波动、夏普、相对基准超额与 β。"""
    nav = nav.dropna()
    if len(nav) < 2:
        return {"total": 0.0, "days": len(nav)}
    r = nav.pct_change().dropna()
    total = float(nav.iloc[-1] / nav.iloc[0] - 1)
    days = (nav.index[-1] - nav.index[0]).days
    dd = nav / nav.cummax() - 1
    out = {
        "total": total, "days": int(days), "n": len(nav),
        "cagr": float((1 + total) ** (365 / days) - 1) if days >= 60 else None,
        "max_dd": float(dd.min()),
        "vol": float(r.std(ddof=0) * math.sqrt(252)) if len(r) > 5 else None,
        "sharpe": float(r.mean() / r.std(ddof=0) * math.sqrt(252)) if len(r) > 5 and r.std(ddof=0) > 0 else None,
    }
    if bench is not None and len(bench.dropna()) > 1:
        b = bench.reindex(nav.index).ffill().dropna()
        if len(b) > 1:
            out["bench_total"] = float(b.iloc[-1] / b.iloc[0] - 1)
            out["excess"] = total - out["bench_total"]
            br = b.pct_change().dropna()
            both = pd.concat([r, br], axis=1).dropna()
            if len(both) > 10 and both.iloc[:, 1].var() > 0:
                out["beta"] = float(both.cov().iloc[0, 1] / both.iloc[:, 1].var())
    return out


def trade_stats(trades: list[dict]) -> dict:
    """已完成交易（卖出）统计：笔数、胜率、平均盈利 / 亏损、盈亏比、期望、平均持有天数。"""
    ct = ledger.closed_trades(trades)
    if ct.empty:
        return {"n": 0, "n_buys": sum(t["side"] == "buy" for t in trades)}
    wins, losses = ct[ct["pnl"] > 0], ct[ct["pnl"] <= 0]
    gross_win, gross_loss = float(wins["pnl"].sum()), float(-losses["pnl"].sum())
    return {
        "n": len(ct), "n_buys": sum(t["side"] == "buy" for t in trades),
        "win_rate": len(wins) / len(ct),
        "avg_win": float(wins["ret"].mean()) if len(wins) else None,
        "avg_loss": float(losses["ret"].mean()) if len(losses) else None,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else None,
        "expectancy": float(ct["ret"].mean()),
        "avg_days": float(ct["days"].mean()) if ct["days"].notna().any() else None,
        "realized": float(ct["pnl"].sum()),
    }


def exposure(trades: list[dict], nav: pd.Series, closes: pd.DataFrame) -> float | None:
    """平均仓位占比（多空持仓总市值 / 净值）。"""
    if nav.empty:
        return None
    vals = []
    px = closes.ffill()
    for d, v in nav.items():
        pos = ledger.open_positions(trades, d.date().isoformat())
        mv = sum(abs(p["qty"]) * float(px.at[d, t]) for t, p in pos.items() if t in px.columns and pd.notna(px.at[d, t]))
        vals.append(mv / v if v else 0)
    return float(np.mean(vals))


def ticker_pnl(trades: list[dict], last_px: dict[str, float]) -> pd.DataFrame:
    """按股票汇总：已实现 + 浮动盈亏。"""
    pos = ledger.positions(trades)
    rows = []
    for t, p in pos.items():
        unreal = (last_px.get(t, 0) - p["avg"]) * p["qty"] if abs(p["qty"]) > 1e-9 and t in last_px else 0.0
        rows.append({"ticker": t, "qty": p["qty"], "avg": p["avg"], "last": last_px.get(t),
                     "realized": p["realized"], "unrealized": unreal, "total": p["realized"] + unreal})
    return pd.DataFrame(rows).sort_values("total", ascending=False) if rows else pd.DataFrame()
