"""views/manual.py — 💼 我的仓位：持仓（多 / 空）、快速下单、交易记录"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from core.sim import ledger, orders, view as V
from core.stock_chart import click_hint
from core.ui import page_header

accs, md = V.ensure()
snap = st.session_state["_snaps"]["manual"]
page_header("💼 我的仓位", f"Day 0 = {snap['day0']} ｜ 和量化同起点、同本金、同成本 ｜ 点持仓行可看图、加仓或平仓")

c = st.columns(4)
c[0].metric("净值（最新价）", V.money(snap["nav"]), f"{snap['ret']:+.2%}")
c[1].metric("现金", V.money(snap["cash"]))
nav, bp = orders.buying_power(snap["trades"], snap["initial"], {r["ticker"]: r["last"] for r in snap["positions"]})
c[2].metric(f"可用额度（{len(snap['positions'])} 只持仓）", V.money(max(bp, 0)),
            help="不加杠杆：多头市值 + 空头市值 ≤ 净值")
realized = sum(p["realized"] for p in ledger.positions(snap["trades"]).values())
c[3].metric("已实现盈亏", V.money(realized))

# ─── 下单 ─────────────────────────────────────────────────────────────────────
st.subheader("📝 快速下单")
held = {r["ticker"]: r for r in snap["positions"]}
with st.form("order", border=True):
    f = st.columns([1.2, 1, 1, 1.3, 1.3])
    ticker = f[0].text_input("股票代码（美股）", placeholder="如 NVDA").strip().upper()
    side = f[1].selectbox("方向", ["买入", "卖出", "做空", "平空"])
    mode = f[2].radio("成交价", ["最新价", "收盘价"], horizontal=True,
                      help="最新价：免费行情（延迟数分钟），成交日记为该报价所在交易日；收盘价：最近一个完整交易日的收盘价")
    by = f[3].radio("数量方式", ["按金额", "按股数"], horizontal=True)
    val = f[4].number_input("金额（$）/ 股数", min_value=0.0, value=10000.0, step=100.0)
    reason = st.text_input("理由（可选，方便复盘）", placeholder="如：放量创 52 周新高，评分 95")
    sell_all = st.checkbox("全部平仓（卖出 / 平空时）")
    ok = st.form_submit_button("提交订单", type="primary")
if ok:
    if not ticker:
        st.error("请输入股票代码")
    else:
        s = {"买入": "buy", "卖出": "sell", "做空": "short", "平空": "cover"}[side]
        qty = None
        amount = None
        if s in ("sell", "cover") and sell_all:
            qty = abs(held.get(ticker, {}).get("qty", 0))
        elif by == "按股数":
            qty = val
        else:
            amount = val
        with st.spinner(f"取 {ticker} 价格…"):
            tr, msg = orders.place(ticker, s, "latest" if mode == "最新价" else "close", qty=qty, amount=amount,
                                   reason=reason, prices={r["ticker"]: r["last"] for r in snap["positions"]})
        if tr:
            V.live_prices.clear()
            st.session_state["_toast"] = msg
            if not snap["trades"]:
                st.session_state["_balloons"] = True
            st.rerun()
        else:
            st.error(msg)
st.caption(f"滑点 {accs['manual']['slippage']:.2%}（买入 / 平空价上浮，卖出 / 做空价下浮），零佣金；"
           "不加杠杆；同一只股票要反向，先平仓再开仓。更方便的方式：在 🎯 选股大厅点开个股直接下单。")

# ─── 持仓与交易 ────────────────────────────────────────────────────────────────
st.subheader("💼 持仓")
click_hint()
V.positions_table(snap, "man_pos", md)

st.subheader("🧾 交易记录")
V.trades_table(snap["trades"], "man_trades", md)

with st.expander("⚠️ 重开一局（清空我的仓位）"):
    st.caption("清空你的全部交易，恢复初始资金（Day 0 不变，量化不受影响）。不可撤销。")
    if st.checkbox("确认清空", key="confirm_reset_manual") and st.button("清空我的仓位"):
        ledger.reset_account("manual")
        st.rerun()
