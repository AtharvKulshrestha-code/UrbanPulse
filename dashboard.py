from pathlib import Path
import io
import json
import os
import urllib.error
import urllib.request

import altair as alt
import math
import pandas as pd
import pydeck as pdk
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

import hashlib
import itertools
import numbers
from contextlib import contextmanager
from datetime import datetime
from html import escape as esc
from urllib.parse import quote

# UrbanPulse — Stitch-inspired dashboard using the real rainfall dataset.
# Rainfall observations are historical source data; no flood predictions are made.

st.set_page_config(
    page_title="UrbanPulse | Rainfall Intelligence",
    page_icon="🌧️",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE = Path(__file__).resolve().parent
CANDIDATE_PATHS = [
    BASE / "data" / "processed" / "bengaluru_geo_filtered.csv",
    BASE / "data" / "processed" / "bengaluru_rainfall.csv",
    BASE / "data" / "rainfall_data.csv",
]
TIME_COL = "Data Acquisition Time"
STATION_COL = "Station"
RAIN_COL = "Telemetry Hourly Rainfall (mm)"
LAT_COL = "Latitude"
LON_COL = "Longitude"


# ═════════════════════════════════════════════════════════════════════════════
# DESIGN SYSTEM — tokens, CSS and small reusable UI helpers (presentation only)
# ═════════════════════════════════════════════════════════════════════════════
TOKENS = {
    # Elevation: canvas → surface → raised → overlay
    "bg-0": "#060a11", "bg-1": "#0c121c", "bg-2": "#121a27", "bg-3": "#1a2538",
    "panel-bg": "linear-gradient(180deg,rgba(255,255,255,.035),rgba(255,255,255,0) 42%),rgba(14,21,33,.74)",
    # Borders
    "border-subtle": "rgba(148,163,184,.12)", "border": "rgba(148,163,184,.22)", "border-strong": "rgba(148,163,184,.38)",
    # Text (all ≥ 4.5:1 on bg-1/bg-2)
    "text-1": "#e9eef6", "text-2": "#a8b5c9", "text-3": "#8697af",
    # Accent — used for active states, primary actions and focus only
    "accent": "#00f0ff", "accent-soft": "rgba(0,240,255,.10)", "accent-line": "rgba(0,240,255,.38)", "accent-ink": "#021419",
    # Status
    "success": "#34d399", "success-soft": "rgba(52,211,153,.12)",
    "warning": "#fbbf24", "warning-soft": "rgba(251,191,36,.12)",
    "danger": "#f87171", "danger-soft": "rgba(248,113,113,.12)",
    "info": "#60a5fa", "info-soft": "rgba(96,165,250,.12)",
    # Radii, spacing, shadows
    "r-sm": "8px", "r-md": "12px", "r-lg": "16px",
    "sp-1": "4px", "sp-2": "8px", "sp-3": "12px", "sp-4": "16px", "sp-5": "24px", "sp-6": "32px",
    "shadow-1": "0 1px 2px rgba(0,0,0,.4)", "shadow-2": "0 8px 24px rgba(0,0,0,.35)", "shadow-3": "0 18px 44px rgba(0,0,0,.5)",
    "glow": "inset 0 1px 0 rgba(255,255,255,.05),inset 0 0 28px rgba(0,240,255,.022)",
    # Type scale 12 / 14 / 16 / 20 / 28 / 36
    "fs-xs": "12px", "fs-sm": "14px", "fs-md": "16px", "fs-lg": "20px", "fs-xl": "28px", "fs-2xl": "36px",
    "font-ui": "'Plus Jakarta Sans',system-ui,-apple-system,'Segoe UI',sans-serif",
    "font-mono": "'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace",
    "ease": "cubic-bezier(.2,.8,.2,1)", "dur": "180ms",
}
T = TOKENS
UI_PLAIN = "Plus Jakarta Sans,system-ui,sans-serif"
MONO_PLAIN = "JetBrains Mono,ui-monospace,monospace"

# Okabe–Ito–derived, colour-blind-friendly categorical palette (tuned for dark backgrounds)
PALETTE = ["#56b4e9", "#e69f00", "#009e73", "#cc79a7", "#f0e442", "#d55e00", "#8da0cb", "#b8c4d6"]

# Rainfall-intensity scales: (lower bound, legend label, RGB). Thresholds mirror the original map logic.
RAIN_SCALE = [
    (0, "< 25", (56, 189, 248)),
    (25, "25–50", (250, 204, 21)),
    (50, "50–75", (249, 115, 22)),
    (75, "≥ 75", (239, 68, 68)),
]
FORECAST_SCALE = [
    (0, "0", (56, 189, 248)),
    (1e-9, "> 0", (250, 204, 21)),
    (15, "≥ 15", (249, 115, 22)),
    (30, "≥ 30", (239, 68, 68)),
]
DQ_ISSUE_SHARE = 0.10  # presentation heuristic: ≥10% of a station's intervals over threshold → "Issue"
HTML_TABLE_LIMIT = 400  # larger tables fall back to the native (virtualised, sortable) grid

ICON_PATHS = {
    "layout": '<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "radio": '<path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9"/><path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5"/><circle cx="12" cy="12" r="2"/><path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5"/><path d="M19.1 4.9C23 8.8 23 15.1 19.1 19"/>',
    "map": '<polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21"/><line x1="9" x2="9" y1="3" y2="18"/><line x1="15" x2="15" y1="6" y2="21"/>',
    "chart": '<path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>',
    "table": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18M3 15h18M12 3v18"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
    "pin": '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
    "rain": '<path d="M4 14.9A7 7 0 1 1 15.7 8h1.8a4.5 4.5 0 0 1 2.5 8.2"/><path d="M16 14v6M8 14v6M12 16v6"/>',
    "gauge": '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4M12 17h.01"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "xcircle": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    "inbox": '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "filter": '<path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z"/>',
    "sliders": '<path d="M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3M14 2v4M8 10v4M16 18v4"/>',
    "calendar": '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
}
NAV_ICONS = ["layout", "target", "radio", "map", "chart", "table", "shield"]  # same order as the nav items

_CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');
:root{/*TOKENS*/color-scheme:dark}

/* ── Base & chrome ───────────────────────────────────────────── */
html,body,.stApp,[data-testid="stAppViewContainer"]{font-family:var(--font-ui);-webkit-font-smoothing:antialiased}
.stApp{color:var(--text-1);background:radial-gradient(1100px 520px at 10% -10%,rgba(0,240,255,.055),transparent 60%),radial-gradient(900px 460px at 100% 0%,rgba(96,165,250,.05),transparent 60%),var(--bg-0)}
#MainMenu,footer,.stDeployButton,[data-testid="stAppDeployButton"],[data-testid="stMainMenu"],[data-testid="stToolbarActions"],[data-testid="stDecoration"]{display:none!important}
[data-testid="stHeader"]{background:transparent}
.block-container{max-width:1600px;padding:64px var(--sp-6) 64px}
h1,h2,h3,h4{color:var(--text-1)!important;letter-spacing:-.01em}
[data-testid="stMarkdownContainer"] p,[data-testid="stMarkdownContainer"] li{color:var(--text-2);font-size:var(--fs-sm);line-height:1.6}
[data-testid="stMarkdownContainer"] a{color:var(--accent)}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p{color:var(--text-3)!important;font-size:var(--fs-xs)!important;line-height:1.55}
:focus-visible{outline:2px solid var(--accent)!important;outline-offset:2px!important}
.up-mono{font-family:var(--font-mono);font-variant-numeric:tabular-nums}

/* ── Top bar & chips ─────────────────────────────────────────── */
.up-topbar{display:flex;align-items:center;justify-content:space-between;gap:var(--sp-4);flex-wrap:wrap;padding:var(--sp-3) var(--sp-4);margin-bottom:var(--sp-5);border:1px solid var(--border-subtle);border-radius:var(--r-lg);background:var(--panel-bg);box-shadow:var(--glow),var(--shadow-1);backdrop-filter:blur(12px)}
.up-brand{display:flex;align-items:center;gap:var(--sp-3)}
.up-brand-name{font-size:var(--fs-md);font-weight:700;letter-spacing:-.01em;line-height:1.2;color:var(--text-1)}
.up-brand-sub{font-size:var(--fs-xs);color:var(--text-3)}
.up-topbar-meta{display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap}
.up-chip{display:inline-flex;align-items:center;gap:var(--sp-2);padding:6px 12px;border-radius:999px;border:1px solid var(--border);background:var(--bg-2);color:var(--text-2);font-size:var(--fs-xs);font-weight:500;line-height:1.4;white-space:nowrap}
.up-chip .up-mono{color:var(--text-1)}
.up-chip svg{color:var(--text-3)}
.up-chip-sep{width:1px;height:12px;background:var(--border)}
.up-dot{width:8px;height:8px;border-radius:50%;background:var(--text-3);flex:none}
.up-dot--ok{background:var(--success);animation:up-ping 2.4s infinite}
.up-dot--warn{background:var(--warning)}.up-dot--issue{background:var(--danger)}.up-dot--info{background:var(--info)}
@keyframes up-ping{0%{box-shadow:0 0 0 0 rgba(52,211,153,.5)}70%,100%{box-shadow:0 0 0 7px rgba(52,211,153,0)}}

/* ── Section & panel headings ────────────────────────────────── */
.up-section{display:flex;align-items:flex-start;gap:var(--sp-3);margin:var(--sp-2) 0 var(--sp-4)}
.up-section-icon{display:grid;place-items:center;width:36px;height:36px;flex:none;border-radius:var(--r-md);background:var(--bg-2);border:1px solid var(--border);color:var(--text-2)}
.up-section-title{font-size:var(--fs-lg);font-weight:700;letter-spacing:-.015em;line-height:1.25;color:var(--text-1)}
.up-section-desc{font-size:var(--fs-sm);line-height:1.5;color:var(--text-2);margin-top:var(--sp-1);max-width:76ch}
.up-panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-3)}
.up-panel-title{font-size:var(--fs-md);font-weight:700;letter-spacing:-.01em;line-height:1.3;color:var(--text-1)}
.up-panel-desc{font-size:var(--fs-xs);line-height:1.5;color:var(--text-3);margin-top:2px}
.up-side-label{display:flex;align-items:center;gap:var(--sp-2);margin:var(--sp-5) 0 var(--sp-2);font-size:var(--fs-xs);font-weight:600;color:var(--text-3);letter-spacing:.02em}
.up-side-label svg{opacity:.85}

/* ── Cards: panels (containers keyed up_panel_*) ─────────────── */
[class*="st-key-up_panel_"]{position:relative;padding:var(--sp-5)!important;margin-bottom:var(--sp-4);border-radius:var(--r-lg);background:var(--panel-bg);border:1px solid var(--border-subtle);box-shadow:var(--glow),var(--shadow-1);backdrop-filter:blur(12px);transition:border-color var(--dur) var(--ease),box-shadow var(--dur) var(--ease)}
[class*="st-key-up_panel_"]:hover{border-color:var(--border);box-shadow:var(--glow),var(--shadow-2)}

/* ── KPI cards ───────────────────────────────────────────────── */
.up-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(var(--kpi-min,220px),1fr));gap:var(--sp-4);margin:var(--sp-2) 0 var(--sp-5)}
.up-kpi{position:relative;display:flex;flex-direction:column;gap:var(--sp-2);min-height:140px;padding:var(--sp-4);border-radius:var(--r-lg);background:var(--panel-bg);border:1px solid var(--border-subtle);box-shadow:var(--glow),var(--shadow-1);backdrop-filter:blur(12px);transition:transform var(--dur) var(--ease),border-color var(--dur) var(--ease),box-shadow var(--dur) var(--ease)}
.up-kpi:hover{transform:translateY(-2px);border-color:var(--border-strong);box-shadow:var(--glow),var(--shadow-2)}
.up-kpi-top{display:flex;align-items:center;justify-content:space-between;gap:var(--sp-2)}
.up-kpi-label{font-size:var(--fs-xs);font-weight:600;color:var(--text-2);line-height:1.4}
.up-kpi-icon{display:grid;place-items:center;width:28px;height:28px;flex:none;border-radius:var(--r-sm);background:var(--bg-2);border:1px solid var(--border-subtle);color:var(--text-2)}
.up-kpi--ok .up-kpi-icon{color:var(--success);background:var(--success-soft)}
.up-kpi--warn .up-kpi-icon{color:var(--warning);background:var(--warning-soft)}
.up-kpi--issue .up-kpi-icon{color:var(--danger);background:var(--danger-soft)}
.up-kpi--info .up-kpi-icon{color:var(--info);background:var(--info-soft)}
.up-kpi-value{font-family:var(--font-mono);font-variant-numeric:tabular-nums;font-size:var(--fs-xl);font-weight:600;line-height:1.15;letter-spacing:-.02em;color:var(--text-1);overflow-wrap:anywhere}
.up-kpi-unit{font-size:var(--fs-sm);font-weight:500;color:var(--text-3);margin-left:6px;letter-spacing:0}
.up-kpi-bottom{display:flex;align-items:flex-end;justify-content:space-between;gap:var(--sp-3);margin-top:auto}
.up-kpi-meta{display:flex;flex-direction:column;gap:6px;min-width:0}
.up-kpi-chips{display:flex;gap:6px;flex-wrap:wrap}
.up-kpi-foot{font-size:var(--fs-xs);line-height:1.45;color:var(--text-3)}
.up-kpi-spark{flex:none;width:96px;height:32px;color:var(--text-3)}
.up-delta{display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;font-size:var(--fs-xs);font-weight:600;line-height:20px;background:var(--bg-3);color:var(--text-2)}
.up-delta--ok{background:var(--success-soft);color:var(--success)}.up-delta--warn{background:var(--warning-soft);color:var(--warning)}
.up-delta--issue{background:var(--danger-soft);color:var(--danger)}.up-delta--info{background:var(--info-soft);color:var(--info)}

