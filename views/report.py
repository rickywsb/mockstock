"""views/report.py — 持仓报告：随时生成，含指标、曲线、持仓、已平仓交易、按股票盈亏，可下载"""
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from core.sim import ledger, report, view as V
from core.ui import page_header

accs, md = V.ensure()
page_header("持仓报告", "随时生成；指标按每日收盘价计算，持仓按最新价")

acc = st.segmented_control(" ", list(ledger.ACCOUNT_IDS), format_func=ledger.ACCOUNT_NAMES.get, default="manual",
                           key="rep_acc", label_visibility="collapsed") or "manual"
snap = V.snapshot(acc, accs, md)
bench = V.bench_series(md, snap["day0"])
p = report.perf(snap["series"], bench.get("SPY"))
ts = report.trade_stats(snap["trades"])
other = V.snapshot("auto" if acc == "manual" else "manual", accs, md)


def f(v, fmt):
    return "—" if v is None else format(v, fmt)


c = st.columns(5)
c[0].metric("净值", V.money(snap["nav"]), f"{snap['ret']:+.2%}")
c[1].metric("相对 SPY", f(p.get("excess"), "+.2%"), help="按收盘价，Day 0 起")
c[2].metric(f"相对{other['name']}", f"{snap['ret'] - other['ret']:+.2%}")
c[3].metric("最大回撤", f(p.get("max_dd"), ".2%"))
c[4].metric("夏普 / β", f"{f(p.get('sharpe'), '.2f')} / {f(p.get('beta'), '.2f')}")

c = st.columns(5)
c[0].metric("买入笔数", ts.get("n_buys", 0))
c[1].metric("已平仓 · 胜率", f"{ts.get('n', 0)} · {f(ts.get('win_rate'), '.0%')}")
c[2].metric("平均盈利 / 亏损", f"{f(ts.get('avg_win'), '+.1%')} / {f(ts.get('avg_loss'), '+.1%')}")
c[3].metric("盈亏比", f(ts.get("profit_factor"), ".2f"), help="已平仓：总盈利 ÷ 总亏损")
c[4].metric("平均持有天数", f(ts.get("avg_days"), ".0f"))

lines = {snap["name"]: snap["series"], other["name"]: other["series"], **bench}
if len(snap["series"]) > 1:
    st.plotly_chart(V.equity_chart(lines, height=320), width="stretch")
if len(snap["series"]) > 2:
    st.plotly_chart(V.drawdown_chart(snap["series"]), width="stretch")
else:
    st.caption("净值曲线从 Day 0 的下一个交易日收盘后开始绘制。")

st.subheader("💼 当前持仓")
V.positions_table(snap, "rep_pos", md)

st.subheader("📊 按股票盈亏（已实现 + 浮动）")
last_px = {r["ticker"]: r["last"] for r in snap["positions"]}
tp = report.ticker_pnl(snap["trades"], last_px)
if tp.empty:
    st.caption("暂无交易")
else:
    st.dataframe(tp.rename(columns={"ticker": "股票", "qty": "持股", "avg": "成本", "last": "最新价",
                                    "realized": "已实现", "unrealized": "浮动", "total": "合计"})
                 .style.format({"持股": "{:.0f}", "成本": "{:,.2f}", "最新价": "{:,.2f}", "已实现": "{:+,.0f}",
                                "浮动": "{:+,.0f}", "合计": "{:+,.0f}"}, na_rep="—"),
                 hide_index=True, width="stretch")

st.subheader("✅ 已平仓交易")
ct = ledger.closed_trades(snap["trades"])
if ct.empty:
    st.caption("暂无已平仓交易")
else:
    st.dataframe(ct.rename(columns={"ticker": "股票", "entry": "建仓", "exit": "卖出", "qty": "股数",
                                    "avg_cost": "成本", "exit_price": "卖出价", "pnl": "盈亏", "ret": "收益",
                                    "days": "天数", "reason": "理由", "signal": "信号"})
                 .style.format({"股数": "{:.0f}", "成本": "{:,.2f}", "卖出价": "{:,.2f}", "盈亏": "{:+,.0f}",
                                "收益": "{:+.1%}"}, na_rep="—"), hide_index=True, width="stretch")


# ─── 下载 ─────────────────────────────────────────────────────────────────────
def _md_report() -> str:
    L = [f"# 模拟盘持仓报告 · {snap['name']}", "",
         f"生成时间：{datetime.now():%Y-%m-%d %H:%M}　Day 0：{snap['day0']}　行情截至：{md['close'].index[-1].date()}", "",
         "## 表现", "",
         f"- 净值 {V.money(snap['nav'])}（{snap['ret']:+.2%}），现金 {V.money(snap['cash'])}",
         f"- 相对 SPY {f(p.get('excess'), '+.2%')}；相对{other['name']} {snap['ret'] - other['ret']:+.2%}",
         f"- 最大回撤 {f(p.get('max_dd'), '.2%')}，夏普 {f(p.get('sharpe'), '.2f')}，β {f(p.get('beta'), '.2f')}",
         f"- 买入 {ts.get('n_buys', 0)} 笔，已平仓 {ts.get('n', 0)} 笔，胜率 {f(ts.get('win_rate'), '.0%')}，"
         f"盈亏比 {f(ts.get('profit_factor'), '.2f')}", "", "## 持仓", "",
         "| 股票 | 股数 | 成本 | 最新价 | 市值 | 收益 | 仓位 | 评分 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in sorted(snap["positions"], key=lambda r: -r["mv"]):
        L.append(f"| {r['ticker']} | {r['qty']:.0f} | {r['avg']:,.2f} | {r['last']:,.2f} | {r['mv']:,.0f} | "
                 f"{f(r['ret'], '+.1%')} | {f(r['weight'], '.1%')} | {f(r['score'], '.0f')} |")
    L += ["", "## 交易记录", "", "| 日期 | 股票 | 方向 | 股数 | 价格 | 理由 |", "|---|---|---|---:|---:|---|"]
    for t in sorted(snap["trades"], key=lambda x: x["date"], reverse=True):
        L.append(f"| {t['date']} | {t['ticker']} | {V.SIDE_TXT[t['side']]} | {t['qty']:.0f} | {t['price']:,.2f} | "
                 f"{t.get('reason', '')} |")
    return "\n".join(L) + "\n"


d1, d2 = st.columns(2)
d1.download_button("⬇️ 下载报告（Markdown）", _md_report(), file_name=f"report_{acc}_{datetime.now():%Y%m%d}.md",
                   mime="text/markdown")
d2.download_button("⬇️ 下载交易流水（CSV）", pd.DataFrame(snap["trades"]).to_csv(index=False),
                   file_name=f"trades_{acc}.csv", mime="text/csv")
