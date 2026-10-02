"""views/backtest.py — 回测：用自动账户同一套撮合在过去 2 年数据上验证规则"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

import config
from core import signal_lab
from core.sim import ledger, report, strategy, view as V
from core.ui import page_header

accs, md = V.ensure()
page_header("回测", "同一套撮合规则（收盘决策、次日开盘成交）在过去约 2 年的全市场数据上跑一遍")

lab = signal_lab.load_summary()
grade = dict(zip(lab["summary"]["信号"], lab["summary"]["grade"])) if lab else {}
buy_opts = [n for n, _, e, _ in signal_lab.SIGNALS if e > 0 and n in md["onsets"]]
sell_opts = [n for n, _, e, _ in signal_lab.SIGNALS if e < 0 and n in md["onsets"]]
lab_fmt = lambda s: f"{s}（{grade[s]}）" if s in grade else s
dates = md["close"].index
p0 = config.AUTO_STRATEGY

with st.form("bt"):
    c = st.columns(4)
    start = c[0].date_input("开始日期", value=max(dates[260], dates[-1] - pd.Timedelta(days=365)).date(),
                            min_value=dates[260].date(), max_value=dates[-2].date(),
                            help="前约 1 年数据用于计算 52 周新高、MA200 等指标，开始日期不能更早")
    max_n = c[1].number_input("最多持仓", 1, 30, int(p0["max_positions"]))
    min_score = c[2].slider("评分门槛", 0, 99, int(p0["min_score"]))
    stop = c[3].slider("止损 %", 0, 30, int(p0["stop_loss"] * 100)) / 100
    buys = st.multiselect("买入信号", buy_opts, default=[s for s in p0["buy_signals"] if s in buy_opts],
                          format_func=lab_fmt)
    sells = st.multiselect("卖出信号", sell_opts, default=[s for s in p0["sell_signals"] if s in sell_opts],
                           format_func=lab_fmt)
    c = st.columns(3)
    initial = c[0].number_input("初始资金 $", 1000.0, 10_000_000.0, float(config.SIM_INITIAL_CASH), step=10000.0)
    slip = c[1].number_input("滑点 %", 0.0, 2.0, config.SIM_SLIPPAGE * 100, step=0.05) / 100
    run = st.form_submit_button("▶️ 运行回测", type="primary")

if run:
    params = {**p0, "buy_signals": buys, "sell_signals": sells, "min_score": min_score,
              "max_positions": int(max_n), "stop_loss": stop if stop > 0 else 9.99}
    with st.spinner("回测中…"):
        st.session_state["bt_res"] = (strategy.backtest(md, params, start.isoformat(), initial, slip), params)

res = st.session_state.get("bt_res")
if not res:
    st.info("设置参数后点击运行。默认参数 = 当前自动策略的规则。")
    st.stop()
bt, params = res
nav = bt["nav"]
if nav.empty:
    st.warning("区间内没有交易。")
    st.stop()
bench = {t: s[s.index >= nav.index[0]] for t, s in V.bench_series(md, str(nav.index[0].date())).items()}
p = report.perf(nav, bench.get("SPY"))
ts = report.trade_stats(bt["trades"])
f = lambda v, fmt: "—" if v is None else format(v, fmt)

c = st.columns(5)
c[0].metric("总收益", f(p.get("total"), "+.1%"), f"SPY {f(p.get('bench_total'), '+.1%')}", delta_color="off")
c[1].metric("年化", f(p.get("cagr"), "+.1%"))
c[2].metric("最大回撤", f(p.get("max_dd"), ".1%"))
c[3].metric("夏普 / β", f"{f(p.get('sharpe'), '.2f')} / {f(p.get('beta'), '.2f')}")
c[4].metric("平均仓位", f(report.exposure(bt["trades"], nav, V.closes_for({t['ticker'] for t in bt['trades']}, md)), ".0%"))
c = st.columns(5)
c[0].metric("买入笔数", ts.get("n_buys", 0))
c[1].metric("已平仓 · 胜率", f"{ts.get('n', 0)} · {f(ts.get('win_rate'), '.0%')}")
c[2].metric("平均盈利 / 亏损", f"{f(ts.get('avg_win'), '+.1%')} / {f(ts.get('avg_loss'), '+.1%')}")
c[3].metric("盈亏比", f(ts.get("profit_factor"), ".2f"))
c[4].metric("平均持有天数", f(ts.get("avg_days"), ".0f"))

st.plotly_chart(V.equity_chart({"回测策略": nav, **bench}), width="stretch")
st.plotly_chart(V.drawdown_chart(nav), width="stretch")

held = ledger.open_positions(bt["trades"])
last_px = {t: float(md["close"][t].dropna().iloc[-1]) for t in held if t in md["close"].columns}
st.subheader("📊 按股票盈亏")
tp = report.ticker_pnl(bt["trades"], last_px)
if not tp.empty:
    st.dataframe(tp.head(30).rename(columns={"ticker": "股票", "qty": "期末持股", "avg": "成本", "last": "最新价",
                                             "realized": "已实现", "unrealized": "浮动", "total": "合计"})
                 .style.format({"期末持股": "{:.0f}", "成本": "{:,.2f}", "最新价": "{:,.2f}", "已实现": "{:+,.0f}",
                                "浮动": "{:+,.0f}", "合计": "{:+,.0f}"}, na_rep="—"), hide_index=True, width="stretch")
st.subheader("🧾 交易记录")
V.trades_table(bt["trades"], "bt_trades", md, limit=300)
st.download_button("⬇️ 下载回测交易（CSV）", pd.DataFrame(bt["trades"]).to_csv(index=False), "backtest_trades.csv",
                   "text/csv")
st.warning(
    "**回测的局限**：① 股票池是**今天**的 S&P 500 / Nasdaq-100 成分股，过去被剔除的股票不在里面（幸存者偏差，结果偏乐观）；"
    "② 综合评分是全市场百分位，用的是当时可得的数据，但评分方法本身是看过这 2 年数据后设计的（有过拟合风险）；"
    "③ 按开盘价成交、固定滑点，未计跳空无法成交、流动性冲击和税费。请把回测当作规则的「健全性检查」，"
    "真正的检验是 Day 0 起的模拟盘。")
