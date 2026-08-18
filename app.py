"""
Wi-Fi Band Analyzer — Modernized Dashboard
-------------------------------------------
Drop this into src/app.py (same folder as diagnostic_engine.py and
synthetic_generator.py). Does NOT modify either of those files.
 
Run with:
    streamlit run app.py
"""
 
import os
import sys
import time
import random
import io
from datetime import datetime
 
import pandas as pd
import altair as alt
import plotly.graph_objects as go
import streamlit as st
 
sys.path.append(os.path.dirname(__file__))
 
from synthetic_generator import generate, DEVICE_PROFILES  # noqa: E402
from diagnostic_engine import smooth, classify, reset_state  # noqa: E402
from data_source import get_devices  # noqa: E402
import active_probe  # noqa: E402
 
try:
    from wifi_standards import get_max_rate
except Exception:  # pragma: no cover - optional, safe no-op if not present
    get_max_rate = None
 
# ----------------------------------------------------------------------------
# Page config + styling
# ----------------------------------------------------------------------------
 
st.set_page_config(
    page_title="Wi-Fi Band Analyzer",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)
 
st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem; }
    div[data-testid="stMetric"] {
        background: #12161c;
        border: 1px solid #262b33;
        border-radius: 10px;
        padding: 12px 16px;
    }
    div[data-testid="stMetricLabel"] { font-size: 0.8rem; opacity: 0.75; }
    .badge {
        display: inline-block; padding: 2px 10px; border-radius: 999px;
        font-size: 0.78rem; font-weight: 600; color: white;
    }
    .card {
        background: #12161c; border: 1px solid #262b33; border-radius: 10px;
        padding: 14px 16px; margin-bottom: 10px;
    }
    .small-muted { opacity: 0.65; font-size: 0.82rem; }
    </style>
    """,
    unsafe_allow_html=True,
)
 
CATEGORY_COLORS = {
    "Optimal": "#22c55e",
    "Hardware Limited": "#eab308",
    "Far Distance": "#f97316",
    "Attenuated Signal": "#ef4444",
    "Congestion": "#a855f7",
    "Device-Specific Issue": "#3b82f6",
    "Signal Critically Weak": "#7f1d1d",
    "Insufficient Information": "#6b7280",
}
 
SEVERITY = {
    "Optimal": 0,
    "Hardware Limited": 1,
    "Device-Specific Issue": 1,
    "Far Distance": 1,
    "Congestion": 2,
    "Attenuated Signal": 2,
    "Signal Critically Weak": 3,
    "Insufficient Information": 1,
}
 
RECOMMENDATIONS = {
    "Optimal": "No action required — connection is healthy.",
    "Hardware Limited": "Client radio can't keep up with current conditions. "
                         "Check the device's Wi-Fi chipset/driver and consider a firmware update.",
    "Far Distance": "Move the device closer to the access point, or add a mesh "
                     "node / extender to improve coverage in that area.",
    "Attenuated Signal": "Signal is being blocked (walls, metal, distance). "
                          "Reposition the AP or device, or remove obstructions.",
    "Congestion": "Channel is busy. Switch to a less-congested channel or "
                  "move the device to a quieter band (5/6 GHz).",
    "Device-Specific Issue": "Behavior is isolated to this device. Try a "
                              "reboot, driver/firmware update, or re-pairing.",
    "Signal Critically Weak": "Signal is near the noise floor — connection may drop. "
                               "Relocate the AP/device immediately or add coverage.",
    "Insufficient Information": "Not enough stable telemetry yet — keep "
                                 "monitoring before taking action.",
}
 
NETWORK_MAX_STANDARD = "wifi6e"
 
 
def badge(label: str) -> str:
    color = CATEGORY_COLORS.get(label, "#6b7280")
    return f'<span class="badge" style="background:{color}">{label}</span>'
 
 
def freq_for_band(band) -> int:
    """Map a device's band string to a representative frequency in MHz,
    so classify() gets a realistic freq_mhz instead of always defaulting."""
    band = str(band).lower()
    if "6" in band:
        return 6000
    if "2.4" in band or band.startswith("2"):
        return 2400
    return 5000
 
 
# ----------------------------------------------------------------------------
# Session state (persistent devices — do NOT regenerate randomly every loop)
# ----------------------------------------------------------------------------
 
def _init_device(device_id: str, profile: str) -> dict:
    d = generate(device_id, profile)
    d["profile"] = profile
    d["channel"] = random.choice([1, 6, 11]) if d["band"] == "2.4GHz" else random.choice([36, 40, 44, 149, 153])
    if get_max_rate:
        max_rate = get_max_rate(d.get("standard"))
        if max_rate:
            d["phy_rate"] = round(max_rate * random.uniform(0.55, 0.95), 1)
    return d
 
 
if "devices" not in st.session_state:
    profiles = list(DEVICE_PROFILES.keys())
    st.session_state.devices = [
        _init_device(f"dev{i}", profiles[i % len(profiles)]) for i in range(8)
    ]
 
if "event_log" not in st.session_state:
    st.session_state.event_log = []
 
if "tickets" not in st.session_state:
    st.session_state.tickets = []
 
if "last_label" not in st.session_state:
    st.session_state.last_label = {}
 
if "history" not in st.session_state:
    st.session_state.history = {d["device_id"]: [] for d in st.session_state.devices}

if "dns_history" not in st.session_state:
    st.session_state.dns_history = []
if "throughput_result" not in st.session_state:
    st.session_state.throughput_result = None
if "isp_tickets" not in st.session_state:
    st.session_state.isp_tickets = []
 
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = True
 
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
 
 
def drift(device: dict, amount: float = 2.0) -> dict:
    device["rssi"] += random.uniform(-amount, amount)
    device["snr"] = max(0.0, device["snr"] + random.uniform(-amount / 2, amount / 2))
    device["retry_rate"] = max(0.0, device["retry_rate"] + random.uniform(-1.0, 1.0))
    return device
 
 
TICKET_WORTHY = {"Attenuated Signal", "Congestion", "Signal Critically Weak"}
 
 
def file_ticket(device_id: str, issue: str, reason: str) -> dict:
    """Create a ticket in the shared tickets list (used by both the manual
    'File ticket' button and the AI assistant's autonomous scan)."""
    now = datetime.now().strftime("%H:%M:%S")
    ticket = {
        "ticket_id": len(st.session_state.tickets) + 1,
        "time": now,
        "device_id": device_id,
        "issue": issue,
        "reason": reason,
        "status": "Open",
    }
    st.session_state.tickets.insert(0, ticket)
    return ticket
 
 
def has_open_ticket(device_id: str) -> bool:
    return any(t["device_id"] == device_id and t["status"] == "Open" for t in st.session_state.tickets)
 
 
LIVE_CHANNEL_DEFAULT = {"2.4GHz": 6, "5GHz": 36, "6GHz": 37}


def _enrich_live(d: dict) -> dict:
    """Live poller dicts lack the keys the synthetic path invented.

    The dashboard reads d["channel"] in the Band tab and d["profile"] in
    a few places; a real station dump has neither. Fill them in rather
    than letting a KeyError take out the whole tab.
    """
    d.setdefault("profile", "live")
    d.setdefault("source", "live")
    if not d.get("channel"):
        d["channel"] = LIVE_CHANNEL_DEFAULT.get(d.get("band"), 0)
    if "phy_rate" not in d and "tx_rate_mbps" in d:
        d["phy_rate"] = d["tx_rate_mbps"]
    d.setdefault("retry_rate", 0.0)
    return d

def run_cycle() -> list:
    results = []
    now = datetime.now().strftime("%H:%M:%S")

    # Live if the poller is feeding telemetry_server, synthetic otherwise.
    # Synthetic devices persist in session_state and random-walk so the demo
    # looks continuous; live devices are whatever is actually associated, and
    # must never be drifted -- that would fabricate movement on real readings.
    devices, st.session_state.data_status = get_devices()

    # Live and synthetic RSSI must never share a Kalman estimate — the filter
    # would blend two unrelated signals and report a number that describes
    # neither. Flipping source resets per-device state.
    _src = st.session_state.data_status["source"]
    if st.session_state.get("_last_source") not in (None, _src):
        reset_state()
        st.session_state.history = {}
    st.session_state._last_source = _src

    if _src == "live":
        devices = [_enrich_live(d) for d in devices]
    else:
        devices = st.session_state.devices
        for d in devices:
            drift(d)
 
    for d in devices:
        smooth(d)
        try:
            result = classify(
                d, network_devices=devices, freq_mhz=freq_for_band(d.get("band"))
            )
        except TypeError:
            # Installed diagnostic_engine.classify() doesn't accept freq_mhz —
            # fall back to the simpler call so the dashboard still runs.
            result = classify(d, network_devices=devices)
 
        if len(result) >= 3:
            label, reason, confidence = result[0], result[1], result[2]
        elif len(result) == 2:
            label, reason = result
            confidence = 100 if label == "Optimal" else 70
        else:
            label, reason, confidence = "Insufficient Information", "Diagnostic engine returned no data.", 0
 
        prev = st.session_state.last_label.get(d["device_id"])
        if prev is not None and prev != label:
            st.session_state.event_log.insert(0, {
                "time": now, "device_id": d["device_id"],
                "from": prev, "to": label, "reason": reason,
            })
            # has_open_ticket guard matters: without it a device flickering
            # across a threshold during a walk test files a fresh ticket on
            # every crossing, and health used to fall with each one.
            if label in TICKET_WORTHY and not has_open_ticket(d["device_id"]):
                file_ticket(d["device_id"], label, reason)
        st.session_state.last_label[d["device_id"]] = label
 
        hist = st.session_state.history.setdefault(d["device_id"], [])
        hist.append(d["rssi"])
        if len(hist) > 20:
            hist.pop(0)
 
        results.append({**d, "diagnosis": label, "reason": reason, "confidence": confidence})
 
    return results
 
 
# ----------------------------------------------------------------------------
# Sidebar controls
# ----------------------------------------------------------------------------
 
with st.sidebar:
    st.markdown("### 📡 Wi-Fi Band Analyzer")
    st.caption("Live root-cause diagnostics across 2.4 / 5 / 6 GHz")
    _s = st.session_state.get("data_status", {})
    st.metric("Data source", _s.get("source", "unknown").upper())
    if _s.get("source") != "live":
        st.caption(_s.get("detail", ""))
    st.session_state.auto_refresh = st.toggle("Auto-refresh (3s)", value=st.session_state.auto_refresh)
    refresh_now = st.button("🔄 Refresh now", use_container_width=True)
    st.divider()
    st.markdown("**Network Standard**")
    st.caption(f"Offered max: {NETWORK_MAX_STANDARD}")
    st.divider()
    st.markdown("**Export**")
    st.caption("See the Export tab to download CSV snapshots.")
 
 
# ----------------------------------------------------------------------------
# Run a diagnostic cycle
# ----------------------------------------------------------------------------
 
results = run_cycle()

# One DNS sample per refresh. ~10ms when healthy, so it does not slow the
# dashboard; the toggle exists because a *broken* resolver blocks for the
# full timeout on every rerun, which does.
if st.session_state.get("probe_dns_auto", True):
    _dns = active_probe.check_dns()
    _dns["t"] = datetime.now().strftime("%H:%M:%S")
    st.session_state.dns_history.append(_dns)
    st.session_state.dns_history = st.session_state.dns_history[-60:]
df = pd.DataFrame(results)
 
# ----------------------------------------------------------------------------
# Header — Network Health
# ----------------------------------------------------------------------------
 
st.title("Wi-Fi Band Analyzer")
st.caption("Root-cause diagnostics · Kalman-smoothed telemetry · explainable classification")

_status = st.session_state.get("data_status", {"source": "?", "detail": ""})
if _status["source"] == "live":
    st.success(f"LIVE telemetry - {_status['detail']}", icon="📡")
else:
    st.warning(
        f"SYNTHETIC data - {_status.get('detail', '')}  \n"
        "Nothing on screen is measured. Run `python3 preflight.py` to find "
        "which hop of the live chain is down.",
        icon="⚠️",
    )
 
problem_count = int((df["diagnosis"] != "Optimal").sum())
avg_rssi = round(df["rssi"].mean(), 1)
avg_snr = round(df["snr"].mean(), 1)
open_tickets = sum(1 for t in st.session_state.tickets if t["status"] == "Open")

# Network health = the complement of how bad the network is, as a fraction of
# how bad it could possibly be. sum(SEVERITY) is observed badness; 3 * n is
# the maximum, since 3 is the top severity. No free constants, and it
# saturates correctly at both ends by construction.
#
# Three deliberate choices:
#   - Unclassified devices leave both numerator and denominator. "I don't
#     know" is not evidence of health or of fault. The old formula counted
#     Insufficient Information as a problem, so a device the engine honestly
#     declined to judge cost as much as one that was critically weak.
#   - Severity is weighted. Hardware Limited (a permanent, benign property
#     of the client) no longer costs the same as Signal Critically Weak.
#   - Open tickets are NOT subtracted. A ticket records that a problem
#     happened; the device causing it is already counted. Charging both
#     penalised one fault twice, and tickets never auto-close, so health
#     stayed depressed long after the network recovered.
#
# This is a presentation statistic, not a measurement: there is no ground
# truth for "network health" anywhere in this project. Its justification is
# only that it moves in the right direction and reaches its endpoints.
_scored = [l for l in df["diagnosis"] if l != "Insufficient Information"]
if _scored:
    _badness = sum(SEVERITY.get(l, 1) for l in _scored)
    health_score = round(100 * (1 - _badness / (3 * len(_scored))))
    health_note = f"{len(_scored)} of {len(df)} devices classified"
else:
    health_score = None
    health_note = "no device could be classified"
 
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Network Health",
          f"{health_score}%" if health_score is not None else "n/a",
          help=health_note)
