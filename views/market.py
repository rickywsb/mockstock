"""views/market.py — 市场：板块雷达 / 选股器"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.ui import page_header, section_switch, run_section

page_header("市场", "板块强弱与轮动；全市场选股（S&P 500 ∪ Nasdaq-100）")
sid = section_switch({"选股器": "screener", "板块雷达": "sectors"}, key="sw_mkt")
run_section(sid)
