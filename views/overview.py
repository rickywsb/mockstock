"""views/overview.py — 总览：两个账户对比、净值曲线、待成交订单、今日买卖点"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

import config
from core.sim import ledger, report, view as V
from core.stock_chart import click_hint
from core.ui import page_header

accs, md = V.ensure()
day0 = accs["auto"]["day0"]
as_of = str(md["close"].index[-1].date())
page_header("模拟盘总览", f"Day 0 = {day0} ｜ 每个账户初始资金 {V.money(accs['auto']['initial_cash'])} ｜ "
                       f"行情截至 {as_of} 收盘 ｜ 滑点 {accs['auto']['slippage']:.2%}，零佣金")

snaps = {a: V.snapshot(a, accs, md) for a in ledger.ACCOUNT_IDS}
bench = V.bench_series(md, day0)

# ─── 账户卡片 ──────────────────────────────────────────────────────────────────
cols = st.columns(4)
for col, a in zip(cols[:2], ledger.ACCOUNT_IDS):
    s = snaps[a]
    col.metric(f"{'🤖' if a == 'auto' else '🧑‍💼'} {s['name']} · 净值", V.money(s["nav"]), f"{s['ret']:+.2%}",
               help=f"现金 {V.money(s['cash'])} ｜ 持仓 {len(s['positions'])} 只（按最新价）")
for col, (t, s) in zip(cols[2:], bench.items()):
    col.metric(f"{t} · Day 0 起", f"{s.iloc[-1]:,.2f}", f"{s.iloc[-1] / s.iloc[0] - 1:+.2%}",
               help="基准：同期买入并持有（按收盘价）")

diff = snaps["manual"]["ret"] - snaps["auto"]["ret"]
spy_ret = bench["SPY"].iloc[-1] / bench["SPY"].iloc[0] - 1 if "SPY" in bench else None
msg = f"我的账户 {'领先' if diff >= 0 else '落后'}自动策略 **{abs(diff):.2%}**"
if spy_ret is not None:
    msg += (f"；相对 SPY：自动策略 {snaps['auto']['ret'] - spy_ret:+.2%}，"
            f"我的账户 {snaps['manual']['ret'] - spy_ret:+.2%}")
st.markdown(msg)

# ─── 净值曲线 ──────────────────────────────────────────────────────────────────
st.subheader("📈 Day 0 起累计收益")
lines = {snaps[a]["name"]: snaps[a]["series"] for a in ledger.ACCOUNT_IDS}
lines.update(bench)
if len(snaps["auto"]["series"]) < 2:
    st.info("今天是 Day 0：曲线从下一个交易日收盘后开始绘制。每天收盘后打开页面会自动更新（自动账户会补算错过的交易日）。")
else:
    st.plotly_chart(V.equity_chart(lines), width="stretch")

# 关键指标对比
mrows = []
for a in ledger.ACCOUNT_IDS:
    s = snaps[a]
    p = report.perf(s["series"], bench.get("SPY"))
    ts = report.trade_stats(s["trades"])
    mrows.append({"账户": s["name"], "收益（收盘）": p.get("total"), "最大回撤": p.get("max_dd"),
                  "夏普": p.get("sharpe"), "β": p.get("beta"), "持仓数": len(s["positions"]),
                  "现金占比": s["cash"] / s["nav"] if s["nav"] else None,
                  "买入笔数": ts.get("n_buys", 0), "已平仓": ts.get("n", 0), "胜率": ts.get("win_rate")})
fmts = {"收益（收盘）": "{:+.2%}", "最大回撤": "{:.2%}", "夏普": "{:.2f}", "β": "{:.2f}", "现金占比": "{:.0%}",
        "胜率": "{:.0%}"}
st.dataframe([{k: (fmts[k].format(v) if v is not None else "—") if k in fmts else v for k, v in r.items()}
              for r in mrows], hide_index=True, width="stretch")
st.caption("曲线与上表按每日收盘价计算；卡片净值按最新价（盘中有数分钟延迟）。样本少于 5 天时夏普 / β 不显示。")

# ─── 自动策略待成交 ────────────────────────────────────────────────────────────
pending = ledger.load_state().get("auto", {}).get("pending", [])
st.subheader("🤖 自动策略 · 下一交易日开盘待成交")
if pending:
    for o in pending:
        icon = "🟢 买入" if o["side"] == "buy" else "🔴 卖出"
        st.markdown(f"- {icon} **{o['ticker']}** {md['names'].get(o['ticker'], '')} — {o['reason']}"
                    f"（{o['decided']} 收盘后决策）")
    st.caption("自动账户在每个交易日收盘后决策，下一交易日开盘价成交；买入金额 = 决策日净值 ÷ "
               f"{config.AUTO_STRATEGY['max_positions']}（现金不足时按剩余现金）。")
else:
    st.caption("没有待成交订单。")

# ─── 今日买卖点 ────────────────────────────────────────────────────────────────
st.subheader(f"🔔 买卖点提醒（{as_of} 收盘）")
click_hint()
held_manual = {r["ticker"] for r in snaps["manual"]["positions"]}
held_auto = {r["ticker"] for r in snaps["auto"]["positions"]}
buys, sells = V.today_signals(md, held_manual | held_auto)
c1, c2 = st.columns([3, 2])
with c1:
    st.markdown(f"**买点**（A / B 级买入信号，评分 ≥{config.AUTO_STRATEGY['min_score']}，美股）")
    V.signal_table(buys, "ov_buys", md, "buy", held_manual)
with c2:
    st.markdown("**卖点**（两个账户的持仓）")
    sell_rows = [dict(x, signal=x["signal"] + ("（我的账户）" if x["ticker"] in held_manual else "")
                      + ("（自动）" if x["ticker"] in held_auto else "")) for x in sells]
    stops = [r for r in snaps["manual"]["positions"]
             if r["ret"] is not None and r["ret"] <= -config.AUTO_STRATEGY["stop_loss"]]
    sell_rows += [{"ticker": r["ticker"], "signal": f"较成本 {r['ret']:+.1%}，已到 {config.AUTO_STRATEGY['stop_loss']:.0%} 止损线（我的账户）",
                   "score": int(r["score"]) if r["score"] is not None else None} for r in stops
                  if r["ticker"] not in {x["ticker"] for x in sells}]
    V.signal_table(sell_rows, "ov_sells", md, "sell")
st.caption("信号来自全市场信号实验室中历史检验为 A / B 级的信号；只在触发当天出现（降噪）。仅供模拟研究，非投资建议。")