c2.metric("Devices Monitored", len(df))
c3.metric("Devices Flagged", problem_count)
c4.metric("Avg RSSI", f"{avg_rssi} dBm")
c5.metric("Open Tickets", open_tickets)
 
st.divider()
 
# ----------------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------------
 
(
    tab_overview, tab_devices, tab_recs, tab_bands,
    tab_timeline, tab_tickets, tab_probe, tab_ai, tab_export,
) = st.tabs([
    "🏠 Overview", "📶 Device Summary", "🛠 Recommendations", "🗺️ Band & Channel",
    "🕒 Event Timeline", "🎫 Tickets", "🛰 Active Probe", "🤖 AI Assistant", "⬇️ Export",
])
 
# ---- Overview: root causes + detected problems + alerts ----
with tab_overview:
    left, right = st.columns([1.1, 1])
 
    with left:
        st.subheader("Root Cause Distribution")
        cause_counts = df["diagnosis"].value_counts().reset_index()
        cause_counts.columns = ["diagnosis", "count"]
        chart = (
            alt.Chart(cause_counts)
            .mark_bar()
            .encode(
                x=alt.X("count:Q", title="Devices"),
                y=alt.Y("diagnosis:N", sort="-x", title=None),
                color=alt.Color(
                    "diagnosis:N",
                    scale=alt.Scale(domain=list(CATEGORY_COLORS.keys()), range=list(CATEGORY_COLORS.values())),
                    legend=None,
                ),
                tooltip=["diagnosis", "count"],
            )
            .properties(height=260)
        )
        st.altair_chart(chart, use_container_width=True)
 
    with right:
        st.subheader("🚨 Active Alerts")
        problems = df[df["diagnosis"] != "Optimal"].sort_values(
            by="diagnosis", key=lambda s: s.map(lambda x: SEVERITY.get(x, 0)), ascending=False
        )
        if problems.empty:
            st.success("No active issues — all devices Optimal.")
        else:
            for _, row in problems.iterrows():
                st.markdown(
                    f"""<div class="card">
                    {badge(row['diagnosis'])} &nbsp; <b>{row['device_id']}</b>
                    <div class="small-muted">{row['reason']}</div>
                    <div class="small-muted">Confidence: {row['confidence']}%</div>
                    </div>""",
                    unsafe_allow_html=True,
                )
 
    st.subheader("Detected Problems (Full Detail)")
    if problems.empty:
        st.caption("Nothing to show — network is healthy.")
    else:
        show_cols = ["device_id", "band", "standard", "rssi", "snr", "retry_rate", "diagnosis", "confidence", "reason"]
        st.dataframe(
            problems[show_cols],
            use_container_width=True,
            hide_index=True,
            key="overview_problems_table",
            column_config={
                "confidence": st.column_config.ProgressColumn(
                    "Confidence", min_value=0, max_value=100, format="%d%%"
                ),
            },
        )
 
