"""views/lobby.py — 🎯 选股大厅：筛选 → 点开个股看图 → 直接买入 / 做空"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from core import stock_chart as SC
from core.sim import game, ledger, view as V
from core.ui import pz_table, pct

accs, md = V.ensure()
snaps = st.session_state["_snaps"]
as_of = str(md["close"].index[-1].date())
df = game.lobby_frame(md)

# ─── 对手动向 ─────────────────────────────────────────────────────────────────
pending = ledger.load_state().get("auto", {}).get("pending", [])
chips = "".join(f'<span class="chip {"b" if o["side"] == "buy" else "s"}">{"买" if o["side"] == "buy" else "卖"} {o["ticker"]}</span>'
                for o in pending) or '<span style="color:#6B6390">按兵不动</span>'
st.html(f'<div class="chips" style="margin:6px 0 2px"><b>🤖 量化下一交易日开盘：</b>{chips}'
        f'<span style="color:#6B6390;font-size:13px">（{as_of} 收盘后决策 · 你要跟单还是反着来？）</span></div>')

st.html('<div class="pz-title" style="margin-top:10px">🎯 选股大厅</div>'
        f'<div class="pz-sub">约 {len(df)} 只美股（S&P 500 ∪ Nasdaq-100）｜ 行情截至 {as_of} 收盘 ｜ '
        '点任意一行 → 看技术图表 → 直接 🟢 买入 或 🔴 做空</div>')

# ─── 筛选 ─────────────────────────────────────────────────────────────────────
names = list(game.PRESETS)
preset = st.segmented_control(" ", names, default=names[0], key="lobby_preset", label_visibility="collapsed") or names[0]
desc, fn = game.PRESETS[preset]

with st.container(border=True):
    f = st.columns([1.3, 2, 1.4, 1.2, 0.9])
    q = f[0].text_input("🔍 搜索", placeholder="代码或名称", key="lobby_q").strip().lower()
    sectors = sorted(s for s in df["sector"].unique() if s)
    pick = f[1].multiselect("行业", sectors, key="lobby_sec", placeholder="全部行业")
    lo, hi = f[2].slider("评分", 1, 99, (1, 99), key="lobby_score")
    sort = f[3].selectbox("排序", ["评分", "当日涨跌", "20 日涨跌", "量比", "距 52 周高"], key="lobby_sort")
    f[4].write("")
    f[4].write("")
    lucky = f[4].button("🎲 手气", help="从当前结果里随机抽一只", width="stretch")

res = fn(df)
if q:
    res = res[res["ticker"].str.lower().str.contains(q, regex=False) | res["name"].str.lower().str.contains(q, regex=False)]
if pick:
    res = res[res["sector"].isin(pick)]
res = res[(res["score"] >= lo) & (res["score"] <= hi)]
key_col = {"评分": "score", "当日涨跌": "chg", "20 日涨跌": "ret20", "量比": "vr", "距 52 周高": "off_high"}[sort]
res = res.sort_values(key_col, ascending=preset == "🧊 做空雷达" and key_col == "score")

st.caption(f"**{preset}** — {desc} ｜ 命中 **{len(res)}** 只" + ("（显示前 80）" if len(res) > 80 else ""))

if lucky:
    t = game.lucky(res)
    if t:
        st.session_state[SC._OPEN] = {"owner": "lobby_tbl", "ticker": t, "name": md["names"].get(t, t)}

mine = {r["ticker"]: r["dir"] for r in snaps["manual"]["positions"]}
theirs = {r["ticker"] for r in snaps["auto"]["positions"]}
rows = []
for r in res.head(80).to_dict("records"):
    t = r["ticker"]
    tag = ("你持有" if mine.get(t) == "做多" else "你做空" if mine.get(t) == "做空" else
           "量化持有" if t in theirs else "")
    sig = " · ".join(x for x in [("▲ " + r["buy_sig"]) if r["buy_sig"] else "", ("▼ " + r["sell_sig"]) if r["sell_sig"] else ""] if x)
    rows.append({"ticker": t, "name": r["name"], "sub": " · ".join(x for x in [r["name"] if r["name"] != t else "", r["sector"]] if x),
                 "price_txt": f"{r['price']:,.2f}", "chg": pct(r["chg"]),
                 "score": int(r["score"]), "d5": int(r["score"] - r["score_5d"]) if r["score_5d"] == r["score_5d"] and r["score_5d"] is not None else None,
                 "spark": r["spark"], "ret20": pct(r["ret20"]), "off_high": pct(r["off_high"]),
                 "vr": r["vr"], "sig": sig, "tag": tag})
cols = [
    {"key": "ticker", "label": "股票", "kind": "stock", "width": "minmax(150px,1.4fr)", "sortable": True},
    {"key": "price_txt", "label": "价格 · 当日", "kind": "price", "chg": "chg", "width": "100px", "sortable": True, "sortKey": "chg"},
    {"key": "score", "label": "评分", "kind": "score", "delta": "d5", "width": "96px", "sortable": True},
    {"key": "spark", "label": "20 日走势", "kind": "spark", "width": "92px"},
    {"key": "ret20", "label": "20 日", "kind": "num", "decimals": 1, "suffix": "%", "sign": True, "color": True,
     "width": "70px", "align": "right", "sortable": True},
    {"key": "off_high", "label": "距 52 周高", "kind": "num", "decimals": 1, "suffix": "%", "color": True,
     "width": "80px", "align": "right", "sortable": True},
    {"key": "vr", "label": "量比", "kind": "num", "decimals": 1, "suffix": "×", "hot": 2, "width": "60px",
     "align": "right", "sortable": True},
    {"key": "sig", "label": "今日信号", "kind": "small", "width": "minmax(150px,1.6fr)"},
    {"key": "tag", "label": "", "kind": "pill", "width": "76px"},
]
pz_table(rows, cols, key="lobby_tbl", sort=None, empty="没有符合条件的股票，换个关卡试试 🎲", min_width=1000)
st.caption("评分 = 全市场综合评分百分位（趋势 / 量能 / 板块 / 健康）；▲▼ = 历史检验为 A / B 级的买卖点今天首次触发。"
           "做空：卖出借来的股票，股价下跌赚钱；不加杠杆（多空总市值 ≤ 净值）。仅供模拟游戏，非投资建议。")
