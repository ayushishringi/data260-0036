"""HW10 Part 1: Streamlit operations dashboard for the s0036 cache + Kafka agent pipeline.

Three pages (dashboard/hw10_pages/): Summary, Evaluation, Trace lookup; the page code and the cached
loaders are in dashboard/hw10_views.py.

Usage: make dashboard-hw10   (http://localhost:8038)
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.hw10_views import NAME  # noqa: E402

st.set_page_config(page_title="s0036 operations", page_icon="📊", layout="wide")
page = st.navigation([st.Page("hw10_pages/summary.py", title="Summary", icon="📈", default=True),
                      st.Page("hw10_pages/evaluation.py", title="Evaluation", icon="🧪"),
                      st.Page("hw10_pages/trace.py", title="Trace lookup", icon="🔎")])
with st.sidebar:
    st.markdown(f"**{NAME}**")
    st.caption("HW10 operations dashboard · data refresh every 15 s (`@st.cache_data`)")
    if st.button("Reload data now"):
        st.cache_data.clear()
page.run()