# ---- Device Summary ----
with tab_devices:
    st.subheader("All Connected Devices")
    show_cols = ["device_id", "band", "standard", "channel", "rssi", "snr", "retry_rate", "diagnosis", "confidence"]
    st.dataframe(
        df[show_cols],
        use_container_width=True,
        hide_index=True,
        key="device_summary_table",
        column_config={
            "confidence": st.column_config.ProgressColumn(
                "Confidence", min_value=0, max_value=100, format="%d%%"
            ),
            "rssi": st.column_config.NumberColumn("RSSI (dBm)", format="%.1f"),
            "snr": st.column_config.NumberColumn("SNR (dB)", format="%.1f"),
            "retry_rate": st.column_config.NumberColumn("Retry %", format="%.1f"),
        },
    )
 
    st.subheader("Reasoning Trace")
    for _, row in df.iterrows():
        with st.expander(f"{row['device_id']} — {badge(row['diagnosis'])}", expanded=False):
            trace_left, trace_right = st.columns([2, 1])
 
            with trace_left:
                st.markdown(row["reason"], unsafe_allow_html=False)
                st.progress(int(row["confidence"]), text=f"Confidence: {row['confidence']}%")
                st.caption(f"Recommendation: {RECOMMENDATIONS.get(row['diagnosis'], '—')}")
 
                if row["diagnosis"] != "Optimal" and not has_open_ticket(row["device_id"]):
                    if st.button(f"🎫 File ticket for {row['device_id']}", key=f"manual_ticket_{row['device_id']}"):
                        file_ticket(row["device_id"], row["diagnosis"], row["reason"])
                        st.rerun()
                elif row["diagnosis"] != "Optimal":
                    st.caption("An open ticket already exists for this device.")
 
            with trace_right:
                gauge = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=row["confidence"],
                    number={"suffix": "%", "font": {"size": 24}},
                    gauge={
                        "axis": {"range": [0, 100]},
                        "bar": {"color": CATEGORY_COLORS.get(row["diagnosis"], "#6b7280")},
                        "bgcolor": "rgba(0,0,0,0)",
                        "borderwidth": 0,
                    },
                ))
                gauge.update_layout(
                    height=150, margin=dict(l=10, r=10, t=10, b=10),
                    paper_bgcolor="rgba(0,0,0,0)", font={"color": "#c9ced6"},
                )
                st.plotly_chart(
                    gauge, use_container_width=True, config={"displayModeBar": False},
                    key=f"gauge_{row['device_id']}",
                )
 
