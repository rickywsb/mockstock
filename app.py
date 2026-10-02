"""app.py — 模拟盘：自动策略 vs 我的账户，Day 0 起逐日跟踪"""

import importlib
import sys
from pathlib import Path

import streamlit as st


def _pyc_source_mtime(mod) -> int | None:
    """模块 .pyc 头里记录的源文件 mtime（即内存中这份代码编译时的源文件版本）。"""
    try:
        head = Path(mod.__cached__).read_bytes()[:16]
    except (OSError, TypeError, AttributeError):
        return None
    if len(head) < 16 or int.from_bytes(head[4:8], "little") != 0:   # 非 mtime 型 pyc
        return None
    return int.from_bytes(head[8:12], "little")


def _reload_stale_modules() -> None:
    """
    Streamlit Cloud 拉取新代码后只重跑脚本，已 import 的 config / core.* 仍是旧版本，
    页面 import 新函数时报 ImportError（以前只能手动 Reboot）。
    判定过期：源文件 mtime 与首次记录时不同；首次见到的模块则对比 .pyc 头里的源 mtime。
    任一过期就按依赖顺序重载全部 config / core.*（config 先行，core 两轮，
    修正模块间 from-import 留下的旧引用）。
    """
    seen: dict[str, float] = getattr(sys, "_mock_module_mtimes", None) or {}
    sys._mock_module_mtimes = seen
    mods = {n: m for n, m in list(sys.modules.items())
            if (n == "config" or n.startswith("core.")) and getattr(m, "__file__", None)}
    stale = False
    for name, mod in mods.items():
        try:
            mtime = Path(mod.__file__).stat().st_mtime
        except OSError:
            continue
        if name in seen:
            stale |= seen[name] != mtime
        else:
            pyc_mtime = _pyc_source_mtime(mod)
            stale |= pyc_mtime is not None and pyc_mtime != (int(mtime) & 0xFFFFFFFF)
        seen[name] = mtime
    if not stale:
        return
    order = (["config"] if "config" in mods else []) + sorted(n for n in mods if n != "config")
    for name in order + order[1:]:
        try:
            importlib.reload(sys.modules[name])
        except Exception:
            pass
        mod = sys.modules.get(name)
        if mod is not None and getattr(mod, "__file__", None):
            seen[name] = Path(mod.__file__).stat().st_mtime


_reload_stale_modules()

st.set_page_config(page_title="炒股大作战 · 你 vs 量化", page_icon="🎮", layout="wide", initial_sidebar_state="auto")

pg = st.navigation(
    {
        "开战": [
            st.Page("views/lobby.py", title="选股大厅", icon="🎯", url_path="lobby", default=True),
            st.Page("views/arena.py", title="对战", icon="⚔️", url_path="arena"),
        ],
        "我的": [
            st.Page("views/manual.py", title="我的仓位", icon="💼", url_path="manual"),
            st.Page("views/report.py", title="战报", icon="📜", url_path="report"),
        ],
        "对手": [
            st.Page("views/auto.py", title="量化对手", icon="🤖", url_path="auto"),
            st.Page("views/backtest.py", title="回测实验室", icon="🧪", url_path="backtest"),
        ],
        "情报": [
            st.Page("views/market.py", title="板块与高级选股", icon="🗺️", url_path="market"),
            st.Page("views/signals.py", title="持仓信号", icon="📊", url_path="signals"),
        ],
    },
    expanded=True,
)

if st.session_state.get("_last_page") != pg.url_path:
    st.session_state.pop("_chart_open", None)
    st.session_state["_last_page"] = pg.url_path

from core.ui import inject_css
from core import stock_chart
from core.sim import game, view as V

inject_css()
game.inject()
stock_chart.TRADE_PANEL = game.trade_panel        # 任何地方点开个股弹窗都能直接下单

# 记分牌：大厅 / 对战页完整显示，其余页面一行
accs, md = V.ensure()
you, quant = V.snapshot("manual", accs, md), V.snapshot("auto", accs, md)
spy = V.bench_series(md, accs["manual"]["day0"]).get("SPY")
spy_ret = float(spy.iloc[-1] / spy.iloc[0] - 1) if spy is not None and len(spy) else None
st.session_state["_snaps"] = {"manual": you, "auto": quant, "spy_ret": spy_ret}
game.scoreboard(you, quant, spy_ret, compact=pg.url_path not in ("", "lobby", "arena"))

if st.session_state.get("_toast"):
    st.toast(st.session_state.pop("_toast"), icon="🎮")
if st.session_state.pop("_balloons", False):
    st.balloons()

pg.run()
