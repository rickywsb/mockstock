"""views/auto.py — 自动策略：规则、持仓、待成交、交易记录"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

import config
from core import signal_lab
from core.sim import ledger, report, view as V
from core.stock_chart import click_hint
from core.ui import page_header

accs, md = V.ensure()
snap = V.snapshot("auto", accs, md)
state = ledger.load_state().get("auto", {})
page_header("自动策略", f"Day 0 = {snap['day0']} ｜ 已处理到 {state.get('last_decision_day') or '—'} 收盘 ｜ "
                       "按规则自动买卖，作为我的账户的对照基准")

c = st.columns(4)
c[0].metric("净值（最新价）", V.money(snap["nav"]), f"{snap['ret']:+.2%}")
c[1].metric("现金", V.money(snap["cash"]))
c[2].metric("持仓", f"{len(snap['positions'])} / {config.AUTO_STRATEGY['max_positions']}")
ts = report.trade_stats(snap["trades"])
c[3].metric("已平仓胜率", f"{ts['win_rate']:.0%}" if ts.get("win_rate") is not None else "—",
            f"{ts.get('n', 0)} 笔已平仓", delta_color="off")

p = config.AUTO_STRATEGY
lab = signal_lab.load_summary()
grade = dict(zip(lab["summary"]["信号"], lab["summary"]["grade"])) if lab else {}
with st.expander("📐 策略规则", expanded=not snap["trades"]):
    st.markdown(
        f"- **买入**：触发以下任一买点信号（当天首次触发），且综合评分 ≥ **{p['min_score']}**，只做美股："
        + "、".join(f"{s}（{grade.get(s, '?')}）" for s in p["buy_signals"]) + "\n"
        f"- **仓位**：最多 **{p['max_positions']}** 只，等权；每只买入金额 = 决策日净值 ÷ {p['max_positions']}，"
        "有空位时按评分从高到低补入\n"
        "- **卖出**：持仓触发卖点信号 " + "、".join(f"{s}（{grade.get(s, '?')}）" for s in p["sell_signals"])
        + f"，或收盘价较平均成本下跌 ≥ **{p['stop_loss']:.0%}**（止损）\n"
        "- **时点**：每个交易日收盘后决策，**下一交易日开盘价**成交（不偷看未来），滑点 "
        f"{accs['auto']['slippage']:.2%}\n"
        "- 打开页面时自动补算到最近收盘日，补算出的交易写入流水后不再改动。")

pending = state.get("pending", [])
st.subheader("⏳ 下一交易日开盘待成交")
if pending:
    for o in pending:
        st.markdown(f"- {'🟢 买入' if o['side'] == 'buy' else '🔴 卖出'} **{o['ticker']}** "
                    f"{md['names'].get(o['ticker'], '')} — {o['reason']}")
else:
    st.caption("没有待成交订单。")

st.subheader("💼 持仓")
click_hint()
V.positions_table(snap, "auto_pos", md)

st.subheader("🧾 交易记录")
V.trades_table(snap["trades"], "auto_trades", md)

with st.expander("⚠️ 重置自动策略"):
    st.caption("清空自动账户全部交易，并从 Day 0 起按当前规则重新补算。")
    if st.checkbox("确认重置", key="confirm_reset_auto") and st.button("重置并重算"):
        ledger.reset_account("auto")
        st.session_state.pop(f"_caught_{md['close'].index[-1].date()}", None)
        st.rerun()