# ---- Recommendations ----
with tab_recs:
    st.subheader("Recommended Actions")
    st.caption("Ranked by confidence — highest-confidence diagnoses first.")
    ranked = df.sort_values(
        by=["diagnosis", "confidence"],
        key=lambda s: s if s.name == "confidence" else s.map(lambda x: SEVERITY.get(x, 0)),
        ascending=[True, False],
    )
    for _, row in ranked.iterrows():
        st.markdown(
            f"""<div class="card">
            {badge(row['diagnosis'])} &nbsp; <b>{row['device_id']}</b>
            <span class="small-muted"> · {row['confidence']}% confidence</span>
            <div class="small-muted">{RECOMMENDATIONS.get(row['diagnosis'], '—')}</div>
            </div>""",
            unsafe_allow_html=True,
        )
 
# ---- Band & Channel analysis (includes heatmap) ----
with tab_bands:
    colA, colB = st.columns(2)
 
    with colA:
        st.subheader("Band Distribution")
        band_counts = df["band"].value_counts().reset_index()
        band_counts.columns = ["band", "count"]
        st.altair_chart(
            alt.Chart(band_counts).mark_arc(innerRadius=60).encode(
                theta="count:Q", color="band:N", tooltip=["band", "count"]
            ).properties(height=260),
            use_container_width=True,
        )
 
    with colB:
        st.subheader("Channel Congestion")
        if "channel" not in df.columns:
            df["channel"] = 0
        chan_counts = df.groupby(["band", "channel"]).size().reset_index(name="count")
        st.altair_chart(
            alt.Chart(chan_counts).mark_bar().encode(
                x=alt.X("channel:O", title="Channel"),
                y=alt.Y("count:Q", title="Devices"),
                color=alt.Color("band:N", legend=alt.Legend(title="Band")),
                tooltip=["band", "channel", "count"],
            ).properties(height=260),
            use_container_width=True,
        )
        st.caption("Channel assignment is simulated for demo purposes until real per-device channel telemetry is captured.")
 
    st.subheader("Signal Heatmap — RSSI Over Recent Readings")
    hist_rows = []
    for did, hist in st.session_state.history.items():
        for i, val in enumerate(hist):
            hist_rows.append({"device_id": did, "reading": i, "rssi": val})
    if hist_rows:
        hist_df = pd.DataFrame(hist_rows)
        heatmap = (
            alt.Chart(hist_df)
            .mark_rect()
            .encode(
                x=alt.X("reading:O", title="Reading # (most recent = rightmost)"),
                y=alt.Y("device_id:N", title=None),
                color=alt.Color("rssi:Q", scale=alt.Scale(scheme="redyellowgreen", domain=[-95, -30]), title="RSSI (dBm)"),
                tooltip=["device_id", "reading", "rssi"],
            )
            .properties(height=220)
        )
        st.altair_chart(heatmap, use_container_width=True)
    else:
        st.caption("Collecting readings — heatmap will populate after a few refresh cycles.")
 
