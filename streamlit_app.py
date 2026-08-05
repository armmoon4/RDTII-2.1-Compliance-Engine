"""
RDTII 2.1 Compliance Engine — Streamlit Audit Dashboard
"""
import os
import time
import requests
import streamlit as st
from datetime import datetime

st.set_page_config(
    page_title="RDTII 2.1 | Audit Dashboard",
    page_icon="asset/UN_emblem_blue.svg.png",
    layout="wide",
    initial_sidebar_state="collapsed",
)

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")
EXPORT_BASE = os.environ.get("EXPORT_BASE_URL", "http://localhost:8000")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');
    
    html, body, .stApp {
        background: linear-gradient(135deg, #0f1117 0%, #1a1d24 100%) !important; 
        color: #e1e4e8; 
        font-family: 'Outfit', sans-serif;
    }
    .main .block-container { max-width: 1400px; padding: 2rem 3rem; }
    h1, h2, h3 { color: #ffffff; font-weight: 600; letter-spacing: -0.02em; }
    h1 { font-size: 2rem; background: -webkit-linear-gradient(45deg, #58a6ff, #9b51e0); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 0.5rem; }

    /* Hide Sidebar Completely */
    section[data-testid="stSidebar"] { display: none !important; }
    .stApp > header { background: transparent !important; }

    .st-bw { background: transparent !important; }

    div.row-widget.stRadio > div { flex-direction: row; gap: 12px; }
    .stSelectbox, .stMultiSelect { background: rgba(22, 27, 34, 0.6); border-radius: 8px; backdrop-filter: blur(10px); }
    .stSelectbox div[data-baseweb="select"], .stMultiSelect div[data-baseweb="select"] {
        background: transparent; border: 1px solid rgba(48, 54, 61, 0.8); border-radius: 8px; color: #e1e4e8;
        transition: all 0.3s ease;
    }
    .stSelectbox div[data-baseweb="select"]:hover, .stMultiSelect div[data-baseweb="select"]:hover { 
        border-color: #58a6ff; box-shadow: 0 0 10px rgba(88, 166, 255, 0.2); 
    }
    div[data-baseweb="select"] > div { background: transparent !important; }
    .st-bx { background: transparent !important; border: none !important; }

    .stForm {
        background: rgba(22, 27, 34, 0.5); border: 1px solid rgba(255, 255, 255, 0.05); 
        border-radius: 12px; padding: 24px; backdrop-filter: blur(12px);
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
    }
    .stForm label { color: #a1aab5; font-size: 0.85rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; }

    .card {
        background: rgba(22, 27, 34, 0.6); border: 1px solid rgba(255, 255, 255, 0.05); 
        border-radius: 10px; padding: 18px 22px; margin-bottom: 12px;
        backdrop-filter: blur(10px); transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .card:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.3); }
    .card-label { font-size: 0.75rem; color: #a1aab5; text-transform: uppercase; letter-spacing: 0.08em; }
    .card-value { font-size: 1.3rem; font-weight: 600; color: #ffffff; margin-top: 4px; }

    .pill-ok     { background: rgba(63, 185, 80, 0.15); color: #3fb950; border: 1px solid rgba(63, 185, 80, 0.3); padding: 4px 12px; border-radius: 99px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }
    .pill-error  { background: rgba(248, 81, 73, 0.15); color: #f85149; border: 1px solid rgba(248, 81, 73, 0.3); padding: 4px 12px; border-radius: 99px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }
    .pill-warn   { background: rgba(210, 153, 34, 0.15); color: #d29922; border: 1px solid rgba(210, 153, 34, 0.3); padding: 4px 12px; border-radius: 99px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }
    .pill-info   { background: rgba(88, 166, 255, 0.15); color: #58a6ff; border: 1px solid rgba(88, 166, 255, 0.3); padding: 4px 12px; border-radius: 99px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }

    .error-box { background: rgba(248, 81, 73, 0.1); border: 1px solid rgba(248, 81, 73, 0.3); border-radius: 8px; padding: 12px 16px; color: #fca5a5; font-family: monospace; font-size: 0.85rem; }

    div[data-testid="stExpander"] {
        background: rgba(22, 27, 34, 0.4); border: 1px solid rgba(255, 255, 255, 0.05); 
        border-radius: 10px; margin-bottom: 12px; overflow: hidden; backdrop-filter: blur(8px);
    }
    div[data-testid="stExpander"] > details { padding: 0; }
    div[data-testid="stExpander"] > details > summary {
        padding: 14px 20px; font-weight: 500; background: transparent; min-height: 48px;
    }
    div[data-testid="stExpander"] > details[open] > summary { border-bottom: 1px solid rgba(255, 255, 255, 0.05); }
    div[data-testid="stExpander"] div[data-testid="stExpanderContent"] { padding: 20px; }
    div[data-testid="stExpander"] .st-bw { background: transparent; }

    .metric-row { display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
    .metric-item { background: rgba(13, 17, 23, 0.5); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; padding: 12px 16px; flex: 1; min-width: 140px; }
    .metric-item .lbl { font-size: 0.75rem; color: #a1aab5; text-transform: uppercase; letter-spacing: 0.05em; }
    .metric-item .val { font-size: 1.15rem; font-weight: 600; color: #ffffff; margin-top: 4px; }

    .stProgress > div > div { background: rgba(255, 255, 255, 0.1); border-radius: 99px; }
    .stProgress > div > div > div { background: linear-gradient(90deg, #3fb950, #58a6ff); border-radius: 99px; }

    button[kind="primary"] { 
        background: linear-gradient(90deg, #58a6ff, #9b51e0) !important; 
        border: none !important; color: #fff !important; font-weight: 600; border-radius: 8px;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    button[kind="primary"]:hover { 
        transform: translateY(-1px); box-shadow: 0 4px 15px rgba(155, 81, 224, 0.4) !important; 
    }

    div[data-testid="stDataFrame"] { background: transparent; }
    div[data-testid="stDataFrame"] th { background: rgba(13, 17, 23, 0.8) !important; color: #a1aab5; font-size: 0.8rem; text-transform: uppercase; border-bottom: 1px solid rgba(255, 255, 255, 0.05); }
    div[data-testid="stDataFrame"] td { background: transparent !important; color: #e1e4e8; border-bottom: 1px solid rgba(255, 255, 255, 0.05); }
    div[data-testid="stDataFrame"] tr:hover td { background: rgba(88, 166, 255, 0.1) !important; }

    .stCaption { color: #a1aab5; font-size: 0.85rem; }
    hr { border-color: rgba(255, 255, 255, 0.05); margin: 1.5rem 0; }
    a { color: #58a6ff; text-decoration: none; transition: color 0.2s ease; }
    a:hover { color: #9b51e0; text-decoration: underline; }
    .st-bb { border-bottom: none; }
</style>
""", unsafe_allow_html=True)


def _get(path: str):
    for attempt in range(2, -1, -1):
        try:
            r = requests.get(f"{API_BASE}{path}", timeout=30)
            r.raise_for_status()
            return r.json(), None
        except requests.exceptions.ConnectionError:
            if attempt:
                time.sleep(2)
                continue
            return None, f"Cannot connect to API at {API_BASE}"
        except Exception as exc:
            if attempt:
                time.sleep(2)
                continue
            return None, str(exc)


STATUS_STYLE = {
    "COMPLETE": "pill-ok", "FAILED": "pill-error",
    "QUEUED": "pill-warn", "DISCOVERING": "pill-info",
    "ANALYSING": "pill-warn", "RUNNING": "pill-warn",
}

# ── Top Navigation ────────────────────────────────────────────────────────────

nav_col1, nav_col2, nav_col3, nav_col4 = st.columns([2, 1.5, 1, 1])
with nav_col1:
    st.markdown("<h1>RDTII 2.1 <span style='font-size:1.2rem;color:#a1aab5;font-weight:400;'>Audit Dashboard</span></h1>", unsafe_allow_html=True)
    st.caption("UNESCAP Hackathon 2026 — Team SUPERNOVA")
with nav_col2:
    st.markdown(f"<div style='margin-top:10px;'><b>API:</b> <code>{API_BASE}</code> &nbsp;|&nbsp; <a href='{API_BASE}/docs' target='_blank'>Docs</a></div>", unsafe_allow_html=True)
with nav_col3:
    page = st.radio("Page", ["Dashboard", "All Results", "Review Queue", "Audit View", "Token Burn", "Countries"], label_visibility="collapsed", horizontal=True)
with nav_col4:
    st.markdown("<div style='margin-top:10px;'>", unsafe_allow_html=True)
    auto_refresh = st.toggle("Auto-refresh (10s)", value=False)
    if st.button("Refresh Now", use_container_width=True):
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

if auto_refresh:
    time.sleep(10)
    st.rerun()

if page == "Token Burn":
    st.subheader("Token Burn — Per Analysis")

    PRICING = {
        "OpenAI (GPT-4o-mini)":    {"input_per_1m": 0.15, "output_per_1m": 0.60, "color": "#19c37d"},
        "Gemini (2.5 Flash)":      {"input_per_1m": 0.15, "output_per_1m": 0.60, "color": "#4285f4"},
        "DeepSeek (deepseek-chat)": {"input_per_1m": 0.27, "output_per_1m": 1.10, "color": "#4f6b8a"},
        "Grok (grok-2)":           {"input_per_1m": 2.00, "output_per_1m": 10.00, "color": "#1c1c1c"},
        "MiniMax-M3 (Free)":       {"input_per_1m": 0, "output_per_1m": 0, "color": "#ff6b6b"},
        "Nvidia Nemotron (Free)":  {"input_per_1m": 0, "output_per_1m": 0, "color": "#76b900"},
        "Ollama (Local)":          {"input_per_1m": 0, "output_per_1m": 0, "color": "#f5a623"},
    }

    def _est_cost(prov: str, inp: int, out: int) -> float:
        info = PRICING.get(prov)
        if not info or (info["input_per_1m"] == 0 and info["output_per_1m"] == 0):
            return 0.0
        return (inp / 1_000_000) * info["input_per_1m"] + (out / 1_000_000) * info["output_per_1m"]

    tab_actual, tab_calc = st.tabs(["Actual Token Usage", "Token Calculator"])

    with tab_actual:
        tus, tus_err = _get("/api/v1/analysis/token-usage?limit=50")
        if tus_err:
            st.markdown(f'<div class="error-box">{tus_err}</div>', unsafe_allow_html=True)
        elif not tus:
            st.info("No analysis runs yet. Submit an analysis to see token burn data.")
        else:
            rows = []
            for t in tus:
                rows.append({
                    "Run ID": t["run_id"][:8] + "...",
                    "Country": t["country"],
                    "Status": t["status"],
                    "Provider": t.get("llm_provider") or "auto",
                    "Input Tokens": f'{t["total_input_tokens"]:,}',
                    "Output Tokens": f'{t["total_output_tokens"]:,}',
                    "Total Tokens": f'{t["total_tokens"]:,}',
                    "Est. Cost": f'${t["estimated_cost_usd"]:.6f}' if t["estimated_cost_usd"] > 0 else "FREE",
                    "Indicators": t["indicators_analysed"],
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)

            if tus:
                total_in = sum(t["total_input_tokens"] for t in tus)
                total_out = sum(t["total_output_tokens"] for t in tus)
                total_cost = sum(t["estimated_cost_usd"] for t in tus)
                m1, m2, m3, m4 = st.columns(4)
                with m1: st.metric("Total Input Tokens", f"{total_in:,}")
                with m2: st.metric("Total Output Tokens", f"{total_out:,}")
                with m3: st.metric("Total Tokens Burned", f"{total_in + total_out:,}")
                with m4: st.metric("Total Cost", f"${total_cost:.4f}" if total_cost > 0 else "FREE")

    with tab_calc:
        st.markdown("<p style='color:#8b949e;'>Estimate token consumption before submitting an analysis</p>", unsafe_allow_html=True)

        c1, c2 = st.columns([3, 2])
        with c1:
            provider = st.selectbox("Provider", options=list(PRICING.keys()), index=0)
            p = PRICING[provider]
            input_text = st.text_area("Input / System Prompt", height=140, placeholder="Paste your prompt...")
            output_text = st.text_area("Expected Output", height=100, placeholder="Paste expected response...")
        with c2:
            is_free = p["input_per_1m"] == 0 and p["output_per_1m"] == 0
            st.markdown(
                f'<div class="card"><div class="card-label">Provider</div>'
                f'<div class="card-value" style="color:{p["color"]};">{provider}</div></div>',
                unsafe_allow_html=True,
            )
            in_tok = len(input_text or "") // 4
            out_tok = len(output_text or "") // 4
            cost = _est_cost(provider, in_tok, out_tok)
            st.markdown(
                f'<div class="metric-row">'
                f'<div class="metric-item"><div class="lbl">Input Tokens</div><div class="val">{in_tok:,}</div></div>'
                f'<div class="metric-item"><div class="lbl">Output Tokens</div><div class="val">{out_tok:,}</div></div>'
                f'<div class="metric-item"><div class="lbl">Total</div><div class="val">{in_tok + out_tok:,}</div></div>'
                f'<div class="metric-item"><div class="lbl">Cost</div><div class="val" style="color:{"#3fb950" if is_free else "#58a6ff"};">{"FREE" if is_free else f"${cost:.8f}"}</div></div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if not is_free and in_tok + out_tok > 0:
                per_1k = cost * 1000 if cost > 0 else 0
                st.caption(f"${cost:.6f} total &nbsp;·&nbsp; ${per_1k:.4f} / 1K tokens")

        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown("##### Per-Analysis Estimate")
        calls = st.slider("LLM calls per indicator", 1, 10, 5)
        indicators = st.slider("Number of indicators", 1, 61, 61)
        avg_in = st.number_input("Avg input tokens per call", 1000, 100000, 8000, step=500)
        avg_out = st.number_input("Avg output tokens per call", 500, 50000, 2000, step=500)

        total_calls = calls * indicators
        total_in = total_calls * avg_in
        total_out = total_calls * avg_out
        total_cost_est = _est_cost(provider, total_in, total_out)

        b1, b2, b3, b4 = st.columns(4)
        with b1: st.metric("Total LLM Calls", f"{total_calls:,}")
        with b2: st.metric("Total Input", f"{total_in:,}")
        with b3: st.metric("Total Output", f"{total_out:,}")
        with b4: st.metric("Est. Cost", "FREE" if is_free else f"${total_cost_est:.4f}")

        st.caption("~1 token ~ 4 characters (English). Estimate only — varies by model.")

    st.stop()

if page == "Countries":
    st.subheader("Analysed Countries")
    cdata, cerr = _get("/api/v1/analysis/countries")
    if cerr:
        st.markdown(f'<div class="error-box">{cerr}</div>', unsafe_allow_html=True)
    elif not cdata:
        st.info("No countries have been analysed yet.")
    else:
        st.markdown(f'**{len(cdata)} countries analysed**')
        for country in cdata:
            st.markdown(
                f'<div class="card" style="display:flex;align-items:center;gap:12px;">'
                f'<span style="font-size:1.2rem;font-weight:600;">{country}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
    st.stop()

if page == "All Results":
    st.subheader("All Results")

    PAGE_SIZE = 50
    if "all_results_offset" not in st.session_state:
        st.session_state.all_results_offset = 0

    c_prev, c_info, c_next = st.columns([1, 6, 1])
    with c_prev:
        if st.button("← Previous", disabled=(st.session_state.all_results_offset == 0)):
            st.session_state.all_results_offset = max(0, st.session_state.all_results_offset - PAGE_SIZE)
            st.rerun()
    with c_next:
        if st.button("Next →"):
            st.session_state.all_results_offset += PAGE_SIZE
            st.rerun()

    offset = st.session_state.all_results_offset
    alldata, alldata_err = _get(f"/api/v1/analysis/results/all?limit={PAGE_SIZE}&offset={offset}")
    if alldata_err:
        st.markdown(f'<div class="error-box">{alldata_err}</div>', unsafe_allow_html=True)
    elif not alldata:
        if offset == 0:
            st.info("No results in the database yet.")
        else:
            st.info("No more results.")
            st.session_state.all_results_offset = 0
            st.rerun()
    else:
        def _to_rdtii_id(pillar_id, indicator_id):
            parts = str(indicator_id).split(".")
            suffix = ".".join(parts[1:]) if len(parts) > 1 else parts[0]
            return f"P{pillar_id}-I{suffix}"

        st.caption(f"Showing {offset + 1}–{offset + len(alldata)}")
        rows = []
        for r_ in alldata:
            citation = (r_.get("article_citation") or "")
            law_ref = citation.split(",")[0].strip() if citation else ""
            rows.append({
                "ID": r_["id"],
                "Economy": r_["country"],
                "Law Name": r_.get("act_and_practice") or "—",
                "Law Number / Ref": law_ref or "—",
                "Coverage": r_.get("coverage") or "N/A",
                "Indicator ID": _to_rdtii_id(r_.get("pillar_id"), r_.get("indicator_id")),
                "Article / Section": r_.get("article_citation") or "—",
                "Discovery Tag": r_.get("discovery_tag") or "NEW",
                "Verbatim Snippet": (r_.get("verbatim_quote") or "—")[:100],
                "Source URL": r_.get("references") or "—",
                "Score": r_.get("raw_score"),
                "Confidence": f'{r_["confidence"]:.2f}' if r_.get("confidence") is not None else "",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
    st.stop()

if page == "Review Queue":
    st.subheader("Review Queue")
    qdata, qerr = _get("/api/v1/analysis/review/queue?limit=50")
    if qerr:
        st.markdown(f'<div class="error-box">{qerr}</div>', unsafe_allow_html=True)
    elif not qdata:
        st.info("No items in review queue.")
    else:
        for item in qdata:
            sc = f"{item['raw_score']:.2f}" if item.get("raw_score") is not None else "—"
            tag = item.get("discovery_tag", "NEW")
            tag_pill = "pill-info" if tag == "KNOWN" else "pill-warn"
            rid = item.get("result_id", "?")
            st.markdown(
                f'<div class="card">'
                f'<div><b>{item["indicator_id"]}</b> · {item["country"]} · <span class="pill-ok">{sc}</span> · <span class="{tag_pill}">{tag}</span> · <code style="font-size:0.75rem;">ID: {rid}</code></div>'
                f'<div style="margin-top:4px;color:#a1aab5;font-size:0.85rem;">{item.get("reason","")}</div>'
                f'<div style="margin-top:6px;font-size:0.85rem;">{item.get("impact_comments","")[:120]}</div>'
                + (f'<div style="margin-top:4px;font-style:italic;background:#0d1117;padding:6px 8px;border-radius:4px;font-size:0.8rem;">{item["verbatim_quote"][:200]}</div>' if item.get("verbatim_quote") else "") +
                f'</div>', unsafe_allow_html=True)
    st.stop()

if page == "Audit View":
    st.subheader("Audit View")
    aid = st.text_input("Enter Indicator Result ID to audit:", placeholder="e.g. 1")
    if aid and aid.isdigit():
        adata, aerr = _get(f"/api/v1/analysis/audit/{aid}")
        if aerr:
            st.markdown(f'<div class="error-box">{aerr}</div>', unsafe_allow_html=True)
        elif adata:
            dt = adata.get("discovery_tag", "NEW")
            dt_pill = "pill-info" if dt == "KNOWN" else "pill-warn"
            st.markdown(f'**Result ID:** {adata["result_id"]}  |  **Indicator:** {adata["indicator_id"]}  |  **Country:** {adata["country"]}  |  **Score:** {adata["raw_score"]}  |  <span class="{dt_pill}">{dt}</span>', unsafe_allow_html=True)
            st.markdown(f'**Act/Practice:** {adata.get("act_and_practice","—")}')
            st.markdown(f'**Citation:** `{adata.get("article_citation","—")}`')
            st.markdown(f'**Verbatim Quote:**<div style="background:#0d1117;padding:10px;border-radius:6px;font-style:italic;">{adata.get("verbatim_quote","—")}</div>', unsafe_allow_html=True)
            st.markdown(f'**References:** {adata.get("references","—")}')
            for d in adata.get("source_documents", []):
                st.markdown(f'- `{d.get("source_type","?")}` {d["url"]}  _cer={d.get("ocr_quality_cer",0)}_', unsafe_allow_html=True)
    st.stop()

# ── Header ────────────────────────────────────────────────────────────────────

health, health_err = _get("/health")

if health_err:
    st.markdown(f'<div class="error-box">API Unreachable — {health_err}</div>', unsafe_allow_html=True)
    st.stop()

overall = health.get("status", "unknown")
overall_pill = ("pill-ok" if overall == "ok" else "pill-warn" if overall == "degraded" else "pill-error")
overall_text = "System OK" if overall == "ok" else overall.upper()
ts = health.get("timestamp", "")
ts_str = f"{ts[:19].replace('T', ' ')} UTC" if ts else ""
now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S') + " UTC"

st.markdown(
    f'<div style="display:flex;align-items:center;gap:14px;padding:16px;background:rgba(22,27,34,0.5);border:1px solid rgba(255,255,255,0.05);border-radius:12px;margin-bottom:24px;backdrop-filter:blur(10px);box-shadow:0 4px 20px rgba(0,0,0,0.1);">'
    f'<span style="font-size:1.2rem;font-weight:600;color:#f0f2f5;letter-spacing:-0.02em;">System Status</span>'
    f'<span class="{overall_pill}">{overall_text}</span>'
    f'<span style="color:#a1aab5;font-size:0.85rem;margin-left:10px;">v{health.get("version", "N/A")}</span>'
    f'<span style="color:#a1aab5;font-size:0.85rem;margin-left:auto;">{now_str}</span>'
    f'</div>',
    unsafe_allow_html=True,
)

# ── Submit New Analysis ───────────────────────────────────────────────────────

st.subheader("New Analysis")

PILLAR_OPTIONS = {
    1: "Tariffs & Trade Defence", 2: "Public Procurement", 3: "Foreign Direct Investment",
    4: "Intellectual Property Rights", 5: "Telecom & Competition", 6: "Cross-border Data",
    7: "Data Protection & Privacy", 8: "Intermediary Liability", 9: "Content Access",
    10: "Non-technical NTMs", 11: "Standards & Procedures", 12: "Online Sales & Transactions",
}

@st.cache_data(ttl=300)
def _fetch_indicators():
    data, err = _get("/api/v1/analysis/indicators")
    return data if data else [], err

all_indicators, ind_err = _fetch_indicators()
if ind_err:
    st.markdown(f'<div class="error-box">Could not load indicators: {ind_err}</div>', unsafe_allow_html=True)
    all_indicators = []

# Reactive selectors (outside form so pillar changes update indicator list immediately)
c1, c2, c3 = st.columns(3)
with c1:
    country = st.selectbox("Country", ["", "Singapore", "Malaysia", "Australia"],
                           format_func=lambda x: "Select..." if x == "" else x)
with c2:
    pillars = st.multiselect("Pillars", options=list(PILLAR_OPTIONS.keys()),
                              format_func=lambda x: f"{x} — {PILLAR_OPTIONS[x]}", placeholder="All")
with c3:
    model = st.selectbox("LLM", ["auto", "minimax", "nvidia", "gemini", "openai", "grok", "deepseek", "ollama"],
        format_func=lambda x: {"auto": "Auto", "minimax": "MiniMax-M3 (Free)", "nvidia": "Nvidia Nemotron Free",
                               "gemini": "Gemini", "openai": "OpenAI",
                               "grok": "Grok (xAI)", "deepseek": "DeepSeek", "ollama": "Ollama"}[x])

# Filter indicators by selected pillars
if all_indicators:
    if pillars:
        filtered = [ind for ind in all_indicators if ind["pillar_id"] in pillars]
    else:
        filtered = all_indicators
    indicator_options = {ind["id"]: f'{ind["id"]} — {ind["title"]}' for ind in filtered}
    selected_indicators = st.multiselect(
        "Indicators (optional — leave empty for all in selected pillars)",
        options=list(indicator_options.keys()),
        format_func=lambda x: indicator_options.get(x, x),
        placeholder="All indicators",
    )
else:
    selected_indicators = []

with st.form("new_analysis_form"):
    if st.form_submit_button("Submit", use_container_width=True, type="primary"):
        if not country:
            st.markdown('<span class="pill-error">Select a country</span>', unsafe_allow_html=True)
        else:
            payload = {"country": country, "llm_provider": model}
            if selected_indicators:
                payload["indicator_ids"] = selected_indicators
            elif pillars:
                payload["pillar_ids"] = pillars
            for attempt in range(3):
                try:
                    r = requests.post(f"{API_BASE}/api/v1/analysis/run", json=payload, timeout=15)
                    if r.status_code in (200, 202):
                        st.markdown(f'<span class="pill-ok">Queued for {country}</span>', unsafe_allow_html=True)
                        time.sleep(1.5)
                        st.rerun()
                        break
                    else:
                        st.markdown(f'<div class="error-box">{r.text}</div>')
                        break
                except Exception as e:
                    if attempt < 2:
                        time.sleep(2)
                        continue
                    st.markdown(f'<div class="error-box">{e}</div>')

st.divider()

# ── Health ────────────────────────────────────────────────────────────────────

st.subheader("Services")

services = health.get("services", {})
queue = health.get("queue", {})
llm_info = health.get("llm", {})

cols = st.columns(4)
for i, (label, val) in enumerate([
    ("PostgreSQL", "Connected" if services.get("database") == "ok" else "Error"),
    ("Redis", "Connected" if services.get("redis") == "ok" else "Error"),
    ("Workers", f'{queue.get("workers_online", 0)} online'),
    ("Queue", queue.get("celery_queue_depth", 0)),
]):
    with cols[i]:
        st.markdown(f'<div class="card"><div class="card-label">{label}</div><div class="card-value">{val}</div></div>',
                    unsafe_allow_html=True)

st.subheader("LLM Providers")

gem = llm_info.get("gemini", {}); oai = llm_info.get("openai", {})
grk = llm_info.get("grok", {}); dsk = llm_info.get("deepseek", {})
mmx = llm_info.get("minimax", {}); nvd = llm_info.get("nvidia", {})
oll = llm_info.get("ollama", {})

def _llm_html(name, info):
    ok = info.get("status") == "ok"
    ks = info.get("api_key_set", False)
    cls = "pill-ok" if ok else ("pill-error" if ks else "pill-info")
    label = f"{name} OK" if ok else (f"{name} Failed" if ks else name)
    msg = info.get("message", "")[:45] or info.get("base_url", "")[:45] or ""
    extra = f'<div style="font-size:0.7rem;color:#8b949e;margin-top:4px;">{msg}</div>' if msg else ""
    return f'<div><span class="{cls}">{label}</span>{extra}</div>'

lc = st.columns(8)
with lc[0]: st.markdown(_llm_html("Gemini", gem), unsafe_allow_html=True)
with lc[1]: st.markdown(_llm_html("OpenAI", oai), unsafe_allow_html=True)
with lc[2]: st.markdown(_llm_html("Grok", grk), unsafe_allow_html=True)
with lc[3]: st.markdown(_llm_html("DeepSeek", dsk), unsafe_allow_html=True)
with lc[4]: st.markdown(_llm_html("MiniMax-M3", mmx), unsafe_allow_html=True)
with lc[5]: st.markdown(_llm_html("Nvidia Free", nvd), unsafe_allow_html=True)
with lc[6]: st.markdown(_llm_html("Ollama", oll), unsafe_allow_html=True)

st.caption(f"Default: {llm_info.get('active', 'auto')}")

st.divider()

# ── Runs ──────────────────────────────────────────────────────────────────────

st.subheader("Analysis Runs")

RUNS_PAGE_SIZE = 10
if "runs_offset" not in st.session_state:
    st.session_state.runs_offset = 0

runs, err = _get("/api/v1/analysis/runs?limit=100")
if err:
    st.markdown(f'<div class="error-box">{err}</div>', unsafe_allow_html=True)
elif not runs:
    st.info("No runs yet.")
else:
    total = len(runs)
    done = sum(1 for r in runs if r["status"] == "COMPLETE")
    failed = sum(1 for r in runs if r["status"] == "FAILED")
    queued = sum(1 for r in runs if r["status"] == "QUEUED")
    running = sum(1 for r in runs if r["status"] in ("DISCOVERING", "ANALYSING", "RUNNING"))

    cols = st.columns(5)
    for i, (l, v) in enumerate([("Total", total), ("Complete", done), ("Failed", failed), ("Queued", queued), ("Active", running)]):
        with cols[i]:
            st.markdown(f'<div class="card"><div class="card-label">{l}</div><div class="card-value">{v}</div></div>',
                        unsafe_allow_html=True)

    st.markdown("---")

    offset = st.session_state.runs_offset
    page_runs = runs[offset:offset + RUNS_PAGE_SIZE]

    rp_prev, rp_info, rp_next = st.columns([1, 6, 1])
    with rp_prev:
        if st.button("← Previous", key="rp_prev", disabled=(offset == 0)):
            st.session_state.runs_offset = max(0, offset - RUNS_PAGE_SIZE)
            st.rerun()
    with rp_info:
        st.caption(f"Showing {offset + 1}–{min(offset + RUNS_PAGE_SIZE, total)} of {total}")
    with rp_next:
        if st.button("Next →", key="rp_next", disabled=(offset + RUNS_PAGE_SIZE >= total)):
            st.session_state.runs_offset += RUNS_PAGE_SIZE
            st.rerun()

    for run in page_runs:
        s = run["status"]
        country_name = run["country"]
        rid = run["id"]
        em = run.get("error_message")

        style = STATUS_STYLE.get(s, "pill-info")
        label = f"{country_name} — {rid[:8]}..."

        with st.expander(label, expanded=(s == "FAILED")):
            st.markdown(f'<span class="{style}">{s}</span>', unsafe_allow_html=True)
            st.markdown('<div class="metric-row">', unsafe_allow_html=True)
            mc = st.columns(4)
            with mc[0]:
                st.markdown(f'<div class="metric-item"><div class="lbl">Country</div><div class="val">{country_name}</div></div>', unsafe_allow_html=True)
            with mc[1]:
                st.markdown(f'<div class="metric-item"><div class="lbl">Status</div><div class="val">{s}</div></div>', unsafe_allow_html=True)
            with mc[2]:
                st.markdown(f'<div class="metric-item"><div class="lbl">Indicators</div><div class="val">{run.get("completed_indicators",0)}/{run.get("total_indicators",0)}</div></div>', unsafe_allow_html=True)
            with mc[3]:
                created = run.get("created_at", "")[:19].replace("T", " ")
                st.markdown(f'<div class="metric-item"><div class="lbl">Started</div><div class="val">{created}</div></div>', unsafe_allow_html=True)

            prov = run.get("llm_provider") or "auto"
            st.caption(f"Model: {prov}")

            if s in ("DISCOVERING", "ANALYSING"):
                ti = run.get("total_indicators", 1) or 1
                di = run.get("completed_indicators", 0)
                st.progress(min(di / ti, 1), text=f"{di}/{ti}")
                act = run.get("current_activity")
                if act:
                    st.caption(act)

                events, ev_err = _get(f"/api/v1/analysis/{rid}/events?offset=0&limit=30")
                if events and events.get("events"):
                    st.markdown("**Live Activity Log**")
                    log_lines = []
                    for ev in events["events"]:
                        ts = ev.get("created_at", "")[11:19]
                        agent = ev.get("agent") or ""
                        ind = ev.get("indicator_id") or ""
                        msg = ev.get("message", "")
                        tag = ev["event_type"].replace("_DONE", "").replace("_START", "")
                        icon = {"SEARCH": "[S]", "CLASSIFY": "[C]", "DOWNLOAD": "[D]",
                                "ZONE1": "[V]", "CHUNK": "[K]", "EMBED": "[E]",
                                "PROSECUTION": "[P]", "DEFENSE": "[D]", "ARBITER": "[A]",
                                "INDICATOR": "[I]", "STATUS": "[!]", "ERROR": "[X]"}.get(tag, "")
                        log_lines.append(
                            f'<div style="font-family:monospace;font-size:0.78rem;'
                            f'color:#e1e4e8;padding:1px 0;">'
                            f'<span style="color:#8b949e;">{ts}</span> '
                            f'{icon} '
                            f'<span style="color:#58a6ff;">{agent}</span> '
                            f'<span style="color:#d29922;">{ind}</span> '
                            f'{msg[:120]}'
                            f'</div>'
                        )
                    st.markdown(
                        f'<div style="background:#0d1117;border:1px solid #21262d;'
                        f'border-radius:6px;padding:8px 12px;max-height:280px;'
                        f'overflow-y:auto;font-family:monospace;">'
                        + "".join(log_lines) +
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                elif ev_err:
                    st.caption(f"Events error: {ev_err}")
            elif s == "QUEUED":
                st.markdown('<span style="color:#8b949e;">Waiting in queue.</span>', unsafe_allow_html=True)

            if s == "FAILED" and em:
                st.markdown(f'<div class="error-box">{em}</div>', unsafe_allow_html=True)

            if s == "COMPLETE":
                base = f"{EXPORT_BASE}/api/v1/analysis/{rid}/export"
                st.markdown(f'**Export:** <a href="{base}?format=json" target="_blank">JSON</a> | '
                            f'<a href="{base}?format=csv" target="_blank">CSV (RDTII Template)</a> | '
                            f'<a href="{base}?format=rdtii_flat_csv" target="_blank">CSV (Flat 9-col)</a> | '
                            f'<a href="{base}?format=submission_csv" target="_blank">CSV (Submission)</a> | '
                            f'<a href="{base}?format=excel" target="_blank">Excel (3 sheets)</a>', unsafe_allow_html=True)

                det, det_err = _get(f"/api/v1/analysis/{rid}")
                if det_err:
                    st.caption(f"Error: {det_err}")
                elif inds := det.get("indicator_results", []):
                    def _to_rdtii_id(pillar_id, indicator_id):
                        parts = str(indicator_id).split(".")
                        suffix = ".".join(parts[1:]) if len(parts) > 1 else parts[0]
                        return f"P{pillar_id}-I{suffix}"
                    country = det.get("country", "")
                    rows = []
                    for r_ in inds:
                        citation = (r_.get("article_citation") or "")
                        law_ref = citation.split(",")[0].strip() if citation else ""
                        rows.append({
                            "ID": r_["id"],
                            "Economy": country,
                            "Law Name": r_.get("act_and_practice") or "—",
                            "Law Number / Ref": law_ref or "—",
                            "Coverage": r_.get("coverage") or "N/A",
                            "Last Amended": r_.get("timeframe") or "",
                            "Indicator ID": _to_rdtii_id(r_.get("pillar_id"), r_.get("indicator_id")),
                            "Article / Section": r_.get("article_citation") or "—",
                            "Discovery Tag": r_.get("discovery_tag") or "NEW",
                            "Location Reference": r_.get("location_ref") or "",
                            "Verbatim Snippet": (r_.get("verbatim_quote") or "—")[:120],
                            "Mapping Rationale": ((r_.get("mapping_rationale") or r_.get("impact_comments") or "")[:200]),
                            "Source URL": r_.get("references") or "—",
                            "Confidence": f"{r_['confidence']:.2f}" if r_.get("confidence") is not None else "",
                            "Notes": r_.get("note") or "",
                        })
                    st.dataframe(rows, use_container_width=True, hide_index=True)

            dc, ic = st.columns([1, 4])
            with dc:
                if st.button("Delete", key=f"d_{rid}"):
                    for attempt in range(3):
                        try:
                            r_ = requests.delete(f"{API_BASE}/api/v1/analysis/{rid}", timeout=10)
                            if r_.status_code == 204:
                                st.success("Deleted"); time.sleep(1); st.rerun()
                                break
                            else:
                                st.error(r_.text)
                                break
                        except Exception as e:
                            if attempt < 2:
                                time.sleep(2)
                                continue
                            st.error(str(e))
            with ic:
                st.caption(f"`{rid}`")

st.divider()
st.caption("RDTII 2.1 Compliance Engine  |  Team SUPERNOVA  |  UNESCAP Global Hackathon 2026")