/* ── Badges ──────────────────────────────────────────────────── */
.up-badge{display:inline-flex;align-items:center;gap:6px;padding:2px 10px;border-radius:999px;border:1px solid transparent;font-size:var(--fs-xs);font-weight:600;line-height:20px;white-space:nowrap;background:var(--bg-3);color:var(--text-2)}
.up-badge i{width:6px;height:6px;border-radius:50%;background:currentColor;flex:none}
.up-badge--ok{color:var(--success);background:var(--success-soft);border-color:rgba(52,211,153,.28)}
.up-badge--warn{color:var(--warning);background:var(--warning-soft);border-color:rgba(251,191,36,.28)}
.up-badge--issue{color:var(--danger);background:var(--danger-soft);border-color:rgba(248,113,113,.3)}
.up-badge--info{color:var(--info);background:var(--info-soft);border-color:rgba(96,165,250,.28)}

/* ── Tables ──────────────────────────────────────────────────── */
.up-table-wrap{overflow:auto;max-height:var(--tbl-h,480px);border:1px solid var(--border-subtle);border-radius:var(--r-md);background:rgba(6,10,17,.4)}
.up-table{width:100%;border-collapse:separate;border-spacing:0;font-size:var(--fs-sm)}
.up-table th{position:sticky;top:0;z-index:1;padding:10px 14px;text-align:left;white-space:nowrap;font-size:var(--fs-xs);font-weight:600;color:var(--text-2);background:var(--bg-2);border-bottom:1px solid var(--border)}
.up-table td{padding:10px 14px;white-space:nowrap;color:var(--text-1);border-bottom:1px solid var(--border-subtle);transition:background var(--dur) var(--ease)}
.up-table tbody tr:nth-child(even) td{background:rgba(255,255,255,.018)}
.up-table tbody tr:hover td{background:rgba(255,255,255,.055)}
.up-table tbody tr:last-child td{border-bottom:0}
.up-table .num{text-align:right;font-family:var(--font-mono);font-size:13px;font-variant-numeric:tabular-nums}
.up-table .mono{font-family:var(--font-mono);font-size:13px;font-variant-numeric:tabular-nums;color:var(--text-2)}
.up-table .wrap{white-space:normal;min-width:260px;line-height:1.5;color:var(--text-2)}
[data-testid="stDataFrame"]{border:1px solid var(--border-subtle);border-radius:var(--r-md);overflow:hidden}

/* ── Banners, empty states, meta rows ────────────────────────── */
.up-banner{display:flex;gap:var(--sp-3);padding:var(--sp-3) var(--sp-4);margin:var(--sp-2) 0 var(--sp-4);border-radius:var(--r-md);border:1px solid var(--border);border-left-width:3px;background:var(--bg-2)}
.up-banner svg{flex:none;margin-top:2px}
.up-banner-title{font-size:var(--fs-sm);font-weight:700;color:var(--text-1);margin-bottom:2px}
.up-banner-body{font-size:var(--fs-sm);line-height:1.6;color:var(--text-2)}
.up-banner--info{border-left-color:var(--info);background:var(--info-soft)}.up-banner--info svg{color:var(--info)}
.up-banner--success{border-left-color:var(--success);background:var(--success-soft)}.up-banner--success svg{color:var(--success)}
.up-banner--warning{border-left-color:var(--warning);background:var(--warning-soft)}.up-banner--warning svg{color:var(--warning)}
.up-banner--danger{border-left-color:var(--danger);background:var(--danger-soft)}.up-banner--danger svg{color:var(--danger)}
.up-empty{display:flex;flex-direction:column;align-items:center;text-align:center;gap:var(--sp-2);padding:var(--sp-6) var(--sp-5);margin:var(--sp-4) 0;border:1px dashed var(--border-strong);border-radius:var(--r-lg);background:var(--panel-bg)}
.up-empty--compact{padding:var(--sp-5)}
.up-empty-icon{display:grid;place-items:center;width:52px;height:52px;border-radius:var(--r-lg);background:var(--bg-2);border:1px solid var(--border);color:var(--text-2);margin-bottom:var(--sp-2)}
.up-empty--issue .up-empty-icon{color:var(--danger);background:var(--danger-soft)}.up-empty--warn .up-empty-icon{color:var(--warning);background:var(--warning-soft)}
.up-empty-title{font-size:var(--fs-md);font-weight:700;color:var(--text-1)}
.up-empty-msg{max-width:60ch;font-size:var(--fs-sm);line-height:1.6;color:var(--text-2);overflow-wrap:anywhere}
.up-empty-hint{max-width:60ch;font-size:var(--fs-xs);line-height:1.6;color:var(--text-3)}
.up-meta{display:flex;flex-wrap:wrap;gap:var(--sp-3) var(--sp-5);margin-top:var(--sp-2)}
.up-meta div{display:flex;flex-direction:column;gap:2px}
.up-meta span{font-size:var(--fs-xs);color:var(--text-3)}
.up-meta b{font-family:var(--font-mono);font-size:var(--fs-sm);font-weight:500;color:var(--text-1)}
.up-datacard{padding:var(--sp-3);border-radius:var(--r-md);background:var(--bg-2);border:1px solid var(--border-subtle)}
.up-datacard-name{font-size:var(--fs-xs);color:var(--text-1);overflow-wrap:anywhere}
.up-datacard-meta{font-size:var(--fs-xs);color:var(--text-3);margin-top:2px}

/* ── Data-quality visuals ────────────────────────────────────── */
.up-check{display:grid;grid-template-columns:32px 1fr auto;align-items:center;gap:var(--sp-3);padding:var(--sp-3) 0;border-bottom:1px solid var(--border-subtle)}
.up-check:last-child{border-bottom:0}
.up-check-name{font-size:var(--fs-sm);font-weight:600;color:var(--text-1)}
.up-check-desc{font-size:var(--fs-xs);color:var(--text-3);line-height:1.5}
.up-check-side{display:flex;align-items:center;gap:var(--sp-3)}
.up-check-val{font-family:var(--font-mono);font-size:var(--fs-sm);color:var(--text-1);font-variant-numeric:tabular-nums}
.up-stack-title{font-size:var(--fs-sm);font-weight:600;color:var(--text-1);margin:var(--sp-3) 0 var(--sp-2)}
.up-stack{display:flex;gap:2px;height:10px;border-radius:999px;overflow:hidden;background:var(--bg-2)}
.up-stack span{display:block;min-width:3px}
.up-stack-legend{display:flex;flex-wrap:wrap;gap:var(--sp-1) var(--sp-4);margin-top:var(--sp-2);font-size:var(--fs-xs);color:var(--text-2)}
.up-stack-legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.up-stack-legend b{font-family:var(--font-mono);font-weight:500;color:var(--text-1);margin-left:4px}

/* ── Map legend (floats over the deck) ───────────────────────── */
[data-testid="stElementContainer"]:has(.up-legend),.element-container:has(.up-legend){position:absolute!important;left:calc(var(--sp-5) + var(--sp-3));bottom:calc(var(--sp-5) + var(--sp-3));width:auto!important;z-index:5}
.up-legend{min-width:230px;padding:var(--sp-3) var(--sp-4);border-radius:var(--r-md);background:rgba(8,13,21,.84);border:1px solid var(--border);box-shadow:var(--shadow-2);backdrop-filter:blur(10px)}
.up-legend-title{font-size:var(--fs-xs);font-weight:600;color:var(--text-1);margin-bottom:var(--sp-2)}
.up-legend-bar{display:flex;gap:2px;height:8px;border-radius:999px;overflow:hidden}
.up-legend-bar span{flex:1}
.up-legend-labels{display:flex;gap:2px;margin-top:6px;font-family:var(--font-mono);font-size:var(--fs-xs);color:var(--text-2)}
.up-legend-labels span{flex:1}
.up-legend-note{margin-top:var(--sp-2);font-size:var(--fs-xs);color:var(--text-3)}

/* ── Skeleton ────────────────────────────────────────────────── */
.up-skel{border-radius:var(--r-md);background:linear-gradient(90deg,var(--bg-2) 25%,var(--bg-3) 37%,var(--bg-2) 63%);background-size:400% 100%;animation:up-shimmer 1.4s ease infinite}
@keyframes up-shimmer{0%{background-position:100% 50%}100%{background-position:0 50%}}

/* ── Streamlit widgets ───────────────────────────────────────── */
[data-testid="stSidebar"]{background:rgba(8,13,21,.96);border-right:1px solid var(--border-subtle)}
[data-testid="stSidebar"] label p,[data-testid="stWidgetLabel"] p{color:var(--text-2)!important;font-size:var(--fs-xs)!important;font-weight:600!important}
[data-baseweb="select"]>div,[data-baseweb="input"],[data-baseweb="base-input"],[data-testid="stDateInput"] input{background:var(--bg-2)!important;border-color:var(--border)!important;border-radius:var(--r-sm)!important;color:var(--text-1)!important}
[data-baseweb="select"]>div:hover,[data-baseweb="input"]:hover{border-color:var(--border-strong)!important}
[data-testid="stMultiSelect"] [data-baseweb="select"]>div{max-height:132px;overflow-y:auto}
[data-baseweb="tag"]{background:var(--bg-3)!important;color:var(--text-1)!important;border-radius:6px!important}
[data-baseweb="popover"] [data-baseweb="menu"],[data-baseweb="popover"] ul{background:var(--bg-2)!important}
[data-testid="stFileUploaderDropzone"]{background:var(--bg-2);border:1px dashed var(--border-strong);border-radius:var(--r-md)}
.stButton button,.stDownloadButton button{min-height:40px;border-radius:var(--r-sm);border:1px solid var(--border);background:var(--bg-2);color:var(--text-1);font-weight:600;font-size:var(--fs-sm);box-shadow:var(--shadow-1);transition:transform var(--dur) var(--ease),border-color var(--dur) var(--ease),background var(--dur) var(--ease)}
.stButton button p,.stDownloadButton button p{color:inherit!important;font-size:var(--fs-sm)}
.stButton button:hover,.stDownloadButton button:hover{border-color:var(--accent-line);background:var(--bg-3);color:var(--text-1);transform:translateY(-1px)}
.stButton button[kind="primary"],.stButton button[data-testid="stBaseButton-primary"]{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.stButton button[kind="primary"]:hover,.stButton button[data-testid="stBaseButton-primary"]:hover{background:#4df5ff;color:var(--accent-ink)}
[data-testid="stSidebar"] .stButton button{width:100%}
[data-testid="stSlider"] [role="slider"]{background:var(--accent)!important;box-shadow:0 0 0 4px var(--accent-soft)}
[data-testid="stSpinner"]{width:fit-content;padding:var(--sp-3) var(--sp-4);margin:var(--sp-2) 0;border-radius:var(--r-md);border:1px solid var(--border);background:var(--bg-2);color:var(--text-2)}
[data-testid="stAlert"]{border-radius:var(--r-md);border:1px solid var(--border);background:var(--bg-2)}
#vg-tooltip-element{font-family:var(--font-ui)!important;background:rgba(18,26,39,.97)!important;color:var(--text-1)!important;border:1px solid var(--border)!important;border-radius:var(--r-sm)!important;box-shadow:var(--shadow-3)!important;padding:10px 12px!important}
#vg-tooltip-element td.key{color:var(--text-3)!important}#vg-tooltip-element td.value{color:var(--text-1)!important;font-family:var(--font-mono)}

[data-testid="stExpander"]{border:1px solid var(--border-subtle)!important;border-radius:var(--r-md)!important;background:var(--bg-2)}
[data-testid="stExpander"] summary p{color:var(--text-1)!important;font-weight:600}
/* Radios → segmented pills (main area) and nav items (sidebar) */
[data-testid="stRadio"] [role="radiogroup"]{gap:var(--sp-1)}
[data-testid="stRadio"] label{margin:0;padding:6px 14px;border-radius:var(--r-sm);border:1px solid var(--border-subtle);background:var(--bg-2);cursor:pointer;transition:background var(--dur) var(--ease),border-color var(--dur) var(--ease)}
[data-testid="stRadio"] label>div:first-child:not(:has([data-testid="stMarkdownContainer"])){display:none!important}
[data-testid="stRadio"] label p{color:var(--text-2)!important;font-size:var(--fs-sm)!important;font-weight:600!important}
[data-testid="stRadio"] label:hover{border-color:var(--border-strong)}
[data-testid="stRadio"] label:has(input:checked){background:var(--accent-soft);border-color:var(--accent-line)}
[data-testid="stRadio"] label:has(input:checked) p{color:var(--text-1)!important}
[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"]{flex-direction:column;gap:2px}
[data-testid="stSidebar"] [data-testid="stRadio"] label{position:relative;display:flex;align-items:center;gap:10px;width:100%;padding:9px 12px;border:0;background:transparent}
[data-testid="stSidebar"] [data-testid="stRadio"] label::before{content:"";width:16px;height:16px;flex:none;background:var(--text-3);-webkit-mask:var(--nav-icon) center/contain no-repeat;mask:var(--nav-icon) center/contain no-repeat;transition:background var(--dur) var(--ease)}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover{background:rgba(255,255,255,.05)}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked){background:var(--accent-soft)}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked)::before{background:var(--accent)}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked)::after{content:"";position:absolute;left:0;top:8px;bottom:8px;width:3px;border-radius:0 3px 3px 0;background:var(--accent)}
/*NAV*/

