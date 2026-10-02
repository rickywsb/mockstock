"""views/market.py — 市场：板块雷达 / 选股器"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.ui import page_header, section_switch, run_section

page_header("🗺️ 板块与高级选股", "板块强弱与轮动；更多技术面条件的全市场选股（RS 评级、象限、均线等）")
sid = section_switch({"板块雷达": "sectors", "高级选股": "screener"}, key="sw_mkt")
run_section(sid)