# ---- Event Timeline ----
with tab_timeline:
    st.subheader("Diagnosis Change Events")
    if not st.session_state.event_log:
        st.caption("No category transitions yet — events appear here as device diagnoses change.")
    else:
        for ev in st.session_state.event_log[:30]:
            st.markdown(
                f"""<div class="card">
                <span class="small-muted">{ev['time']}</span> &nbsp; <b>{ev['device_id']}</b>
                &nbsp; {badge(ev['from'])} → {badge(ev['to'])}
                <div class="small-muted">{ev['reason']}</div>
                </div>""",
                unsafe_allow_html=True,
            )
 
# ---- Tickets ----
with tab_tickets:
    st.subheader("Support Tickets")
    st.caption("Auto-filed when a device transitions into a ticket-worthy issue "
               "(Attenuated Signal, Congestion, Signal Critically Weak) — or file one "
               "manually from the Device Summary tab or the AI Assistant.")
    if not st.session_state.tickets:
        st.caption("No tickets filed yet.")
    else:
        for t in st.session_state.tickets:
            cols = st.columns([5, 1])
            with cols[0]:
                st.markdown(
                    f"""<div class="card">
                    <b>#{t['ticket_id']}</b> &nbsp; {badge(t['issue'])} &nbsp; <b>{t['device_id']}</b>
                    <span class="small-muted"> · {t['time']}</span>
                    <div class="small-muted">{t['reason']}</div>
                    <div class="small-muted">Status: <b>{t['status']}</b></div>
                    </div>""",
                    unsafe_allow_html=True,
                )
            with cols[1]:
                if t["status"] == "Open":
                    if st.button("Resolve", key=f"resolve_{t['ticket_id']}"):
                        t["status"] = "Resolved"
                        st.rerun()
 
