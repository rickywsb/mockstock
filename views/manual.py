"""views/manual.py — 我的账户：手动下单、持仓、交易记录"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from core.sim import ledger, orders, view as V
from core.stock_chart import click_hint
from core.ui import page_header

accs, md = V.ensure()
snap = V.snapshot("manual", accs, md)
page_header("我的账户", f"Day 0 = {snap['day0']} ｜ 自己买卖，与自动策略同起点、同成本比较")

c = st.columns(4)
c[0].metric("净值（最新价）", V.money(snap["nav"]), f"{snap['ret']:+.2%}")
c[1].metric("现金", V.money(snap["cash"]))
c[2].metric("持仓市值", V.money(snap["nav"] - snap["cash"]), f"{len(snap['positions'])} 只")
realized = sum(p["realized"] for p in ledger.positions(snap["trades"]).values())
c[3].metric("已实现盈亏", V.money(realized))

# ─── 下单 ─────────────────────────────────────────────────────────────────────
st.subheader("📝 下单")
held = {r["ticker"]: r for r in snap["positions"]}
with st.form("order", border=True):
    f = st.columns([1.2, 1, 1, 1.3, 1.3])
    ticker = f[0].text_input("股票代码（美股）", placeholder="如 NVDA").strip().upper()
    side = f[1].radio("方向", ["买入", "卖出"], horizontal=True)
    mode = f[2].radio("成交价", ["最新价", "收盘价"], horizontal=True,
                      help="最新价：免费行情（延迟数分钟），成交日记为该报价所在交易日；收盘价：最近一个完整交易日的收盘价")
    by = f[3].radio("数量方式", ["按金额", "按股数"], horizontal=True)
    val = f[4].number_input("金额（$）/ 股数", min_value=0.0, value=10000.0, step=100.0)
    reason = st.text_input("理由（可选，方便复盘）", placeholder="如：放量创 52 周新高，评分 95")
    sell_all = st.checkbox("卖出全部持股（卖出时）")
    ok = st.form_submit_button("提交订单", type="primary")
if ok:
    if not ticker:
        st.error("请输入股票代码")
    else:
        s = "buy" if side == "买入" else "sell"
        qty = None
        amount = None
        if s == "sell" and sell_all:
            qty = held.get(ticker, {}).get("qty", 0)
        elif by == "按股数":
            qty = val
        else:
            amount = val
        with st.spinner(f"取 {ticker} 价格…"):
            tr, msg = orders.place(ticker, s, "latest" if mode == "最新价" else "close", qty=qty, amount=amount,
                                   reason=reason)
        if tr:
            V.live_prices.clear()
            st.session_state["_order_msg"] = msg
            st.rerun()
        else:
            st.error(msg)
if st.session_state.get("_order_msg"):
    st.success(st.session_state.pop("_order_msg"))
st.caption(f"滑点 {accs['manual']['slippage']:.2%}（买入价上浮、卖出价下浮），零佣金；只能用现金买入（不融资、不做空）。")

# ─── 持仓与交易 ────────────────────────────────────────────────────────────────
st.subheader("💼 持仓")
click_hint()
V.positions_table(snap, "man_pos", md)

st.subheader("🧾 交易记录")
V.trades_table(snap["trades"], "man_trades", md)

with st.expander("⚠️ 重置我的账户"):
    st.caption("清空我的账户全部交易，恢复初始现金（Day 0 不变）。不可撤销。")
    if st.checkbox("确认清空", key="confirm_reset_manual") and st.button("清空我的账户"):
        ledger.reset_account("manual")
        st.rerun()
