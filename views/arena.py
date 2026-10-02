"""views/arena.py — ⚔️ 对战：收益曲线、日胜负、成就、战况播报、买卖点提醒"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

import config
from core.sim import game, ledger, report, view as V
from core.stock_chart import click_hint

accs, md = V.ensure()
S = st.session_state["_snaps"]
you, quant = S["manual"], S["auto"]
day0 = accs["manual"]["day0"]
as_of = str(md["close"].index[-1].date())
bench = V.bench_series(md, day0)

# ─── 曲线 ─────────────────────────────────────────────────────────────────────
st.subheader("📈 战况曲线（Day 0 起累计收益）")
if len(quant["series"]) < 2:
    st.info("🏁 今天是 Day 0，比赛刚开始！曲线从下一个交易日收盘后开始绘制；量化每天收盘后自动出招。"
            "去 🎯 选股大厅 先下手为强吧。")
else:
    st.plotly_chart(V.equity_chart({"你": you["series"], "量化": quant["series"], **bench}), width="stretch")

c = st.columns(4)
pm, pa = report.perf(you["series"], bench.get("SPY")), report.perf(quant["series"], bench.get("SPY"))
f = lambda v, fmt: "—" if v is None else format(v, fmt)
c[0].metric("🧑 你 · 最大回撤", f(pm.get("max_dd"), ".2%"))
c[1].metric("🤖 量化 · 最大回撤", f(pa.get("max_dd"), ".2%"))
tm, ta = report.trade_stats(you["trades"]), report.trade_stats(quant["trades"])
c[2].metric(f"🧑 你 · 胜率（{tm.get('n', 0)} 笔平仓）", f(tm.get("win_rate"), ".0%"))
c[3].metric(f"🤖 量化 · 胜率（{ta.get('n', 0)} 笔平仓）", f(ta.get("win_rate"), ".0%"))

# ─── 成就 ─────────────────────────────────────────────────────────────────────
ach = game.achievements(you, quant)
st.subheader(f"🏅 成就 {sum(a[3] for a in ach)} / {len(ach)}")
st.html('<div class="badges">' + "".join(
    f'<div class="badge {"" if ok else "off"}"><i>{e}</i><b>{n}</b><span>{d}</span></div>' for e, n, d, ok in ach) + "</div>")

# ─── 战况播报 ─────────────────────────────────────────────────────────────────
st.subheader("📣 战况播报")
allt = sorted(you["trades"] + quant["trades"], key=lambda x: (x["date"], x.get("created_at", "")), reverse=True)[:20]
verb = {"buy": "🟢 买入", "sell": "🔵 卖出", "short": "🔴 做空", "cover": "🟣 平空"}
if allt:
    st.html('<div class="feed">' + "".join(
        f'<div><span style="color:#6B6390">{t["date"]}</span> '
        f'<span class="{"who-you" if t["account"] == "manual" else "who-quant"}">{"🧑 你" if t["account"] == "manual" else "🤖 量化"}</span> '
        f'{verb[t["side"]]} <b>{t["ticker"]}</b> {t["qty"]:g} 股 @ {t["price"]:,.2f}'
        f'{" — " + t["reason"] if t.get("reason") else ""}</div>' for t in allt) + "</div>")
else:
    st.caption("还没有人出手。")

pending = ledger.load_state().get("auto", {}).get("pending", [])
if pending:
    st.markdown("**🤖 量化下一交易日开盘的招式：** " + "；".join(
        f"{'买' if o['side'] == 'buy' else '卖'} **{o['ticker']}**（{o['reason'].split('：', 1)[-1]}）" for o in pending))

# ─── 买卖点提醒 ───────────────────────────────────────────────────────────────
st.subheader(f"🔔 你的持仓提醒（{as_of} 收盘）")
click_hint()
held = {r["ticker"] for r in you["positions"]}
_, sells = V.today_signals(md, held)
rows = [dict(x, signal="卖点：" + x["signal"]) for x in sells]
stops = [r for r in you["positions"] if r["ret"] is not None and r["ret"] <= -config.AUTO_STRATEGY["stop_loss"]]
rows += [{"ticker": r["ticker"], "signal": f"{r['dir']} {r['ret']:+.1%}，已到 {config.AUTO_STRATEGY['stop_loss']:.0%} 止损线",
          "score": int(r["score"]) if r["score"] is not None else None} for r in stops
         if r["ticker"] not in {x["ticker"] for x in sells}]
V.signal_table(rows, "arena_alerts", md, "sell")
st.caption("卖点 = 历史检验为 A / B 级的卖出信号今天首次触发；止损线参照量化的 8% 规则。")