# ---- AI Assistant (agentic, rule-based — no external API needed) ----
 
def ai_agent_response(query: str) -> str:
    """Local 'agent' that reasons over the current device telemetry (df,
    session_state.tickets, health_score, etc.) and can take actions like
    filing tickets — no external LLM/API call required, so it works
    offline out of the box during a demo."""
    q = query.lower()
 
    if "file ticket" in q or "autonomous" in q or ("auto" in q and "ticket" in q):
        filed = []
        for _, row in df[df["diagnosis"] != "Optimal"].iterrows():
            if has_open_ticket(row["device_id"]):
                continue
            file_ticket(row["device_id"], row["diagnosis"], row["reason"])
            filed.append(row["device_id"])
        if filed:
            return f"Ran an autonomous scan and filed tickets for: {', '.join(filed)}. Check the Tickets tab."
        return "Ran an autonomous scan — every flagged device already has an open ticket, nothing new to file."
 
    if "attention" in q or "problem" in q or "issue" in q or "flagged" in q:
        flagged = df[df["diagnosis"] != "Optimal"].sort_values("confidence", ascending=False)
        if flagged.empty:
            return "All devices are currently Optimal — nothing needs attention."
        lines = [f"- **{r.device_id}**: {r.diagnosis} ({r.confidence}% confidence) — {r.reason}"
                 for r in flagged.itertuples()]
        return "Devices needing attention:\n" + "\n".join(lines)
 
    if "summar" in q or "health" in q or "overview" in q:
        return (f"Network health score is {health_score}%. {problem_count} of {len(df)} devices are "
                f"flagged, {open_tickets} ticket(s) are open. Average RSSI is {avg_rssi} dBm and "
                f"average SNR is {avg_snr} dB.")
 
    if "recommend" in q:
        flagged = df[df["diagnosis"] != "Optimal"]
        if flagged.empty:
            return "No action needed right now — every device is Optimal."
        lines = [f"- **{r.device_id}**: {RECOMMENDATIONS.get(r.diagnosis, '—')}" for r in flagged.itertuples()]
        return "Recommendations:\n" + "\n".join(lines)
 
    if "channel" in q or "congest" in q or "band" in q:
        congested = df[df["diagnosis"] == "Congestion"]
        if not congested.empty:
            names = ", ".join(congested["device_id"])
            return f"Congestion detected on: {names}. Consider a channel switch or moving them to a quieter band."
        return "No congestion detected in the current cycle."
 
    for _, row in df.iterrows():
        if row["device_id"].lower() in q:
            return (f"**{row['device_id']}** — {row['diagnosis']} ({row['confidence']}% confidence). "
                    f"{row['reason']} Recommendation: {RECOMMENDATIONS.get(row['diagnosis'], '—')}")
 
    return ("I can summarize network health, list flagged devices, explain root causes, "
            "give recommendations, check channel congestion, or auto-file tickets — "
            "just ask, e.g. \"which devices need attention?\" or \"run autonomous scan and file tickets\".")
 
 
