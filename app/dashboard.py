"""Camera-friendly Streamlit demo for the FastAPI revenue recovery service."""

from collections import Counter

import pandas as pd
import requests
import streamlit as st


BACKEND_URL = "http://localhost:8000"
AUDIT_COLUMNS = [
    "event_id", "event_type", "root_cause", "confidence", "policy_decision",
    "policy_reason", "action_taken", "outcome",
]
AI_COMPONENTS = pd.DataFrame([
    {"Component": "ai_classify_root_cause", "Why AI": "Free-text gateway reasons require semantic classification."},
    {"Component": "ai_generate_nudge", "Why AI": "Copy needs natural, locale-aware customer language."},
    {"Component": "ai_classify_reply_intent", "Why AI": "Short natural-language and Hinglish replies resist keyword rules."},
    {"Component": "ai_judge_nudge_quality", "Why AI": "Compliance, clarity, and tone are contextual language judgments."},
])
DETERMINISTIC_RULES = pd.DataFrame([
    {"Deterministic control": "Retry limits", "Why rules": "Money exposure must have hard, auditable bounds."},
    {"Deterministic control": "Cooldown and promise timing", "Why rules": "Scheduling cannot be improvised by model discretion."},
    {"Deterministic control": "Amount ceilings", "Why rules": "Large-value actions require escalation regardless of model output."},
    {"Deterministic control": "Final action decision", "Why rules": "Policy owns retry, nudge, switch, escalate, close, and await-promise."},
])
HTTP_SESSION = requests.Session()


def _get(path: str):
    """Fetch backend data while keeping the demo usable when the server is down."""
    try:
        response = HTTP_SESSION.get(f"{BACKEND_URL}{path}", timeout=3)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        st.warning(f"Backend unavailable: {exc}. Start FastAPI at {BACKEND_URL}.")
        return None


def _post(path: str):
    """Trigger one backend operation and surface failures clearly to the operator."""
    try:
        response = HTTP_SESSION.post(f"{BACKEND_URL}{path}", timeout=120)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        st.error(f"Request failed: {exc}")
        return None


def _percent(value) -> str:
    """Format backend ratios as readable percentages without crashing on missing metrics."""
    return f"{float(value or 0) * 100:.1f}%"


@st.cache_data(ttl=2, show_spinner=False)
def load_dashboard_data() -> tuple[dict, list[dict]]:
    """Share short-lived dashboard reads across Streamlit reruns and tabs."""
    return _get("/metrics") or {}, _get("/audit-log") or []


@st.cache_data(ttl=5, show_spinner=False)
def load_baseline_comparison() -> dict:
    """Cache the heavier comparison endpoint while the operator explores the tab."""
    return _get("/baseline-comparison") or {}


def _audit_frame(audit: list[dict]) -> pd.DataFrame:
    """Normalize audit records so sparse fallback records still render in the table."""
    frame = pd.DataFrame(audit)
    for column in AUDIT_COLUMNS:
        if column not in frame:
            frame[column] = ""
    return frame[AUDIT_COLUMNS]


def _show_detail(event_id: str, audit: list[dict]) -> None:
    """Show the evidence a reviewer needs to connect model judgment to policy action."""
    record = next((item for item in audit if item.get("event_id") == event_id), None)
    if not record:
        st.info("Enter an event ID above to inspect its full reasoning.")
        return
    with st.expander(f"Full reasoning: {event_id}", expanded=True):
        left, right = st.columns(2)
        with left:
            st.write("**Raw failure text**", record.get("failure_reason_raw", "Not returned by current API"))
            st.write("**Classification reasoning**", record.get("classification_reasoning", "Not returned by current API"))
            st.write("**Policy reason**", record.get("policy_reason", "Not available"))
        with right:
            st.write("**Generated nudge**", record.get("nudge_content", "No nudge generated"))
            st.write("**AI components**", ", ".join(record.get("ai_components", [])) or "No AI component metadata")
            trace_url = record.get("langfuse_trace_url")
            st.write("**Langfuse**", trace_url or "Trace URL not returned by current API")


