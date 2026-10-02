"""core/sim/ledger.py — 模拟账户与交易流水

交易流水是唯一数据源：持仓、现金、每日净值都由流水按日回放算出，永远对得上。
交易记录：{id, account, date（成交日）, ticker, side（buy 买入 / sell 卖出 / short 做空 / cover 平空）, qty（正数）,
          price（含滑点的成交价）,
          mode（open 开盘 / close 收盘 / latest 最新价）, reason, signal, created_at}
只交易美股（美元计价，免汇率换算）。持仓用带符号的股数：多头为正、空头为负；做空所得计入现金，
净值 = 现金 + Σ 股数 × 价格（空头股数为负，自然扣减）。
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import config

ACCOUNT_IDS = ("auto", "manual")
ACCOUNT_NAMES = {"auto": "量化", "manual": "你"}


# ─── 读写 ─────────────────────────────────────────────────────────────────────

def _read(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write(path: Path, obj, sync_msg: str | None = None) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    if sync_msg:
        try:
            from core.github_storage import sync_to_github
            sync_to_github(path, f"data/{path.name}", sync_msg)
        except Exception:
            pass


def load_accounts() -> dict:
    return _read(config.SIM_ACCOUNTS_PATH, {})


def init_accounts(day0: str, initial_cash: float = config.SIM_INITIAL_CASH,
                  slippage: float = config.SIM_SLIPPAGE) -> dict:
    """两个账户同一 Day 0、同样初始资金与成本，保证可比。"""
    acc = {a: {"name": ACCOUNT_NAMES[a], "initial_cash": float(initial_cash), "day0": day0,
               "slippage": float(slippage), "created_at": datetime.now().isoformat(timespec="seconds")}
           for a in ACCOUNT_IDS}
    _write(config.SIM_ACCOUNTS_PATH, acc, "chore: init sim accounts")
    _write(config.SIM_TRADES_PATH, [], "chore: init sim trades")
    _write(config.SIM_STATE_PATH, {"auto": {"last_decision_day": None, "pending": []}}, "chore: init sim state")
    return acc


def load_trades(account: str | None = None) -> list[dict]:
    t = _read(config.SIM_TRADES_PATH, [])
    return [x for x in t if account is None or x["account"] == account]


def append_trades(new: list[dict], sync: bool = True) -> None:
    if not new:
        return
    allt = load_trades()
    allt.extend(new)
    allt.sort(key=lambda x: (x["date"], x.get("created_at", "")))
    _write(config.SIM_TRADES_PATH, allt, "chore: sim trades" if sync else None)
    write_portfolio_shim()


def reset_account(account: str) -> None:
    """清空某个账户的全部交易（Day 0 与初始资金不变）。"""
    allt = [t for t in load_trades() if t["account"] != account]
    _write(config.SIM_TRADES_PATH, allt, f"chore: reset sim {account}")
    write_portfolio_shim()
    if account == "auto":
        save_state({"auto": {"last_decision_day": None, "pending": []}})


def load_state() -> dict:
    return _read(config.SIM_STATE_PATH, {"auto": {"last_decision_day": None, "pending": []}})


def save_state(state: dict, sync: bool = True) -> None:
    _write(config.SIM_STATE_PATH, state, "chore: sim state" if sync else None)


def make_trade(account: str, date: str, ticker: str, side: str, qty: float, price: float, mode: str,
               reason: str = "", signal: str = "") -> dict:
    return {"id": uuid.uuid4().hex[:10], "account": account, "date": date, "ticker": ticker.upper(),
            "side": side, "qty": float(qty), "price": round(float(price), 4), "mode": mode,
            "reason": reason, "signal": signal, "created_at": datetime.now().isoformat(timespec="seconds")}


# ─── 回放 ─────────────────────────────────────────────────────────────────────

SIGN = {"buy": 1, "cover": 1, "sell": -1, "short": -1}


def positions(trades: list[dict], upto: str | None = None) -> dict[str, dict]:
    """
    {ticker: {qty（带符号）, cost（剩余持仓成本，带符号）, avg, realized（已实现盈亏）, first_buy（本轮建仓日）}}
    平均成本法：同方向加仓摊薄成本；反方向成交先平仓并结算盈亏（不允许一笔直接反手）。
    """
    pos: dict[str, dict] = {}
    for t in trades:
        if upto and t["date"] > upto:
            continue
        p = pos.setdefault(t["ticker"], {"qty": 0.0, "cost": 0.0, "realized": 0.0, "first_buy": None})
        q = SIGN[t["side"]] * t["qty"]
        if abs(p["qty"]) <= 1e-9 or (p["qty"] > 0) == (q > 0):
            if abs(p["qty"]) <= 1e-9:
                p["first_buy"], p["cost"], p["qty"] = t["date"], 0.0, 0.0
            p["qty"] += q
            p["cost"] += q * t["price"]
        else:
            avg = p["cost"] / p["qty"]
            close = min(abs(q), abs(p["qty"]))
            direction = 1 if p["qty"] > 0 else -1
            p["realized"] += close * (t["price"] - avg) * direction
            p["qty"] -= direction * close
            p["cost"] -= direction * close * avg
    for p in pos.values():
        p["avg"] = p["cost"] / p["qty"] if abs(p["qty"]) > 1e-9 else 0.0
    return pos


def cash(trades: list[dict], initial: float, upto: str | None = None) -> float:
    c = initial
    for t in trades:
        if upto and t["date"] > upto:
            continue
        c -= SIGN[t["side"]] * t["qty"] * t["price"]
    return c


def open_positions(trades: list[dict], upto: str | None = None) -> dict[str, dict]:
    return {k: v for k, v in positions(trades, upto).items() if abs(v["qty"]) > 1e-9}


def nav_series(trades: list[dict], initial: float, day0: str, closes: pd.DataFrame) -> pd.Series:
    """Day 0 起每个交易日收盘后的净值：现金 + Σ 持股 × 收盘价（收盘价缺失时沿用前值）。"""
    if closes.empty:
        return pd.Series(dtype=float)
    days = closes.index[closes.index >= pd.Timestamp(day0)]
    px = closes.ffill()
    out = {}
    for d in days:
        ds = d.date().isoformat()
        pos = open_positions(trades, ds)
        val = sum(p["qty"] * float(px.at[d, t]) for t, p in pos.items() if t in px.columns and pd.notna(px.at[d, t]))
        out[d] = cash(trades, initial, ds) + val
    return pd.Series(out)


def closed_trades(trades: list[dict]) -> pd.DataFrame:
    """每次平仓（卖出 / 平空）与对应平均成本配对，得到「已完成的交易」：方向、收益率、盈亏、持有天数。"""
    rows, pos = [], {}
    for t in trades:
        p = pos.setdefault(t["ticker"], {"qty": 0.0, "cost": 0.0, "first": None})
        q = SIGN[t["side"]] * t["qty"]
        if abs(p["qty"]) <= 1e-9 or (p["qty"] > 0) == (q > 0):
            if abs(p["qty"]) <= 1e-9:
                p.update(qty=0.0, cost=0.0, first=t["date"])
            p["qty"] += q
            p["cost"] += q * t["price"]
            continue
        avg = p["cost"] / p["qty"]
        close = min(abs(q), abs(p["qty"]))
        d = 1 if p["qty"] > 0 else -1
        rows.append({"ticker": t["ticker"], "dir": "多" if d > 0 else "空", "entry": p["first"], "exit": t["date"],
                     "qty": close, "avg_cost": avg, "exit_price": t["price"], "pnl": close * (t["price"] - avg) * d,
                     "ret": (t["price"] / avg - 1) * d if avg else None,
                     "days": (pd.Timestamp(t["date"]) - pd.Timestamp(p["first"])).days if p["first"] else None,
                     "reason": t.get("reason", ""), "signal": t.get("signal", "")})
        p["qty"] -= d * close
        p["cost"] -= d * close * avg
    return pd.DataFrame(rows)


# ─── 兼容层：让复制来的评分 / 个股信号模块把模拟持仓当作「持仓」──────────────────

def write_portfolio_shim() -> None:
    allt = load_trades()
    tickers = set()
    for a in ACCOUNT_IDS:
        tickers |= set(open_positions([t for t in allt if t["account"] == a]))
    pf = {"accounts": [{"name": "模拟持仓", "positions": [
        {"display": t, "yf_ticker": t, "shares": 0.0, "sector": "模拟"} for t in sorted(tickers)]}]}
    config.PORTFOLIO_PATH.write_text(json.dumps(pf, ensure_ascii=False, indent=1), encoding="utf-8")