/* ── Responsive ──────────────────────────────────────────────── */
@media (max-width:900px){.block-container{padding:56px var(--sp-4) 48px}.up-chip{white-space:normal}[class*="st-key-up_panel_"]{padding:var(--sp-4)!important}}
@media (max-width:520px){.up-kpis{grid-template-columns:1fr}.up-kpi-value{font-size:var(--fs-lg)}.up-topbar{padding:var(--sp-3)}.up-legend{min-width:180px}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>"""

_uid = itertools.count()  # re-created on every Streamlit rerun, so ids/keys stay unique per run


def _icon_mask(name):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" '
        f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">{ICON_PATHS[name]}</svg>'
    )
    return f'url("data:image/svg+xml;utf8,{quote(svg)}")'


def inject_css():
    """Single entry point for all custom CSS (design tokens are generated from TOKENS)."""
    root = "".join(f"--{k}:{v};" for k, v in TOKENS.items())
    nav = "".join(
        f'[data-testid="stSidebar"] [data-testid="stRadio"] label:nth-of-type({i + 1}){{--nav-icon:{_icon_mask(n)}}}'
        for i, n in enumerate(NAV_ICONS)
    )
    st.markdown(_CSS.replace("/*TOKENS*/", root).replace("/*NAV*/", nav), unsafe_allow_html=True)


# ── Small HTML utilities ─────────────────────────────────────────────────────
def _flat(markup):
    """Collapse template whitespace: Markdown treats indented/blank lines inside HTML as code."""
    return "".join(line.strip() for line in str(markup).strip().splitlines())


def _md(markup):
    st.markdown(_flat(markup).replace("$", "&#36;"), unsafe_allow_html=True)


def icon(name, size=16):
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICON_PATHS[name]}</svg>'
    )


def _rgb_css(rgb):
    return f"rgb({rgb[0]},{rgb[1]},{rgb[2]})"


def scale_color(value, scale, alpha=220):
    """Return [r, g, b, a] for the highest scale step whose lower bound the value meets."""
    chosen = scale[0][2]
    for lower, _, rgb in scale:
        if value >= lower:
            chosen = rgb
    return [chosen[0], chosen[1], chosen[2], alpha]


_TONES = {"ok": "ok", "success": "ok", "warn": "warn", "warning": "warn", "issue": "issue", "danger": "issue", "info": "info", "neutral": "neutral"}


def badge(text, tone="neutral", dot=True):
    """Status pill. tone: ok | warn | issue | info | neutral."""
    return f'<span class="up-badge up-badge--{_TONES.get(tone, "neutral")}">{"<i></i>" if dot else ""}{esc(str(text))}</span>'


def section_header(title, description=None, icon_name=None):
    ico = f'<div class="up-section-icon">{icon(icon_name, 18)}</div>' if icon_name else ""
    desc = f'<div class="up-section-desc">{esc(description)}</div>' if description else ""
    _md(f'<div class="up-section">{ico}<div><div class="up-section-title" role="heading" aria-level="2">{esc(title)}</div>{desc}</div></div>')


@contextmanager
def panel(title=None, description=None, *, name=None, aside=None):
    """Glass card. Use as `with panel("Title", "Description"):` and place any Streamlit element inside."""
    key = f"up_panel_{name or next(_uid)}"
    try:
        box = st.container(key=key)
    except TypeError:  # Streamlit < 1.39 has no container keys: fall back to an unstyled container
        box = st.container()
    with box:
        if title:
            desc = f'<div class="up-panel-desc">{esc(description)}</div>' if description else ""
            _md(f'<div class="up-panel-head"><div><div class="up-panel-title">{esc(title)}</div>{desc}</div>{aside or ""}</div>')
        yield


def _split_unit(value):
    parts = value.rsplit(" ", 1)
    if len(parts) == 2 and parts[1].isalpha() and len(parts[1]) <= 4:
        return parts[0], parts[1]
    return value, ""


def sparkline(values, width=96, height=32):
    vals = [float(v) for v in list(values) if pd.notna(v)]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    step = (width - 6) / (len(vals) - 1)
    pts = [(3 + i * step, height - 4 - (v - lo) / span * (height - 8)) for i, v in enumerate(vals)]
    line = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{line} L{pts[-1][0]:.1f},{height} L{pts[0][0]:.1f},{height} Z"
    gid = f"upsg{next(_uid)}"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" aria-hidden="true">'
        f'<defs><linearGradient id="{gid}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".28"/>'
        f'<stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>'
        f'<path d="{area}" fill="url(#{gid})"/><path d="{line}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="2.5" fill="{T["accent"]}"/></svg>'
    )


def metric_card(label, value, foot="", *, icon_name="gauge", tone="default", delta=None, delta_tone="neutral", status=None, spark=None):
    """Returns KPI-card HTML. Render several together with kpi_grid([...]).
    status=(text, tone) shows a badge; delta is a small neutral/toned chip; spark is sparkline() output."""
    label = label.strip().capitalize() if label.strip().isupper() else label
    number, unit = _split_unit(str(value))
    unit_html = f'<span class="up-kpi-unit">{esc(unit)}</span>' if unit else ""
    chips = (badge(*status) if status else "") + (
        f'<span class="up-delta up-delta--{_TONES.get(delta_tone, "neutral")}">{esc(delta)}</span>' if delta else ""
    )
    chips_html = f'<div class="up-kpi-chips">{chips}</div>' if chips else ""
    foot_html = f'<div class="up-kpi-foot">{esc(foot)}</div>' if foot else ""
    spark_html = f'<div class="up-kpi-spark">{spark}</div>' if spark else ""
    return _flat(
        f'<div class="up-kpi up-kpi--{tone}"><div class="up-kpi-top"><span class="up-kpi-label">{esc(label)}</span>'
        f'<span class="up-kpi-icon">{icon(icon_name, 16)}</span></div>'
        f'<div class="up-kpi-value">{esc(number)}{unit_html}</div>'
        f'<div class="up-kpi-bottom"><div class="up-kpi-meta">{chips_html}{foot_html}</div>{spark_html}</div></div>'
    )


def kpi_grid(cards, min_width=185):
    """Equal-height, auto-wrapping KPI row."""
    _md(f'<div class="up-kpis" style="--kpi-min:{min_width}px">{"".join(cards)}</div>')


def banner(kind, body, title=None, icon_name=None):
    """Info banner. kind: info | success | warning | danger. `body` may contain trusted inline HTML."""
    default_icon = {"info": "info", "success": "check", "warning": "alert", "danger": "alert"}[kind]
    head = f'<div class="up-banner-title">{esc(title)}</div>' if title else ""
    _md(f'<div class="up-banner up-banner--{kind}" role="note">{icon(icon_name or default_icon, 18)}<div>{head}<div class="up-banner-body">{body}</div></div></div>')


def empty_state(title, message="", *, icon_name="inbox", tone="neutral", hint=None, compact=False):
    msg = f'<div class="up-empty-msg">{esc(message)}</div>' if message else ""
    hnt = f'<div class="up-empty-hint">{esc(hint)}</div>' if hint else ""
    cls = f"up-empty up-empty--{tone}" + (" up-empty--compact" if compact else "")
    _md(f'<div class="{cls}" role="status"><div class="up-empty-icon">{icon(icon_name, 24)}</div><div class="up-empty-title">{esc(title)}</div>{msg}{hnt}</div>')


def skeleton_html(cards=4):
    kpis = "".join('<div class="up-skel" style="height:140px"></div>' for _ in range(cards))
    return _flat(
        f'<div class="up-kpis">{kpis}</div><div class="up-skel" style="height:320px" role="status" aria-label="Loading"></div>'
    )


# ── Tables ───────────────────────────────────────────────────────────────────
def _fmt_cell(v, decimals):
    try:
        if pd.isna(v):
            return "—"
    except (TypeError, ValueError):
        pass
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, numbers.Integral):
        return f"{int(v):,}"
    if isinstance(v, numbers.Real):
        return f"{float(v):,.{decimals}f}"
    return str(v)


def _call_stretch(fn, *args, **kwargs):
    """Full-width rendering across Streamlit versions (width="stretch" → use_container_width fallback)."""
    try:
        return fn(*args, width="stretch", **kwargs)
    except Exception:
        return fn(*args, use_container_width=True, **kwargs)


def data_table(df, *, decimals=2, col_decimals=None, badges=None, wrap_cols=(), max_height=460, index=False):
    """Styled table: sticky header, zebra/hover rows, monospaced numerics, optional status badges per column.
    badges = {column: fn(value) -> (text, tone)}. Tables over HTML_TABLE_LIMIT rows use the native grid."""
    if df is None or len(df) == 0:
        empty_state("Nothing to show", "No rows match the current view.", compact=True)
        return
    if len(df) > HTML_TABLE_LIMIT:
        _call_stretch(st.dataframe, df, hide_index=not index)
        return
    col_decimals, badges = col_decimals or {}, badges or {}
    frame = df.reset_index() if index else df
    if index:
        frame.columns = [""] + [str(c) for c in frame.columns[1:]]
    cols = list(frame.columns)
    kinds = {}
    for c in cols:
        s = frame[c]
        kinds[c] = "num" if (pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)) else (
            "mono" if pd.api.types.is_datetime64_any_dtype(s) else ("wrap" if c in wrap_cols else "")
        )
    head = "".join(f'<th class="{"num" if kinds[c] == "num" else ""}">{esc(str(c))}</th>' for c in cols)
    body = []
    for row in frame.itertuples(index=False, name=None):
        cells = []
        for c, v in zip(cols, row):
            if c in badges:
                text, tone = badges[c](v)
                cells.append(f"<td>{badge(text, tone)}</td>")
            else:
                cells.append(f'<td class="{kinds[c]}">{esc(_fmt_cell(v, col_decimals.get(c, decimals)))}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    _md(f'<div class="up-table-wrap" style="--tbl-h:{max_height}px"><table class="up-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


# Status mappers for badge columns → (text, tone)
def signal_badge(v):
    s = str(v)
    tone = "issue" if s.startswith("Unusually high") else "warn" if s.startswith("Elevated") else "ok" if s.startswith("No percentile") else "neutral"
    return s, tone


def freshness_badge(v):
    s = str(v)
    tone = "ok" if s.startswith("Recent") else "warn" if s.startswith("Aging") else "issue"
    return s, tone


def confidence_badge(v):
    s = str(v)
    tone = "ok" if s.startswith("Higher") else "info" if s.startswith("Moderate") else "warn"
    return s, tone


def flag_badge(v):
    s = str(v)
    tone = "issue" if s.startswith("High") else "warn" if s.startswith("Elevated") else "ok" if s.startswith("No threshold") else "neutral"
    return s, tone


def coordinate_badge(v):
    return ("In range", "ok") if bool(v) else ("Check", "warn")


def status_badge(v):
    return str(v), {"OK": "ok", "Warning": "warn", "Issue": "issue"}.get(str(v), "neutral")


def dq_status(gaps, intervals):
    """Presentation heuristic for the Data Quality badges (tune DQ_ISSUE_SHARE to taste)."""
    if not gaps:
        return "OK"
    return "Issue" if intervals and gaps / intervals >= DQ_ISSUE_SHARE else "Warning"


def check_row(icon_name, name, description, status, value):
    text, tone = status
    return _flat(
        f'<div class="up-check"><div class="up-kpi-icon up-kpi--{tone}">{icon(icon_name, 16)}</div>'
        f'<div><div class="up-check-name">{esc(name)}</div><div class="up-check-desc">{esc(description)}</div></div>'
        f'<div class="up-check-side"><span class="up-check-val">{esc(value)}</span>{badge(text, tone)}</div></div>'
    )


def stacked_bar(title, parts):
    """parts = [(label, value, css_color)] → proportional bar with a legend."""
    total = sum(v for _, v, _ in parts) or 1
    segs = "".join(f'<span style="flex:{v / total:.6f};background:{c}"></span>' for _, v, c in parts if v > 0)
    legend = "".join(f'<span><i style="background:{c}"></i>{esc(label)}<b>{v:,}</b></span>' for label, v, c in parts)
    return _flat(f'<div class="up-stack-title">{esc(title)}</div><div class="up-stack" role="img" aria-label="{esc(title)}">{segs}</div><div class="up-stack-legend">{legend}</div>')


# ── Charts & maps ────────────────────────────────────────────────────────────
def station_color(title="Station"):
    return alt.Color(
        "station:N", title=title, scale=alt.Scale(range=PALETTE),
        legend=alt.Legend(orient="top", direction="horizontal", symbolLimit=8, symbolType="circle"),
    )


def style_chart(chart, height=330):
    """One place that themes every Altair chart: transparent, soft grid, mono tick labels, top legend."""
    return (
        chart.properties(height=height)
        .configure(background="transparent", font=UI_PLAIN)
        .configure_view(stroke=None)
        .configure_axis(
            domain=False, ticks=False, grid=True, gridColor="rgba(148,163,184,.14)", gridWidth=1,
            labelColor=T["text-3"], titleColor=T["text-2"], labelFont=MONO_PLAIN, labelFontSize=12,
            titleFont=UI_PLAIN, titleFontSize=12, titleFontWeight=500, labelPadding=8, titlePadding=12, labelOverlap="greedy",
        )
        .configure_axisX(grid=False)
        .configure_legend(
            labelColor=T["text-2"], titleColor=T["text-3"], labelFont=UI_PLAIN, titleFont=UI_PLAIN,
            labelFontSize=12, titleFontSize=12, symbolSize=80, padding=4, rowPadding=4, columnPadding=16,
        )
    )


def deck_tooltip(title_field, rows):
    """pydeck tooltip: rows = [(label, field)]. Fields are filled in by deck.gl from the layer data."""
    lines = "".join(
        f"<div style='display:flex;justify-content:space-between;gap:20px;font-size:12px;line-height:1.75;color:{T['text-2']}'>"
        f"<span>{label}</span><b style='font-family:{MONO_PLAIN};font-weight:600;color:{T['text-1']}'>{{{field}}}</b></div>"
        for label, field in rows
    )
    return {
        "html": f"<div style='min-width:210px'><div style='font-weight:700;font-size:14px;margin-bottom:6px;color:{T['text-1']}'>{{{title_field}}}</div>{lines}</div>",
        "style": {
            "backgroundColor": "rgba(14,21,33,.96)", "color": T["text-1"], "fontFamily": UI_PLAIN,
            "border": "1px solid rgba(148,163,184,.28)", "borderRadius": "12px", "padding": "12px 14px",
            "boxShadow": "0 18px 44px rgba(0,0,0,.5)",
        },
    }


def map_legend(title, scale, note):
    bar = "".join(f'<span style="background:{_rgb_css(rgb)}"></span>' for _, _, rgb in scale)
    labels = "".join(f"<span>{esc(label)}</span>" for _, label, _ in scale)
    return f'<div class="up-legend"><div class="up-legend-title">{esc(title)}</div><div class="up-legend-bar">{bar}</div><div class="up-legend-labels">{labels}</div><div class="up-legend-note">{esc(note)}</div></div>'


# ── Layout shells ────────────────────────────────────────────────────────────
LOGO = (
    '<svg width="32" height="32" viewBox="0 0 32 32" aria-hidden="true"><rect x=".5" y=".5" width="31" height="31" rx="9" fill="#0f1b2a" stroke="rgba(0,240,255,.4)"/>'
    '<path d="M7 11c3-3 6 3 9 0s6 3 9 0M7 17c3-3 6 3 9 0s6 3 9 0M7 23c3-3 6 3 9 0s6 3 9 0" fill="none" stroke="#00f0ff" stroke-width="1.8" stroke-linecap="round"/></svg>'
)


def sidebar_label(text, icon_name):
    _md(f'<div class="up-side-label">{icon(icon_name, 14)}<span>{esc(text)}</span></div>')


def render_topbar(slot, *, source_label=None, latest=None, start=None, end=None, state="ready"):
    tone, text = {
        "ready": ("ok", "Historical data"), "error": ("issue", "Data unavailable"),
        "empty": ("warn", "Nothing in view"), "loading": ("info", "Loading data"),
    }[state]
    sep = '<span class="up-chip-sep"></span>'
    status = f'<span class="up-dot up-dot--{tone}"></span><span>{text}</span>'
    if source_label:
        status += f'{sep}<span class="up-mono">{esc(source_label)}</span>'
    if latest is not None and pd.notna(latest):
        status += f"{sep}<span>Latest record {latest:%d %b %Y, %H:%M}</span>"
    dates = ""
    if start is not None and end is not None:
        dates = f'<div class="up-chip">{icon("calendar", 14)}<span class="up-mono">{start:%d %b %Y} – {end:%d %b %Y}</span></div>'
    with slot:
        _md(
            f'<div class="up-topbar"><div class="up-brand">{LOGO}<div><div class="up-brand-name">UrbanPulse</div>'
            f'<div class="up-brand-sub">Rainfall Intelligence · Bengaluru</div></div></div>'
            f'<div class="up-topbar-meta"><div class="up-chip" role="status">{status}</div>{dates}</div></div>'
        )


def find_default_csv():
    for path in CANDIDATE_PATHS:
        if path.exists():
            return path
    return None


def _pick_column(columns, exact, keywords=(), exclude=()):
    """Find a column by exact (case-insensitive) name first, then by keyword in the header."""
    lowered = {str(c).strip().lower(): c for c in columns}
    for name in exact:
        if name.lower() in lowered:
            return lowered[name.lower()]
    for key in keywords:
        for low, original in lowered.items():
            if key in low and not any(bad in low for bad in exclude):
                return original
    return None


def _read_csv_flexible(source):
    """Read a CSV with the common separators/encodings (comma, semicolon, tab, pipe; UTF-8 or Latin-1)."""
    last_error = None
    for kwargs in (
        {},
        {"encoding": "latin-1"},
        {"sep": None, "engine": "python"},
        {"sep": None, "engine": "python", "encoding": "latin-1"},
    ):
        try:
            if hasattr(source, "seek"):
                source.seek(0)
            frame = pd.read_csv(source, skip_blank_lines=True, **kwargs)
        except (UnicodeDecodeError, ValueError) as exc:
            last_error = exc
            continue
        if frame.shape[1] > 1:
            return frame
        last_error = ValueError("The file has only one column, so it does not look like a table.")
    raise ValueError(f"Could not read this file as a CSV table ({last_error}).")


def _parse_timestamps(series):
    """Parse dates without guessing blindly: try day-first and month-first, keep whichever reads more rows."""
    import warnings

    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    text = series.astype("string").str.strip()
    best = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        is_iso = text.str.match(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}").fillna(False).mean() > 0.9
        for dayfirst in ((False, True) if is_iso else (True, False)):  # year-first dates are never day-first
            parsed = pd.to_datetime(text, errors="coerce", dayfirst=dayfirst)
            bad = int(parsed.isna().sum())
            if best is None or bad < best[0]:
                best = (bad, parsed)
        if best[0] > 0:  # mixed formats inside one column
            try:
                mixed = pd.to_datetime(text, errors="coerce", dayfirst=True, format="mixed")
                if int(mixed.isna().sum()) < best[0]:
                    best = (int(mixed.isna().sum()), mixed)
            except (ValueError, TypeError):
                pass
    parsed = best[1]
    try:
        if getattr(parsed.dt, "tz", None) is not None:
            parsed = parsed.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    except (AttributeError, TypeError):
        pass
    return parsed


def load_rainfall(uploaded_file=None):
    """Load and normalize a rainfall CSV. Column names, separators and date formats are detected, not assumed."""
    source_label = "Uploaded CSV"
    if uploaded_file is not None:
        raw = _read_csv_flexible(uploaded_file)
    else:
        path = find_default_csv()
        if path is None:
            raise FileNotFoundError(
                "No default rainfall CSV was found. Expected one of: "
                + ", ".join(str(p.relative_to(BASE)) for p in CANDIDATE_PATHS)
            )
        raw = _read_csv_flexible(path)
        source_label = str(path.relative_to(BASE))

    raw.columns = [str(c).strip() for c in raw.columns]
    cols = list(raw.columns)

    time_col = _pick_column(
        cols, [TIME_COL, "timestamp", "datetime", "date time", "date", "time"],
        ("timestamp", "datetime", "acquisition", "observ", "time", "date"), exclude=("lgd", "code", "station", "state"),
    )
    station_col = _pick_column(
        cols, [STATION_COL, "station_name", "station name", "sensor_id", "station id", "site", "location"],
        ("station", "site", "gauge", "gage", "sensor", "location"), exclude=("lgd", "code", "state"),
    )
    rain_col = _pick_column(
        cols, [RAIN_COL, "rainfall_mm", "rainfall (mm)", "rainfall", "hourly rainfall (mm)", "precipitation", "precip"],
        ("rain", "precip"), exclude=("station", "state", "time", "date", "lgd"),
    )
    lat_col = _pick_column(cols, [LAT_COL, "latitude", "lat", "lat_dd"], ("latitude",))
    lon_col = _pick_column(cols, [LON_COL, "longitude", "lon", "lng", "long", "lon_dd"], ("longitude",))

    missing = []
    if time_col is None:
        missing.append("a date/time column")
    if station_col is None:
        missing.append("a station name column")
    if rain_col is None:
        missing.append("a rainfall column")
    if missing:
        raise ValueError(
            "Could not find " + ", ".join(missing) + ". Columns in your file: "
            + ", ".join(cols[:25]) + (" …" if len(cols) > 25 else "")
            + ". Rename the matching columns to something like Station, Timestamp and Rainfall (mm), or tell the developer which columns to use."
        )

    rename = {time_col: "timestamp", station_col: "station", rain_col: "rainfall_mm"}
    if lat_col:
        rename[lat_col] = "latitude"
    if lon_col:
        rename[lon_col] = "longitude"
    df = raw.rename(columns=rename).copy()

    keep = ["timestamp", "station", "rainfall_mm"]
    if "latitude" in df.columns:
        keep.append("latitude")
    if "longitude" in df.columns:
        keep.append("longitude")
    df = df[keep].copy()
    rows_read = len(df)

    df["timestamp"] = _parse_timestamps(df["timestamp"])
    df["station"] = df["station"].astype("string").str.strip()
    df["rainfall_mm"] = pd.to_numeric(df["rainfall_mm"], errors="coerce")
    if "latitude" in df.columns:
        df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    if "longitude" in df.columns:
        df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")

    df = df.dropna(subset=["timestamp", "station", "rainfall_mm"])
    df = df[(df["station"] != "") & (df["rainfall_mm"] >= 0)].copy()
    df = df.sort_values(["station", "timestamp"]).reset_index(drop=True)
    if df.empty:
        raise ValueError("The CSV was loaded, but no valid rainfall records remain.")
    df["gap_hours"] = (
        df.groupby("station")["timestamp"].diff().dt.total_seconds() / 3600
    )
    df.attrs["rows_read"] = rows_read
    df.attrs["columns"] = {"Date/time": time_col, "Station": station_col, "Rainfall": rain_col, **({"Latitude": lat_col} if lat_col else {}), **({"Longitude": lon_col} if lon_col else {})}
    return df, source_label


OPEN_METEO_API = "https://api.open-meteo.com/v1/forecast"


@st.cache_data(ttl=300, show_spinner=False)
def fetch_open_meteo(locations):
    """Fetch Open-Meteo estimates in small coordinate batches.

    Each returned row represents one station and includes its hourly forecast
    in the ``hourly_forecast`` field, matching the dashboard's expected format.
    These are model estimates near station coordinates, not gauge observations.
    """
    import json
    import time
    import urllib.error
    import urllib.parse
    import urllib.request

    fetched_at = pd.Timestamp.now(tz="UTC").isoformat()
    if not locations:
        return [], "No station coordinates are available in the historical dataset.", fetched_at

    rows = []
    errors = []
    batch_size = 5

    for start in range(0, len(locations), batch_size):
        batch = locations[start:start + batch_size]
        params = {
            "latitude": ",".join(f"{float(item[1]):.5f}" for item in batch),
            "longitude": ",".join(f"{float(item[2]):.5f}" for item in batch),
            "current": "temperature_2m,relative_humidity_2m,precipitation,rain,wind_speed_10m,weather_code",
            "hourly": "precipitation,rain,precipitation_probability,temperature_2m",
            "forecast_days": 2,
            "timezone": "Asia/Kolkata",
        }
        url = OPEN_METEO_API + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "UrbanPulse/1.0 (student rainfall monitoring prototype)",
            },
            method="GET",
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))

            if isinstance(payload, dict) and payload.get("error"):
                reason = str(payload.get("reason", "Open-Meteo reported an API error."))
                errors.append(f"Batch {start // batch_size + 1}: {reason}")
                continue

            payloads = payload if isinstance(payload, list) else [payload]
            for idx, location in enumerate(batch):
                if idx >= len(payloads) or not isinstance(payloads[idx], dict):
                    errors.append(f"No response for station {location[0]}")
                    continue

                item = payloads[idx]
                current = item.get("current") or {}
                hourly = item.get("hourly") or {}
                times = hourly.get("time") or []
                precip = hourly.get("precipitation") or []
                rain = hourly.get("rain") or []
                probability = hourly.get("precipitation_probability") or []
                temps = hourly.get("temperature_2m") or []
                current_time = current.get("time")

                forecast_times = pd.to_datetime(pd.Series(times), errors="coerce")
                if current_time and len(forecast_times):
                    current_timestamp = pd.to_datetime(current_time, errors="coerce")
                    future_mask = forecast_times >= current_timestamp
                else:
                    future_mask = pd.Series([True] * len(times))

                forecast_values = pd.to_numeric(pd.Series(precip), errors="coerce")
                if len(forecast_values) == len(future_mask):
                    future_values = forecast_values[future_mask.reset_index(drop=True)]
                else:
                    future_values = forecast_values

                first_6h = future_values.head(6).dropna()
                first_24h = future_values.head(24).dropna()
                next_6h = float(first_6h.sum()) if len(first_6h) else float("nan")
                next_24h = float(first_24h.sum()) if len(first_24h) else float("nan")

                hourly_rows = []
                for j, timestamp in enumerate(times):
                    hourly_rows.append({
                        "station": location[0],
                        "latitude": location[1],
                        "longitude": location[2],
                        "forecast_time": timestamp,
                        "forecast_precipitation_mm": precip[j] if j < len(precip) else None,
                        "forecast_rain_mm": rain[j] if j < len(rain) else None,
                        "precipitation_probability_percent": probability[j] if j < len(probability) else None,
                        "forecast_temperature_c": temps[j] if j < len(temps) else None,
                    })

                rows.append({
                    "station": location[0],
                    "latitude": location[1],
                    "longitude": location[2],
                    "timezone": item.get("timezone", "Asia/Kolkata"),
                    "current_time": current_time,
                    "temperature_c": current.get("temperature_2m"),
                    "relative_humidity_percent": current.get("relative_humidity_2m"),
                    "current_precipitation_mm": current.get("precipitation"),
                    "current_rain_mm": current.get("rain"),
                    "wind_speed_kmh": current.get("wind_speed_10m"),
                    "weather_code": current.get("weather_code"),
                    "next_6h_precipitation_mm": next_6h,
                    "next_24h_precipitation_mm": next_24h,
                    "hourly_forecast": hourly_rows,
                    "model_elevation_m": item.get("elevation"),
                    "error": "",
                })

        except urllib.error.HTTPError as exc:
            errors.append(f"Open-Meteo returned HTTP {exc.code} for batch {start // batch_size + 1}.")
        except urllib.error.URLError as exc:
            errors.append(f"Could not connect to Open-Meteo for batch {start // batch_size + 1}: {exc.reason}")
        except TimeoutError:
            errors.append(f"Open-Meteo request timed out for batch {start // batch_size + 1}.")
        except json.JSONDecodeError:
            errors.append(f"Open-Meteo returned invalid JSON for batch {start // batch_size + 1}.")
        except Exception as exc:
            errors.append(f"Batch {start // batch_size + 1} failed: {type(exc).__name__}: {exc}")

        if start + batch_size < len(locations):
            time.sleep(0.2)

    fetched_at = pd.Timestamp.now(tz="UTC").isoformat()
    return rows, "; ".join(errors) if errors else "", fetched_at


def weather_screening_flag(next_6h, next_24h):
    """Explainable prototype review thresholds; not official alerts or flood prediction."""
    if pd.isna(next_6h) or pd.isna(next_24h):
        return "Insufficient forecast data"
    if next_6h >= 30 or next_24h >= 75:
        return "High forecast rainfall — verify local conditions"
    if next_6h >= 15 or next_24h >= 35:
        return "Elevated forecast rainfall — review"
    return "No threshold flag from this simple screen"


def records_frame(records):
    """Convert source records to a display frame without renaming away original fields."""
    return pd.DataFrame(records) if records else pd.DataFrame()


def find_column(frame, candidates):
    by_lower = {str(c).strip().lower(): c for c in frame.columns}
    for candidate in candidates:
        if candidate.lower() in by_lower:
            return by_lower[candidate.lower()]
    return None


# ═════════════════════════════════════════════════════════════════════════════
# APP SHELL — sidebar, data load, filters, header
# ═════════════════════════════════════════════════════════════════════════════
inject_css()
header_slot = st.container()

NAV_LABELS = {
    "Mission Control": "Overview",
    "Decision Engine": "Station Screening",
    "Live Open-Meteo & Alerts": "Live Forecast",
    "Spatial Matrix": "Station Map",
    "Telemetry Trends": "Rainfall Trends",
    "Sensor Log Matrix": "Raw Records",
    "Data Quality": "Data Health",
}

with st.sidebar:
    _md(f'<div class="up-brand">{LOGO}<div><div class="up-brand-name">UrbanPulse</div><div class="up-brand-sub">Resilient city AI</div></div></div>')
    sidebar_label("Workspace", "layout")
    page = st.radio(
        "Navigation",
        ["Mission Control", "Decision Engine", "Live Open-Meteo & Alerts", "Spatial Matrix", "Telemetry Trends", "Sensor Log Matrix", "Data Quality"],
        format_func=NAV_LABELS.get,
        label_visibility="collapsed",
    )
    sidebar_label("Data", "database")
    uploaded = st.file_uploader(
        "Import rainfall CSV", type=["csv"], label_visibility="collapsed", key="rainfall_upload"
    )

loading = st.empty()
loading.markdown(skeleton_html(), unsafe_allow_html=True)
try:
    df, source_label = load_rainfall(uploaded)
except Exception as exc:
    loading.empty()
    render_topbar(header_slot, state="error")
    empty_state(
        "Could not load rainfall data", str(exc), icon_name="database", tone="issue",
        hint="Place bengaluru_geo_filtered.csv in data/processed/ beside the UrbanPulse project folder, or upload it in the sidebar.",
    )
    st.stop()
loading.empty()

stations = sorted(df["station"].dropna().unique().tolist())
min_date = df["timestamp"].min().date()
max_date = df["timestamp"].max().date()
latest_record = df["timestamp"].max()


def show_topbar(state="ready", start=None, end=None):
    render_topbar(header_slot, source_label=source_label, latest=latest_record, start=start, end=end, state=state)


# Reset works by bumping a nonce that is part of the filter widget keys (widgets re-initialise to defaults).
if "filter_nonce" not in st.session_state:
    st.session_state["filter_nonce"] = 0


def _reset_filters():
    st.session_state["filter_nonce"] += 1


_sig = hashlib.md5("|".join(stations).encode("utf-8")).hexdigest()[:8]
_fk = f"{_sig}_{min_date}_{max_date}_{st.session_state['filter_nonce']}"

with st.sidebar:
    _md(
        f'<div class="up-datacard"><div class="up-datacard-name up-mono">{esc(source_label)}</div>'
        f'<div class="up-datacard-meta">{len(df):,} valid records · {len(stations):,} stations</div></div>'
    )
    if df.attrs.get("columns"):
        with st.expander("How your file was read"):
            st.markdown("\n".join(f"- **{k}** ← `{v}`" for k, v in df.attrs["columns"].items()))
            st.caption(f"{df.attrs.get('rows_read', len(df)):,} rows read · {len(df):,} used. Rows with an unreadable date, station or rainfall value are skipped.")
    sidebar_label("Filters", "filter")
    selected_stations = st.multiselect(
        "Stations",
        stations,
        default=stations,
        help="Select one or more stations to display.",
        key=f"flt_stations_{_fk}",
    )
    date_range = st.date_input(
        "Observation date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
        key=f"flt_dates_{_fk}",
    )
    st.button("Reset filters", key="reset_filters", on_click=_reset_filters)
    sidebar_label("Settings", "sliders")
    gap_threshold = st.slider(
        "Flag reporting gaps longer than (hours)", min_value=6, max_value=168, value=24, step=6
    )
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    with st.expander("New here? Quick guide"):
        st.markdown(
            "**1. Pick your data:** use the built-in file or upload your own CSV.\n\n"
            "**2. Narrow it down:** choose stations and dates under *Filters*. *Reset filters* undoes this.\n\n"
            "**3. Explore:** *Overview* gives the big picture, *Station Map* shows where, *Rainfall Trends* shows when, "
            "*Data Health* shows what is missing, and *Live Forecast* shows model estimates for the next hours."
        )
    banner(
        "warning",
        "Historical CSV analysis is preserved. The Live Open-Meteo page shows weather-model estimates separately from historical gauge observations. UrbanPulse is not an official flood warning service.",
        title="Dual data mode",
    )

if not selected_stations:
    show_topbar("empty")
    empty_state("No stations selected", "Choose at least one station in the sidebar to see rainfall data.", icon_name="filter", tone="warn")
    st.stop()

if isinstance(date_range, (tuple, list)) and len(date_range) < 2:
    show_topbar("empty")
    empty_state("Select an end date", "Pick the last day of your range in the sidebar to continue.", icon_name="calendar", tone="warn")
    st.stop()

if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date = end_date = date_range

start_ts = pd.Timestamp(start_date)
end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
filtered = df[
    df["station"].isin(selected_stations)
    & df["timestamp"].between(start_ts, end_ts)
].copy()

if filtered.empty:
    show_topbar("empty", start_date, end_date)
    empty_state(
        "No records match these filters", "There are no observations for this station and date combination.",
        icon_name="inbox", tone="warn", hint="Widen the date range, add stations, or use Reset filters in the sidebar.",
    )
    st.stop()

# Recalculate intervals after filtering only for records visible in the selected date range.
filtered = filtered.sort_values(["station", "timestamp"])
filtered["gap_hours"] = (
    filtered.groupby("station")["timestamp"].diff().dt.total_seconds() / 3600
)

latest_timestamp = filtered["timestamp"].max()
median_gap = filtered["gap_hours"].median()
gaps_over_threshold = int((filtered["gap_hours"] > gap_threshold).sum())
max_rain = filtered["rainfall_mm"].max()
mean_rain = filtered["rainfall_mm"].mean()

show_topbar("ready", start_date, end_date)

if page == "Mission Control":
    section_header("Overview", "The big picture for the stations and dates you selected. Change them in the sidebar.", "layout")
    peak = filtered.loc[filtered["rainfall_mm"].idxmax()]
    banner(
        "info",
        f"Showing <b>{len(filtered):,}</b> readings from <b>{filtered['station'].nunique():,}</b> stations. "
        f"The heaviest single reading was <b>{max_rain:.2f} mm</b> at <b>{esc(str(peak['station']))}</b> on {peak['timestamp']:%d %b %Y}. "
        f"{'There were <b>' + format(gaps_over_threshold, ',') + '</b> stretches where a station went quiet for more than ' + str(gap_threshold) + ' hours.' if gaps_over_threshold else 'No station went quiet for longer than ' + str(gap_threshold) + ' hours.'}",
        title="At a glance",
    )
    daily = filtered.groupby(filtered["timestamp"].dt.floor("D"))["rainfall_mm"]
    gap_intervals = int(filtered["gap_hours"].notna().sum())
    gap_pct = (gaps_over_threshold / gap_intervals * 100) if gap_intervals else 0.0
    kpi_grid([
        metric_card("Valid observations", f"{len(filtered):,}", "Records after current filters", icon_name="database", spark=sparkline(daily.size().tail(30).tolist())),
        metric_card("Stations selected", f"{filtered['station'].nunique():,}", "Stations represented in view", icon_name="pin", delta=f"of {len(stations):,} in dataset"),
        metric_card("Max recorded rainfall", f"{max_rain:.2f} mm", "Highest source-record value in view", icon_name="rain", spark=sparkline(daily.max().tail(30).tolist())),
        metric_card("Mean rainfall", f"{mean_rain:.2f} mm", "Average per source record", icon_name="gauge", spark=sparkline(daily.mean().tail(30).tolist())),
        metric_card(
            "Gaps above threshold", f"{gaps_over_threshold:,}", f"Intervals longer than {gap_threshold} hours",
            icon_name="alert", tone="warn" if gaps_over_threshold else "ok",
            delta=f"{gap_pct:.1f}% of intervals", delta_tone="warn" if gaps_over_threshold else "ok",
        ),
    ])

    left, right = st.columns([1.5, 1], gap="large")
    with left:
        with panel("Recorded rainfall over time", "Points show actual source records; missing intervals are not filled with zero."):
            chart = style_chart(
                alt.Chart(filtered)
                .mark_circle(size=48, opacity=0.72)
                .encode(
                    x=alt.X("timestamp:T", title="Observation time"),
                    y=alt.Y("rainfall_mm:Q", title="Rainfall per source record (mm)"),
                    color=station_color(),
                    tooltip=[
                        alt.Tooltip("station:N", title="Station"),
                        alt.Tooltip("timestamp:T", title="Timestamp"),
                        alt.Tooltip("rainfall_mm:Q", title="Rainfall (mm)", format=".2f"),
                    ],
                ),
                330,
            )
            _call_stretch(st.altair_chart, chart, theme=None)
    with right:
        with panel("Rainfall snapshot", "Summary of the selected observations"):
            summary = filtered["rainfall_mm"].describe().rename("rainfall_mm").to_frame()
            summary.index = ["Count", "Mean", "Std. deviation", "Minimum", "25th percentile", "Median", "75th percentile", "Maximum"]
            summary["rainfall_mm"] = summary["rainfall_mm"].round(2)
            data_table(summary, index=True, max_height=330)
            median_txt = f"{median_gap:.2f} hours" if pd.notna(median_gap) else "n/a"
            _md(
                f'<div class="up-meta"><div><span>Latest observation</span><b>{latest_timestamp:%Y-%m-%d %H:%M}</b></div>'
                f'<div><span>Median interval between readings</span><b>{median_txt}</b></div></div>'
            )

    with panel("Station summary", "Readings and reporting-gap indicators for the current filters"):
        station_summary = filtered.groupby("station").agg(
            readings=("rainfall_mm", "size"),
            mean_rainfall_mm=("rainfall_mm", "mean"),
            max_rainfall_mm=("rainfall_mm", "max"),
            median_gap_hours=("gap_hours", "median"),
            gaps_over_threshold=("gap_hours", lambda x: int((x > gap_threshold).sum())),
            first_observation=("timestamp", "min"),
            last_observation=("timestamp", "max"),
        ).reset_index()
        station_summary[["mean_rainfall_mm", "max_rainfall_mm", "median_gap_hours"]] = station_summary[
            ["mean_rainfall_mm", "max_rainfall_mm", "median_gap_hours"]
        ].round(2)
        data_table(station_summary)

elif page == "Decision Engine":
    section_header("Station screening", "Which stations had an unusually heavy latest reading, and can you trust it? This is a screening aid, not a flood forecast.", "target")
    banner(
        "info",
        "UrbanPulse compares each station's latest observation on or before the selected assessment date with that station's own historical rainfall distribution. It also checks how old the observation is. Results are screening signals only; they do not prove flooding or sensor failure.<br><b>Plain English:</b> “P95” means the latest reading is higher than 95% of that station's past readings. “Stale” means the station hasn't reported recently. “Source record” means one row in your CSV.",
        title="How to read this page",
    )

    with panel("Assessment settings", "Choose how each station's latest reading is compared with its own history."):
        control_a, control_b, control_c = st.columns(3)
        with control_a:
            baseline_days = st.selectbox("Historical baseline window", [30, 60, 90, 180, 365], index=2, help="Number of days before the assessment date used to estimate station-specific rainfall percentiles.")
        with control_b:
            high_percentile = st.selectbox("Unusual rainfall threshold", [90, 95, 97.5, 99], index=1, help="Latest reading at or above this station-specific percentile is flagged as unusually high.")
        with control_c:
            freshness_hours = st.selectbox("Stale observation after", [6, 12, 24, 48, 72], index=2, help="A reporting-freshness threshold for this historical replay, not an official service-level target.")

    assessment_time = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    history = df[(df["station"].isin(selected_stations)) & (df["timestamp"] <= assessment_time)].copy()
    if history.empty:
        empty_state("No observations available", "No observations exist on or before the selected assessment date.", icon_name="inbox", tone="warn")
    else:
        baseline_start = assessment_time - pd.Timedelta(days=int(baseline_days))
        rows = []
        for station_name in selected_stations:
            station_all = history[history["station"] == station_name].sort_values("timestamp")
            if station_all.empty:
                rows.append({
                    "Station": station_name, "Latest observation": pd.NaT,
                    "Latest rainfall (mm per source record)": float("nan"),
                    "Historical baseline readings": 0, "P90 threshold (mm)": float("nan"),
                    f"P{high_percentile:g} threshold (mm)": float("nan"),
                    "Rainfall signal": "Insufficient evidence", "Observation age (hours)": float("nan"),
                    "Data freshness": "No observation by assessment date", "Confidence": "Low",
                    "Recommended next check": "Check station data availability and telemetry history",
                })
                continue
            latest = station_all.iloc[-1]
            prior_records = station_all[station_all["timestamp"] < latest["timestamp"]]
            baseline = prior_records[prior_records["timestamp"] >= baseline_start]["rainfall_mm"]
            # Exclude the latest observation from its own baseline to avoid self-influencing the threshold.
            if len(baseline) < 10:
                baseline = prior_records["rainfall_mm"]
            q90 = float(baseline.quantile(0.90)) if len(baseline) else float("nan")
            qhigh = float(baseline.quantile(float(high_percentile) / 100.0)) if len(baseline) else float("nan")
            latest_rain = float(latest["rainfall_mm"])
            age_hours = max(0.0, (assessment_time - latest["timestamp"]).total_seconds() / 3600.0)
            if len(baseline) < 10 or pd.isna(qhigh):
                signal = "Insufficient baseline"
            elif latest_rain >= qhigh:
                signal = f"Unusually high (≥P{high_percentile:g})"
            elif latest_rain >= q90:
                signal = "Elevated (≥P90)"
            else:
                signal = "No percentile anomaly"

            if age_hours <= 6:
                freshness = "Recent (≤6h)"
            elif age_hours <= freshness_hours:
                freshness = "Aging"
            else:
                freshness = "Stale for selected threshold"

            if len(baseline) >= 30 and age_hours <= freshness_hours:
                confidence = "Higher data support"
            elif len(baseline) >= 10:
                confidence = "Moderate data support" if age_hours <= freshness_hours else "Reduced — stale data"
            else:
                confidence = "Low — limited baseline"

            if age_hours > freshness_hours:
                action = "Verify reporting continuity before interpreting conditions"
            elif signal.startswith("Unusually high"):
                action = "Verify the reading and check local rainfall / drainage conditions"
            elif signal == "Elevated (≥P90)":
                action = "Review nearby stations and continue observation"
            elif signal == "Insufficient baseline":
                action = "Collect more valid observations before classifying this station"
            else:
                action = "Continue routine monitoring; no station-specific anomaly detected"

            rows.append({
                "Station": station_name,
                "Latest observation": latest["timestamp"],
                "Latest rainfall (mm per source record)": latest_rain,
                "Historical baseline readings": int(len(baseline)),
                "P90 threshold (mm)": q90,
                f"P{high_percentile:g} threshold (mm)": qhigh,
                "Rainfall signal": signal,
                "Observation age (hours)": age_hours,
                "Data freshness": freshness,
                "Confidence": confidence,
                "Recommended next check": action,
            })

        decision_df = pd.DataFrame(rows)
        # Sort by high rainfall signal first, then stale-data concerns, then observation magnitude.
        decision_df["_priority"] = decision_df["Rainfall signal"].map({
            f"Unusually high (≥P{high_percentile:g})": 0,
            "Elevated (≥P90)": 1,
            "Insufficient baseline": 2,
            "No percentile anomaly": 3,
            "Insufficient evidence": 4,
        }).fillna(5)
        decision_df = decision_df.sort_values(["_priority", "Observation age (hours)"], ascending=[True, False], na_position="last")

        unusual_count = int(decision_df["Rainfall signal"].astype(str).str.startswith("Unusually high").sum())
        stale_count = int(decision_df["Data freshness"].astype(str).str.startswith("Stale").sum())
        insufficient_count = int(decision_df["Rainfall signal"].astype(str).str.contains("Insufficient").sum())
        kpi_grid([
            metric_card("Stations assessed", f"{len(decision_df):,}", "Selected stations with a result row", icon_name="pin"),
            metric_card(
                "Unusual latest readings", f"{unusual_count:,}", f"At or above station P{high_percentile:g}", icon_name="alert",
                tone="issue" if unusual_count else "ok", status=("Issue", "issue") if unusual_count else ("OK", "ok"),
            ),
            metric_card(
                "Stale observations", f"{stale_count:,}", f"Older than {freshness_hours} hours at assessment time", icon_name="clock",
                tone="warn" if stale_count else "ok", status=("Warning", "warn") if stale_count else ("OK", "ok"),
            ),
            metric_card(
                "Limited evidence", f"{insufficient_count:,}", "Stations needing more data or baseline", icon_name="info",
                tone="info", status=("Info", "info") if insufficient_count else ("OK", "ok"),
            ),
        ])

        _md(
            f'<div class="up-meta" style="margin:0 0 16px"><div><span>Assessment as of</span><b>{assessment_time:%Y-%m-%d %H:%M}</b></div>'
            f'<div><span>Baseline</span><b>{baseline_days} days before assessment where available</b></div></div>'
        )
        display_cols = [
            "Station", "Latest observation", "Latest rainfall (mm per source record)",
            "Historical baseline readings", "P90 threshold (mm)", f"P{high_percentile:g} threshold (mm)",
            "Rainfall signal", "Observation age (hours)", "Data freshness", "Confidence", "Recommended next check",
        ]
        display_df = decision_df[display_cols].copy()
        for col in ["Latest rainfall (mm per source record)", "P90 threshold (mm)", f"P{high_percentile:g} threshold (mm)", "Observation age (hours)"]:
            display_df[col] = pd.to_numeric(display_df[col], errors="coerce").round(2)
        with panel("Station screening results", "Strongest rainfall signals first, then the oldest observations."):
            data_table(
                display_df,
                badges={"Rainfall signal": signal_badge, "Data freshness": freshness_badge, "Confidence": confidence_badge},
                wrap_cols=("Recommended next check",),
                max_height=520,
            )

        report = display_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download decision report (CSV)",
            data=report,
            file_name=f"urbanpulse_decision_report_{end_date}.csv",
            mime="text/csv",
        )
        banner(
            "info",
            "The signal is station-specific, every flag has a numeric threshold, and data freshness is shown separately so a stale reading is not mistaken for a current condition.",
            title="Why this is different",
        )
        st.caption("Percentile flags describe a reading relative to the station's available historical values. They are not calibrated flood-risk levels. The source field is labelled hourly rainfall, but observation intervals may be irregular; values are therefore described as rainfall per source record. The assessment date is historical replay time, not the current time.")

elif page == "Live Open-Meteo & Alerts":
    section_header("Live forecast", "Expected rain for the next hours at each station location, from the Open-Meteo weather model. Updates every 5 minutes.", "radio")
    banner(
        "info",
        "Open-Meteo returns weather-model estimates for grid cells near the coordinates in your historical CSV. These are not measurements from your named rain gauges. Current conditions and hourly forecasts are displayed separately from historical sensor records. Threshold flags are prototype screening prompts, not official warnings or validated flood predictions.",
        title="Source distinction",
    )
    refresh_col, status_col = st.columns([1, 2])
    with refresh_col:
        if st.button("↻ Refresh weather data now", key="refresh_open_meteo", type="primary"):
            fetch_open_meteo.clear()
            st.rerun()
    auto_refresh_available = st_autorefresh is not None
    if auto_refresh_available:
        st_autorefresh(interval=300_000, limit=None, key="urbanpulse_open_meteo_auto_refresh")
    with status_col:
        if auto_refresh_available:
            st.caption("Auto-refresh: every 5 minutes · API responses cached for 5 minutes")
        else:
            st.caption("API cache: 5 minutes · Manual refresh available. Install streamlit-autorefresh for automatic page refresh.")

    if not {"latitude", "longitude"}.issubset(df.columns):
        empty_state(
            "Coordinates missing", "Your historical CSV does not contain latitude and longitude columns. Open-Meteo requires coordinates; the historical pages will still work.",
            icon_name="map", tone="issue",
        )
    else:
        station_locations = (
            df[df["station"].isin(selected_stations)]
            .dropna(subset=["latitude", "longitude"])
            .sort_values("timestamp")
            .groupby("station", as_index=False)
            .agg(latitude=("latitude", "first"), longitude=("longitude", "first"))
        )
        station_locations = station_locations[
            station_locations["latitude"].between(-90, 90) & station_locations["longitude"].between(-180, 180)
        ]
        locations = tuple((str(row.station), float(row.latitude), float(row.longitude)) for row in station_locations.itertuples(index=False))
        if len(locations) > 10:
            with panel("Choose stations for the live forecast", f"{len(locations):,} stations are selected in the sidebar. Fetching all of them takes several minutes, so pick up to 40 here.", name="live_pick"):
                chosen = st.multiselect(
                    "Stations to fetch", [item[0] for item in locations],
                    default=[item[0] for item in locations[:10]], max_selections=40,
                )
            locations = tuple(item for item in locations if item[0] in chosen)
        if not locations:
            empty_state("No stations chosen", "Pick at least one station with valid coordinates to load the live forecast.", icon_name="map", tone="warn")
        else:
            skeleton = st.empty()
            skeleton.markdown(skeleton_html(), unsafe_allow_html=True)
            with st.spinner(f"Fetching Open-Meteo estimates for {len(locations)} selected station coordinates…"):
                live_rows, live_error, fetched_at = fetch_open_meteo(locations)
            skeleton.empty()
            valid_rows = [r for r in live_rows if not r.get("error")]
            failed_rows = [r for r in live_rows if r.get("error")]
            live_df = pd.DataFrame([{k: v for k, v in row.items() if k != "hourly_forecast"} for row in valid_rows])
            high_flags = sum(weather_screening_flag(r.get("next_6h_precipitation_mm", float("nan")), r.get("next_24h_precipitation_mm", float("nan"))).startswith(("High", "Elevated")) for r in valid_rows)
            all_returned = len(valid_rows) == len(locations)
            kpi_grid([
                metric_card("Coordinates requested", f"{len(locations):,}", "From selected historical stations", icon_name="pin"),
                metric_card(
                    "Locations with data", f"{len(valid_rows):,}", "Open-Meteo response objects received", icon_name="radio",
                    tone="ok" if all_returned else "warn", status=("OK", "ok") if all_returned else ("Warning", "warn"),
                ),
                metric_card(
                    "Forecast review flags", f"{high_flags:,}", "Prototype thresholds; not official warnings", icon_name="alert",
                    tone="warn" if high_flags else "ok", status=("Review", "warn") if high_flags else ("OK", "ok"),
                ),
                metric_card("Refresh interval", "5 min", "Model data may update less frequently", icon_name="clock"),
            ])
            st.caption(f"Fetch time (UTC): {fetched_at}. Forecast/current timestamps are provided by Open-Meteo in Asia/Kolkata time. Refreshing the dashboard does not mean the underlying weather model updates every five minutes.")

            if live_error:
                banner("danger", esc(str(live_error)), title="Open-Meteo reported a problem")
            if failed_rows:
                banner("warning", f"{len(failed_rows)} coordinate(s) did not return a usable forecast object.")
                data_table(pd.DataFrame(failed_rows).drop(columns=["hourly_forecast"], errors="ignore"))

            if not live_df.empty:
                banner("success", f"{len(valid_rows)} of {len(locations)} selected coordinates returned data.", title="Open-Meteo API connected")
                map_df = pd.DataFrame(valid_rows).copy()
                for numeric in ["latitude", "longitude", "next_6h_precipitation_mm", "next_24h_precipitation_mm"]:
                    if numeric in map_df.columns:
                        map_df[numeric] = pd.to_numeric(map_df[numeric], errors="coerce")
                map_df = map_df.dropna(subset=["latitude", "longitude"])
                map_df["next_6h_precipitation_mm"] = map_df["next_6h_precipitation_mm"].fillna(0)
                def forecast_marker_color(value):
                    return scale_color(value, FORECAST_SCALE, 225)
                map_df["marker_color"] = map_df["next_6h_precipitation_mm"].apply(forecast_marker_color)
                map_df["marker_radius"] = map_df["next_6h_precipitation_mm"].apply(lambda v: 260 if v >= 30 else 210 if v >= 15 else 160 if v > 0 else 120)
                if not map_df.empty:
                    center_lat = float((map_df["latitude"].min() + map_df["latitude"].max()) / 2)
                    center_lon = float((map_df["longitude"].min() + map_df["longitude"].max()) / 2)
                    span = max(float(map_df["latitude"].max() - map_df["latitude"].min()), float(map_df["longitude"].max() - map_df["longitude"].min()), 0.05)
                    zoom = max(7.0, min(11.0, 8.5 - math.log2(span / 0.5)))
                    map_df["next_6h_txt"] = map_df["next_6h_precipitation_mm"].round(2)
                    map_df["next_24h_txt"] = map_df["next_24h_precipitation_mm"].round(2)
                    forecast_layer = pdk.Layer(
                        "ScatterplotLayer", data=map_df, get_position="[longitude, latitude]",
                        get_fill_color="marker_color", get_line_color=[235, 245, 255, 230],
                        get_radius="marker_radius", radius_min_pixels=5, radius_max_pixels=18,
                        stroked=True, line_width_min_pixels=1, pickable=True, auto_highlight=True,
                    )
                    with panel("Live forecast map", "Markers are weather-model estimates at the coordinates in your CSV, not readings from the physical gauges.", name="live_map"):
                        forecast_deck = pdk.Deck(
                            layers=[forecast_layer],
                            initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0),
                            tooltip=deck_tooltip("station", [("Forecast, next 6 h", "next_6h_txt"), ("Forecast, next 24 h", "next_24h_txt")]),
                            map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
                        )
                        _call_stretch(st.pydeck_chart, forecast_deck, height=430)
                        _md(map_legend("Forecast precipitation, next 6 h (mm)", FORECAST_SCALE, "Review prompts only; not official warnings."))
                live_df["UrbanPulse screening flag"] = live_df.apply(
                    lambda r: weather_screening_flag(r.get("next_6h_precipitation_mm"), r.get("next_24h_precipitation_mm")), axis=1
                )
                live_df = live_df.rename(columns={
                    "station": "Historical station label (coordinate lookup)",
                    "latitude": "Latitude", "longitude": "Longitude",
                    "current_time": "Open-Meteo current timestamp (local)",
                    "temperature_c": "Temperature (°C)",
                    "relative_humidity_percent": "Relative humidity (%)",
                    "current_precipitation_mm": "Current precipitation (mm/model interval)",
                    "current_rain_mm": "Current rain (mm/model interval)",
                    "wind_speed_kmh": "Wind speed (km/h)",
                    "next_6h_precipitation_mm": "Forecast precipitation next 6h (mm)",
                    "next_24h_precipitation_mm": "Forecast precipitation next 24h (mm)",
                    "model_elevation_m": "Model elevation (m)",
                })
                display_cols = [c for c in [
                    "Historical station label (coordinate lookup)", "Latitude", "Longitude",
                    "Open-Meteo current timestamp (local)", "Temperature (°C)", "Relative humidity (%)",
                    "Current precipitation (mm/model interval)", "Current rain (mm/model interval)",
                    "Wind speed (km/h)", "Forecast precipitation next 6h (mm)",
                    "Forecast precipitation next 24h (mm)", "UrbanPulse screening flag", "Model elevation (m)",
                ] if c in live_df.columns]
                numeric_cols = [c for c in display_cols if c in live_df.columns and c not in ["Historical station label (coordinate lookup)", "Open-Meteo current timestamp (local)", "UrbanPulse screening flag"]]
                for col in numeric_cols:
                    live_df[col] = pd.to_numeric(live_df[col], errors="coerce").round(2)
                sorted_live = live_df.sort_values("Forecast precipitation next 6h (mm)", ascending=False, na_position="last") if "Forecast precipitation next 6h (mm)" in live_df.columns else live_df
                with panel("Current conditions and forecast review", "One model-grid estimate per selected station coordinate"):
                    data_table(
                        sorted_live[display_cols],
                        badges={"UrbanPulse screening flag": flag_badge},
                        col_decimals={"Latitude": 4, "Longitude": 4},
                        max_height=520,
                    )
                st.download_button(
                    "Download live estimates and screening flags (CSV)",
                    data=sorted_live[display_cols].to_csv(index=False).encode("utf-8"),
                    file_name=f"urbanpulse_open_meteo_{pd.Timestamp.now().date()}.csv",
                    mime="text/csv",
                )

                forecast_frames = []
                for row in valid_rows:
                    hourly_rows = row.get("hourly_forecast", [])
                    if hourly_rows:
                        hourly_df = pd.DataFrame(hourly_rows)
                        hourly_df["forecast_time"] = pd.to_datetime(hourly_df["forecast_time"], errors="coerce")
                        hourly_frames = hourly_df[hourly_df["forecast_time"] >= pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)]
                        if not hourly_frames.empty:
                            forecast_frames.append(hourly_frames.head(24))
                if forecast_frames:
                    forecast_all = pd.concat(forecast_frames, ignore_index=True)
                    forecast_chart = style_chart(
                        alt.Chart(forecast_all).mark_line(point=True, strokeCap="round", strokeJoin="round", strokeWidth=2).encode(
                            x=alt.X("forecast_time:T", title="Forecast time (Asia/Kolkata)"),
                            y=alt.Y("forecast_precipitation_mm:Q", title="Forecast precipitation (mm/hour)"),
                            color=station_color("Coordinate label"),
                            tooltip=["station:N", alt.Tooltip("forecast_time:T", title="Time"), alt.Tooltip("forecast_precipitation_mm:Q", title="Precipitation (mm)", format=".2f"), alt.Tooltip("precipitation_probability_percent:Q", title="Precipitation probability (%)")],
                        ),
                        360,
                    )
                    with panel("Hourly precipitation forecast", "Forecast values are model estimates in millimetres per hour"):
                        _call_stretch(st.altair_chart, forecast_chart, theme=None)
                st.caption("Screening thresholds used by this prototype: elevated if forecast precipitation is ≥15 mm over 6 hours or ≥35 mm over 24 hours; high if ≥30 mm over 6 hours or ≥75 mm over 24 hours. These are review prompts chosen for the prototype, not official IMD thresholds, a calibrated flood model, or a guarantee of local impacts.")
            else:
                empty_state(
                    "No usable forecast data", str(live_error) if live_error else "Open-Meteo returned no usable location data.",
                    icon_name="radio", tone="warn", hint="Historical pages remain available. Check your internet connection and the coordinate columns, then refresh.",
                )

    with panel("Data source and limitations", name="live_sources"):
        st.write("Open-Meteo provides weather-model data at requested coordinates. Station names shown here are labels inherited from your CSV; they do not mean Open-Meteo is reading those physical gauges. Model output can be spatially smoothed and may differ from local sensor observations.")
        st.markdown("Source: [Open-Meteo API documentation](https://open-meteo.com/en/docs) · [Open-Meteo service](https://open-meteo.com/)")
        st.caption("The live panel needs internet access but no account, sign-in, API token, or extra authentication. Open-Meteo data attribution is required under CC BY 4.0. This is a monitoring prototype, not an official flood warning service.")

elif page == "Spatial Matrix":
    section_header("Station map", "Where each station is and how much rain it has recorded. Hover over a dot for details.", "map")
    if not {"latitude", "longitude"}.issubset(filtered.columns):
        empty_state("No map available", "The loaded CSV does not contain latitude and longitude columns, so a station map cannot be drawn.", icon_name="map", tone="warn")
    else:
        loc = filtered.dropna(subset=["latitude", "longitude"]).groupby("station").agg(
            latitude=("latitude", "first"),
            longitude=("longitude", "first"),
            readings=("rainfall_mm", "size"),
            mean_rainfall_mm=("rainfall_mm", "mean"),
            max_rainfall_mm=("rainfall_mm", "max"),
        ).reset_index()
        if loc.empty:
            empty_state("No usable coordinates", "No usable station coordinates are available in the filtered records.", icon_name="map", tone="warn")
        else:
            # Validate coordinates before plotting; keep flagged records visible in the audit table.
            loc["coordinate_valid"] = (
                loc["latitude"].between(12, 14)
                & loc["longitude"].between(77, 78)
            )
            loc["max_rainfall_mm"] = pd.to_numeric(
                loc["max_rainfall_mm"], errors="coerce"
            ).fillna(0)

            # Color markers by maximum observed rainfall in the currently filtered records.
            # These colors describe historical observations, not live flood risk.
            def rainfall_color(value):
                return scale_color(value, RAIN_SCALE, 220)

            loc["marker_color"] = loc["max_rainfall_mm"].apply(rainfall_color)
            loc["marker_radius"] = loc["max_rainfall_mm"].apply(
                lambda value: 240 if value >= 75 else 200 if value >= 50 else 165 if value >= 25 else 135
            )
            loc["mean_txt"] = loc["mean_rainfall_mm"].round(2)
            loc["max_txt"] = loc["max_rainfall_mm"].round(2)

            layer = pdk.Layer(
                "ScatterplotLayer",
                data=loc,
                get_position="[longitude, latitude]",
                get_fill_color="marker_color",
                get_line_color=[235, 245, 255, 230],
                get_radius="marker_radius",
                radius_min_pixels=5,
                radius_max_pixels=18,
                stroked=True,
                line_width_min_pixels=1,
                pickable=True,
                auto_highlight=True,
            )

            # Frame the map around the station spread instead of relying on one fixed center.
            center_lat = float((loc["latitude"].min() + loc["latitude"].max()) / 2)
            center_lon = float((loc["longitude"].min() + loc["longitude"].max()) / 2)
            span = max(
                float(loc["latitude"].max() - loc["latitude"].min()),
                float(loc["longitude"].max() - loc["longitude"].min()),
                0.05,
            )
            zoom = max(7.0, min(10.0, 8.5 - math.log2(span / 0.5)))

            coords_ok = int(loc["coordinate_valid"].sum())
            kpi_grid([
                metric_card("Stations plotted", f"{len(loc):,}", "With usable coordinates in the current filters", icon_name="pin"),
                metric_card(
                    "Coordinates in range", f"{coords_ok:,} / {len(loc):,}", "Checked against broad regional bounds", icon_name="check",
                    tone="ok" if coords_ok == len(loc) else "warn", status=("OK", "ok") if coords_ok == len(loc) else ("Warning", "warn"),
                ),
                metric_card("Highest station maximum", f"{loc['max_rainfall_mm'].max():.2f} mm", "Maximum recorded rainfall across plotted stations", icon_name="rain"),
            ], min_width=240)

            with panel("Station map", "Marker color and size represent maximum recorded rainfall in the current filters.", name="map"):
                deck = pdk.Deck(
                    layers=[layer],
                    initial_view_state=pdk.ViewState(
                        latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0
                    ),
                    tooltip=deck_tooltip("station", [
                        ("Readings", "readings"), ("Mean rainfall (mm)", "mean_txt"),
                        ("Max rainfall (mm)", "max_txt"), ("Coordinates in range", "coordinate_valid"),
                    ]),
                    map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
                )
                _call_stretch(st.pydeck_chart, deck, height=550)
                _md(map_legend("Max recorded rainfall (mm)", RAIN_SCALE, "Marker size also scales with intensity."))

            with panel("Station table", "Per-station summary for the markers shown on the map"):
                data_table(
                    loc[["station", "latitude", "longitude", "coordinate_valid", "readings",
                        "mean_rainfall_mm", "max_rainfall_mm"]].round(4),
                    badges={"coordinate_valid": coordinate_badge},
                    col_decimals={"latitude": 4, "longitude": 4},
                )
            banner(
                "info",
                "Marker colors are historical summaries, not live alerts. Coordinate checks use broad regional bounds. Map points use source coordinates, and a geographic filter is not the same as an official city boundary.",
            )

elif page == "Telemetry Trends":
    section_header("Rainfall trends", "How rainfall changed over time. Hover over a point to see the exact reading; gaps mean no data was recorded.", "chart")
    with panel("Rainfall over time", name="trends"):
        chart_style = st.radio("View", ["Recorded observations", "Daily mean (observed days only)"], horizontal=True)
        if chart_style == "Daily mean (observed days only)":
            plot_df = filtered.copy()
            plot_df["date"] = plot_df["timestamp"].dt.floor("D")
            plot_df = plot_df.groupby(["date", "station"], as_index=False)["rainfall_mm"].mean()
            x_col = "date"
            y_title = "Mean recorded rainfall (mm per source record)"
        else:
            plot_df = filtered
            x_col = "timestamp"
            y_title = "Rainfall per source record (mm)"
        trend = style_chart(
            alt.Chart(plot_df).mark_line(point=alt.OverlayMarkDef(size=35), strokeWidth=2, strokeCap="round", strokeJoin="round").encode(
                x=alt.X(f"{x_col}:T", title="Date/time"),
                y=alt.Y("rainfall_mm:Q", title=y_title),
                color=station_color(),
                tooltip=["station:N", alt.Tooltip(f"{x_col}:T", title="Time"), alt.Tooltip("rainfall_mm:Q", format=".2f")],
            ),
            430,
        )
        _call_stretch(st.altair_chart, trend, theme=None)
        st.caption("Daily means summarize available readings only; they are not complete daily rainfall totals.")

elif page == "Sensor Log Matrix":
    section_header("Raw records", "Every reading behind the charts. Click a column header to sort, and download the table if you need it.", "table")
    table = filtered.copy()
    table["gap_hours"] = table["gap_hours"].round(2)
    table = table.rename(columns={
        "timestamp": "OBSERVATION TIME",
        "station": "STATION",
        "rainfall_mm": "RAINFALL (mm per source record)",
        "latitude": "LATITUDE",
        "longitude": "LONGITUDE",
        "gap_hours": "GAP SINCE PREVIOUS READING (hours)",
    })
    with panel("Source records", f"{len(table):,} rows in the current filters. Sort and search in the grid; download the filtered set below.", name="log"):
        _call_stretch(st.dataframe, table, hide_index=True)
        st.download_button(
            "Download filtered rainfall CSV",
            data=table.to_csv(index=False).encode("utf-8"),
            file_name="urbanpulse_filtered_rainfall.csv",
            mime="text/csv",
        )

else:
    section_header("Data health", "Is the data complete and trustworthy? Green means fine, amber means look closer, red means a problem.", "shield")
    total_n = len(filtered)
    zero_n = int((filtered["rainfall_mm"] == 0).sum())
    neg_n = int((filtered["rainfall_mm"] < 0).sum())
    gap_intervals = int(filtered["gap_hours"].notna().sum())
    gap_state = dq_status(gaps_over_threshold, gap_intervals)
    gap_status = (gap_state, {"OK": "ok", "Warning": "warn", "Issue": "issue"}[gap_state])
    neg_status = ("OK", "ok") if neg_n == 0 else ("Issue", "issue")
    gap_pct = (gaps_over_threshold / gap_intervals * 100) if gap_intervals else 0.0
    kpi_grid([
        metric_card("Missing required values", "0", "Rows with invalid timestamp/station/rainfall are removed during loading", icon_name="check", tone="ok", status=("OK", "ok")),
        metric_card("Zero rainfall readings", f"{zero_n:,}", "Measured zero values in this filtered dataset", icon_name="rain", delta=f"{zero_n / total_n * 100:.1f}% of readings", status=("OK", "ok")),
        metric_card("Negative values", f"{neg_n:,}", "Negative values are excluded during loading", icon_name="alert", tone=neg_status[1], status=neg_status),
        metric_card(
            "Gaps over threshold", f"{gaps_over_threshold:,}", f"Visible consecutive-reading intervals over {gap_threshold} hours",
            icon_name="clock", tone=gap_status[1], status=gap_status, delta=f"{gap_pct:.1f}% of intervals", delta_tone=gap_status[1],
        ),
    ])

    left, right = st.columns([1.2, 1], gap="large")
    with left:
        with panel("Checks overview", "Status of each check for the current view", name="dq_checks"):
            _md(
                check_row("check", "Required fields", "Timestamp, station and rainfall present", ("OK", "ok"), "0 invalid")
                + check_row("alert", "Negative rainfall", "Excluded when the file is loaded", neg_status, f"{neg_n:,}")
                + check_row("rain", "Zero readings", "Valid measurements; dry periods are not errors", ("OK", "ok"), f"{zero_n:,}")
                + check_row("clock", "Reporting gaps", f"Intervals longer than {gap_threshold} hours", gap_status, f"{gaps_over_threshold:,}")
            )
    with right:
        with panel("Data composition", "How the visible records and intervals break down", name="dq_mix"):
            _md(
                stacked_bar("Readings", [("Rainfall recorded", total_n - zero_n, T["info"]), ("Zero rainfall", zero_n, T["text-3"])])
                + stacked_bar("Reporting intervals", [("Within threshold", gap_intervals - gaps_over_threshold, T["success"]), ("Over threshold", gaps_over_threshold, T["warning"])])
            )

    coverage = filtered.groupby("station").agg(
        readings=("rainfall_mm", "size"),
        intervals=("gap_hours", "count"),
        gaps=("gap_hours", lambda x: int((x > gap_threshold).sum())),
        longest_gap_hours=("gap_hours", "max"),
    ).reset_index()
    coverage["Status"] = [dq_status(g, n) for g, n in zip(coverage["gaps"], coverage["intervals"])]
    coverage = coverage.sort_values(["gaps", "longest_gap_hours"], ascending=False).rename(columns={
        "station": "Station", "readings": "Readings", "intervals": "Intervals",
        "gaps": "Gaps over threshold", "longest_gap_hours": "Longest gap (hours)",
    })
    with panel("Station coverage", f"Warning: any gap over {gap_threshold} h · Issue: {DQ_ISSUE_SHARE:.0%} or more of a station's intervals", name="dq_coverage"):
        data_table(coverage, badges={"Status": status_badge})

    gap_df = filtered[filtered["gap_hours"] > gap_threshold].copy()
    with panel("Long reporting gaps", "Intervals between consecutive visible observations", name="dq_gaps"):
        if gap_df.empty:
            banner("success", "No reporting gaps exceed the selected threshold in this filtered view.", title="No long gaps")
        else:
            gap_df = gap_df[["station", "timestamp", "gap_hours"]].rename(columns={
                "station": "STATION",
                "timestamp": "LATER OBSERVATION TIME",
                "gap_hours": "GAP (hours)",
            })
            gap_df["GAP (hours)"] = gap_df["GAP (hours)"].round(2)
            data_table(gap_df.sort_values("GAP (hours)", ascending=False))
    banner(
        "info",
        "A reporting gap means there is no observation in that interval. It does not mean rainfall was zero. These checks do not establish sensor uptime, measurement accuracy, or flood risk. Status badges are a presentation heuristic over the numbers above.",
        title="Interpretation",
    )

banner(
    "info",
    "UrbanPulse combines historical rainfall observations with Open-Meteo model estimates at station coordinates; neither is direct gauge telemetry. It is a monitoring prototype and not an official flood warning service.",
    title="Not a flood warning service",
)
_md(
    '<div style="text-align:center;color:var(--text-3);font-size:12px;line-height:1.7;margin-top:16px">'
    'UrbanPulse Rainfall Intelligence · Historical analysis + Open-Meteo model estimates<br>'
    'Credits: weather data by <a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo.com</a> (CC BY 4.0) · '
    'Map © <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>, '
    '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors · '
    'Icons adapted from <a href="https://lucide.dev" target="_blank" rel="noopener">Lucide</a> (ISC) · '
    'Fonts: Plus Jakarta Sans and JetBrains Mono (SIL OFL). Rainfall data: Karnataka telemetry hourly rainfall via the <a href="https://nwdp.nwic.gov.in/en/dataset/rainfall-telemetry-hourly-karnataka-department" target="_blank" rel="noopener">National Water Data Portal</a>.'
    '</div>'
)