def main() -> None:
    """Render the single-page demo so the recovery loop is legible during a video."""
    st.set_page_config(page_title="Revenue Recovery Agent", page_icon="₹", layout="wide", initial_sidebar_state="collapsed")
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
        :root { --ink:#102331; --muted:#657681; --line:#dce5e7; --paper:#f6f9f8; --teal:#087f78; --teal-soft:#dff2ee; --coral:#e76f51; }
        .stApp { background:var(--paper); color:var(--ink); }
        [data-testid="stHeader"] { background:rgba(246,249,248,.92); }
        [data-testid="stAppViewContainer"] > .main { padding-top:1.5rem; }
        .block-container { max-width:1440px; padding:2rem 3rem 4rem; }
        h1,h2,h3 { font-family:'Space Grotesk',sans-serif !important; color:var(--ink) !important; letter-spacing:0 !important; }
        p, label, .stCaption, .stMetric { font-family:'DM Sans',sans-serif; }
        h1 { font-size:2.25rem !important; line-height:1.08 !important; margin:0 !important; }
        h2 { font-size:1.25rem !important; margin-top:1rem !important; }
        h3 { font-size:1rem !important; }
        .hero { display:flex; justify-content:space-between; align-items:flex-end; gap:2rem; background:linear-gradient(118deg,#102f3b 0%,#14535b 68%,#087f78 100%); color:white; border-radius:16px; padding:2.1rem 2.25rem; margin-bottom:1.25rem; box-shadow:0 12px 30px rgba(16,35,49,.14); }
        .hero h1 { color:white !important; max-width:720px; }
        .hero p { color:#cde4e1; margin:.65rem 0 0; font-size:1.02rem; }
        .hero-mark { width:72px; height:72px; border:1px solid rgba(255,255,255,.34); border-radius:50%; display:grid; place-items:center; color:#ffb49d; font:700 2rem 'Space Grotesk'; flex:none; }
        .section-kicker { color:var(--teal); text-transform:uppercase; letter-spacing:.12em; font:700 .7rem 'DM Sans'; margin:1.25rem 0 .3rem; }
        .status { display:inline-flex; align-items:center; gap:.45rem; color:#d7f4e9; font:600 .78rem 'DM Sans'; margin-top:1.1rem; }
        .status-dot { width:8px; height:8px; border-radius:50%; background:#58d68d; box-shadow:0 0 0 4px rgba(88,214,141,.16); }
        [data-testid="stMetric"] { background:white; border:1px solid var(--line); border-radius:12px; padding:1rem 1.05rem; box-shadow:0 3px 12px rgba(16,35,49,.045); min-height:108px; }
        [data-testid="stMetricLabel"] p { color:var(--muted) !important; font-size:.78rem !important; font-weight:600; }
        [data-testid="stMetricValue"] { color:var(--ink) !important; font-family:'Space Grotesk',sans-serif; font-size:1.45rem !important; }
        .primary-metric [data-testid="stMetric"] { border:2px solid var(--teal); background:var(--teal-soft); min-height:124px; }
        .primary-metric [data-testid="stMetricValue"] { color:var(--teal) !important; font-size:1.85rem !important; }
        .primary-caption { color:#3d6866; font:500 .7rem 'DM Sans'; line-height:1.35; margin-top:-.55rem; padding:0 .1rem; }
        .stButton > button { background:var(--coral); color:white; border:0; border-radius:9px; font:700 .88rem 'DM Sans'; padding:.65rem 1.15rem; box-shadow:0 5px 14px rgba(231,111,81,.25); }
        .stButton > button:hover { background:#d85f43; color:white; border:0; }
        button[role="tab"] { font:600 .86rem 'DM Sans'; color:var(--muted); padding:1rem .9rem; }
        button[role="tab"][aria-selected="true"] { color:var(--teal); }
        [data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:10px; overflow:hidden; }
        .info-strip { background:#fff; border:1px solid var(--line); border-left:4px solid var(--coral); border-radius:10px; padding:.85rem 1rem; color:#405661; font:.85rem 'DM Sans'; }
        @media (max-width:800px) { .block-container { padding:1rem 1rem 3rem; } .hero { padding:1.4rem; } .hero-mark { display:none; } h1 { font-size:1.7rem !important; } }
        </style>
    """, unsafe_allow_html=True)
    st.markdown("""
        <div class="hero">
            <div><div class="section-kicker" style="color:#ffb49d;margin:0 0 .55rem">RAZORPAY AI BUILDATHON · TRACK 3</div>
            <h1>Revenue Recovery Agent</h1><p>Payment failures → subscriptions → mandates, one policy engine</p>
            <div class="status"><span class="status-dot"></span> Recovery control room · FastAPI connected</div></div>
            <div class="hero-mark">₹</div>
        </div>
    """, unsafe_allow_html=True)
    action_col, refresh_col = st.columns([1, 5])
    with action_col:
        run_batch = st.button("Run Batch", type="primary", use_container_width=True)
    with refresh_col:
        st.markdown('<div class="info-strip">Decision quality is the north-star metric. Every retry, ceiling, and final action remains deterministic.</div>', unsafe_allow_html=True)
    if run_batch:
        with st.spinner("Running recovery graph across payment, subscription, and mandate events..."):
            result = _post("/run-batch")
        if result is not None:
            st.success(f"Processed {result.get('processed', 0)} events")
            st.rerun()

    metrics, audit = load_dashboard_data()
    tabs = st.tabs(["Overview / Metrics", "Event-by-Event Audit Trail", "AI vs Rules Breakdown", "Naive vs Policy Engine", "System Notes"])

    with tabs[0]:
        st.markdown('<div class="section-kicker">OPERATING SNAPSHOT</div>', unsafe_allow_html=True)
        st.subheader("Batch health")
        metric_columns = st.columns(5)
        metric_columns[0].metric("Recovery Rate", _percent(metrics.get("recovery_rate")))
        with metric_columns[1]:
            st.markdown('<div class="primary-metric">', unsafe_allow_html=True)
            st.metric("Decision Quality", _percent(metrics.get("decision_quality", 0)))
            st.markdown('<div class="primary-caption">% of decisions respecting stop conditions and confidence thresholds, independent of outcome</div></div>', unsafe_allow_html=True)
        metric_columns[2].metric("Total Amount Recovered", f"₹{metrics.get('total_amount_recovered', 0):,.2f}")
        metric_columns[3].metric("Avg Tokens / Event", f"{metrics.get('avg_tokens_per_event', 0):,.1f}")
        metric_columns[4].metric("Promise Kept Rate", _percent(metrics.get("promise_kept_rate")))
        outcomes = Counter(row.get("outcome", "pending") for row in audit)
        chart = pd.DataFrame({"events": [outcomes.get(name, 0) for name in ["recovered", "escalated", "closed", "pending", "awaiting promise"]]}, index=["recovered", "escalated", "closed", "pending", "awaiting promise"])
        st.markdown('<div class="section-kicker">PORTFOLIO FLOW</div>', unsafe_allow_html=True)
        st.subheader("Outcome distribution")
        st.bar_chart(chart)
        st.caption(f"AI calls per event: {metrics.get('ai_calls_per_event', 0):.2f}  ·  Total tokens: {metrics.get('total_tokens', 0):,}  ·  AI latency: {metrics.get('ai_latency_ms', 0):,.1f} ms")

    with tabs[1]:
        st.markdown('<div class="section-kicker">AUDITABLE OPERATIONS</div>', unsafe_allow_html=True)
        st.subheader("Auditable decisions")
        all_events = sorted({row.get("event_type", "") for row in audit if row.get("event_type")})
        all_outcomes = sorted({row.get("outcome", "") for row in audit if row.get("outcome")})
        filter_columns = st.columns([1, 1, 2])
        event_filter = filter_columns[0].selectbox("Event type", ["All"] + all_events)
        outcome_filter = filter_columns[1].selectbox("Outcome", ["All"] + all_outcomes)
        search = filter_columns[2].text_input("Search event ID", placeholder="evt_001")
        filtered = [row for row in audit if (event_filter == "All" or row.get("event_type") == event_filter) and (outcome_filter == "All" or row.get("outcome") == outcome_filter) and (not search or search.lower() in row.get("event_id", "").lower())]
        st.dataframe(_audit_frame(filtered), use_container_width=True, hide_index=True)
        selected_id = st.text_input("Inspect event ID", value=search, placeholder="evt_001")
        _show_detail(selected_id, audit)

    with tabs[2]:
        st.markdown('<div class="section-kicker">MODEL GOVERNANCE</div>', unsafe_allow_html=True)
        st.subheader("Judgment is AI. Money decisions are code.")
        st.dataframe(AI_COMPONENTS, use_container_width=True, hide_index=True)
        st.subheader("Deterministic policy.py controls")
        st.dataframe(DETERMINISTIC_RULES, use_container_width=True, hide_index=True)
        st.info("The dashboard shows AI calls as measured events. It does not add calls merely to make the numbers look larger.")

    with tabs[3]:
        st.markdown('<div class="section-kicker">COUNTERFACTUAL EVALUATION</div>', unsafe_allow_html=True)
        st.subheader("Same events, two recovery approaches")
        comparison = load_baseline_comparison()
        naive = comparison.get("naive", {})
        policy = comparison.get("policy_engine", {})
        comparison_columns = st.columns(2)
        for column, label, values in [(comparison_columns[0], "Naive baseline", naive), (comparison_columns[1], "Policy engine", policy)]:
            with column:
                st.markdown(f"### {label}")
                st.metric("Recovery rate", _percent(values.get("recovery_rate")))
                st.metric("Amount recovered", f"₹{values.get('amount_recovered', 0) / 100:,.2f}")
                st.metric("False retries", values.get("false_retry_count", 0))
                st.metric("Compliance violations", values.get("compliance_violations", 0))
        amount_delta = comparison.get("delta_amount_recovered", 0) / 100
        violation_delta = comparison.get("delta_compliance_violations", 0)
        st.success(f"Policy engine recovered ₹{amount_delta:,.2f} more while committing {violation_delta} fewer compliance violations.")
        chart = pd.DataFrame({"Naive baseline": [naive.get("recovery_rate", 0) * 100, naive.get("amount_recovered", 0) / 100, naive.get("false_retry_count", 0), naive.get("compliance_violations", 0)], "Policy engine": [policy.get("recovery_rate", 0) * 100, policy.get("amount_recovered", 0) / 100, policy.get("false_retry_count", 0), policy.get("compliance_violations", 0)]}, index=["Recovery rate (%)", "Amount recovered (₹)", "False retries", "Compliance violations"])
        st.bar_chart(chart)

    with tabs[4]:
        st.markdown('<div class="section-kicker">DEMO CONFIGURATION</div>', unsafe_allow_html=True)
        st.subheader("Demo setup")
        st.write("FastAPI backend: ", BACKEND_URL)
        st.write("Use the Run Batch button to process the synthetic 40 payment, 20 subscription, and 10 mandate failure events.")
        st.write("MongoDB and provider failures fall back to conservative escalation and local audit evidence.")


if __name__ == "__main__":
    main()