with tab_ai:
    st.subheader("🤖 Network AI Assistant")
    st.caption("Ask about network health, root causes, or let it act for you — "
               "runs locally on live telemetry, no external API required.")
 
    qc1, qc2, qc3, qc4 = st.columns(4)
    quick_prompts = {
        qc1: "Summarize network health",
        qc2: "Which devices need attention?",
        qc3: "Give recommendations",
        qc4: "Run autonomous scan and file tickets",
    }
    triggered_prompt = None
    for col, prompt in quick_prompts.items():
        with col:
            if st.button(prompt, use_container_width=True, key=f"quick_{prompt}"):
                triggered_prompt = prompt
 
    for role, text in st.session_state.chat_history:
        with st.chat_message(role):
            st.markdown(text)
 
    user_msg = st.chat_input("Ask the network assistant...")
    final_msg = triggered_prompt or user_msg
 
    if final_msg:
        st.session_state.chat_history.append(("user", final_msg))
        reply = ai_agent_response(final_msg)
        st.session_state.chat_history.append(("assistant", reply))
        st.rerun()
 
# ---- Export ----
with tab_export:
    st.subheader("Export Data")
    snapshot_csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download current device snapshot (CSV)",
        data=snapshot_csv,
        file_name=f"device_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        use_container_width=True,
        key="export_snapshot",
    )
 
    if st.session_state.event_log:
        events_csv = pd.DataFrame(st.session_state.event_log).to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download event timeline (CSV)",
            data=events_csv,
            file_name=f"event_timeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
            key="export_events",
        )
 
    if st.session_state.tickets:
        tickets_csv = pd.DataFrame(st.session_state.tickets).to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download tickets (CSV)",
            data=tickets_csv,
            file_name=f"tickets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
            key="export_tickets",
        )
 
