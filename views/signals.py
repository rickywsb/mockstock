"""views/signals.py — 个股信号：模拟持仓（两个账户合计）的量能健康、技术图表"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import streamlit as st
import config
from core.sim import ledger
from core.ui import page_header, run_section

page_header("📊 持仓信号", "你和量化的持仓：动量、量能、斐波那契、背离等信号")
ledger.write_portfolio_shim()
pf = json.loads(config.PORTFOLIO_PATH.read_text(encoding="utf-8"))
if not any(a.get("positions") for a in pf.get("accounts", [])):
    st.info("你和量化目前都没有持仓。买入股票后，这里会显示它们的动量与量能分析。")
    st.stop()
run_section("momentum")