# ---- Active Probe: measurements we generate, rather than observe ----
with tab_probe:
    st.subheader("Active Probe")
    st.caption(
        "The poller only reports what the radio says. These probes put traffic "
        "on the network to answer questions a station dump cannot."
    )

    c1, c2 = st.columns(2)

    # ---------------------------------------------------------------- DNS
    with c1:
        st.markdown("#### Name resolution")
        st.session_state.probe_dns_auto = st.toggle(
            "Sample every refresh", value=st.session_state.get("probe_dns_auto", True),
            key="dns_auto_toggle",
        )

        hist = st.session_state.dns_history
        latest = hist[-1] if hist else None

        if latest is None:
            st.info("No sample yet.")
        elif latest["ok"]:
            oks = [h["ms"] for h in hist if h["ok"]]
            st.metric("DNS latency", f"{latest['ms']} ms",
                      delta=f"{round(latest['ms'] - sum(oks) / len(oks), 1)} ms vs mean"
                      if len(oks) > 1 else None, delta_color="inverse")
            if len(oks) > 1:
                st.line_chart({"ms": oks}, height=140)
            st.caption(
                f"{len(oks)}/{len(hist)} succeeded · min {min(oks)} · max {max(oks)} ms"
            )
        else:
            st.error(f"DNS failing — {latest['detail']}")
            st.caption(
                "Clients with no working resolver disassociate on their own, "
                "which shows up downstream as the poller seeing zero devices."
            )

        st.caption(
            "Measures the AP's uplink (the USB tether), not any single client. "
            "It is a network-wide check, so it is reported here rather than "
            "per device."
        )

    # --------------------------------------------------------- throughput
    with c2:
        st.markdown("#### Throughput")
        if not active_probe.iperf3_available():
            st.warning("iperf3 not installed — `sudo apt install iperf3`")

        server = st.text_input("iperf3 server", value="192.168.50.1",
                               help="Run `iperf3 -s` on the target and enter its IP.")
        reverse = st.toggle("Reverse (download)", value=False,
                            help="Off measures upload to the server; on measures download.")

        if st.button("Run 3s test", use_container_width=True):
            with st.spinner(f"iperf3 against {server}…"):
                st.session_state.throughput_result = active_probe.run_throughput_test(
                    server=server, duration=3, reverse=reverse
                )

        res = st.session_state.throughput_result
        if res is None:
            st.caption("Not run yet.")
        elif res["ok"]:
            st.metric(f"Measured ({res['direction']})", f"{res['mbps']} Mbps")
            if res.get("retransmits"):
                st.caption(f"{res['retransmits']} retransmits during the run")
        else:
            st.error(res["detail"])

        st.caption(
            "Run from this laptop against an external host, iperf3 measures the "
            "tether, not Wi-Fi. To measure a client's actual link: `iperf3 -s` "
            "here, iperf3 client on the phone against 192.168.50.1."
        )

    st.divider()

    # ------------------------------------------------------ ISP escalation
    st.markdown("#### ISP escalation")
    st.caption(
        "Sends a ticket out of the process to mock_isp_server.py on :6000. "
        "Separate from the Tickets tab, which only records issues in this session."
    )

    flagged = [r for r in results if r["diagnosis"] != "Optimal"]
    if not flagged:
        st.success("No device currently has an issue worth escalating.")
    else:
        labels = [f"{r['device_id']} — {r['diagnosis']}" for r in flagged]
        pick = st.selectbox("Device", labels)
        chosen = flagged[labels.index(pick)]

        if st.button("Escalate to ISP", type="primary"):
            probe = st.session_state.dns_history[-1] if st.session_state.dns_history else {}
            out = active_probe.file_ticket({
                "device_id": chosen["device_id"],
                "issue": chosen["diagnosis"],
                "reason": chosen["reason"],
                "rssi": chosen["rssi"],
                "snr": chosen["snr"],
                "retry_rate": chosen["retry_rate"],
                "band": chosen["band"],
                "source": chosen.get("source", "unknown"),
                "dns_ms": probe.get("ms"),
                "throughput_mbps": (st.session_state.throughput_result or {}).get("mbps"),
            })
            st.session_state.isp_tickets.insert(
                0, {"time": datetime.now().strftime("%H:%M:%S"),
                    "device_id": chosen["device_id"], **out})

    for t in st.session_state.isp_tickets[:8]:
        if t["ok"]:
            st.success(f"{t['time']} · {t['device_id']} · {t['detail']}")
        else:
            st.error(f"{t['time']} · {t['device_id']} · {t['detail']}")

# ----------------------------------------------------------------------------
# Auto-refresh loop
# ----------------------------------------------------------------------------
 
if refresh_now:
    st.rerun()
 
if st.session_state.auto_refresh:
    time.sleep(3)
    st.rerun()