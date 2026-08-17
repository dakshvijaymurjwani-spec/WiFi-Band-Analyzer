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
import streamlit as st

sys.path.append(os.path.dirname(__file__))

from synthetic_generator import generate, DEVICE_PROFILES  # noqa: E402
from diagnostic_engine import smooth, classify  # noqa: E402

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

NETWORK_MAX_STANDARD = "wifi6e"


def badge(label: str) -> str:
    color = CATEGORY_COLORS.get(label, "#6b7280")
    return f'<span class="badge" style="background:{color}">{label}</span>'


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

if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = True


def drift(device: dict, amount: float = 2.0) -> dict:
    device["rssi"] += random.uniform(-amount, amount)
    device["snr"] = max(0.0, device["snr"] + random.uniform(-amount / 2, amount / 2))
    device["retry_rate"] = max(0.0, device["retry_rate"] + random.uniform(-1.0, 1.0))
    return device


TICKET_WORTHY = {"Attenuated Signal", "Congestion", "Signal Critically Weak"}


def run_cycle() -> list:
    results = []
    devices = st.session_state.devices
    now = datetime.now().strftime("%H:%M:%S")

    for d in devices:
        drift(d)
        smooth(d)
        label, reason, confidence = classify(d, network_devices=devices)

        prev = st.session_state.last_label.get(d["device_id"])
        if prev is not None and prev != label:
            st.session_state.event_log.insert(0, {
                "time": now, "device_id": d["device_id"],
                "from": prev, "to": label, "reason": reason,
            })
            if label in TICKET_WORTHY and (not prev or prev not in TICKET_WORTHY):
                st.session_state.tickets.insert(0, {
                    "ticket_id": len(st.session_state.tickets) + 1,
                    "time": now, "device_id": d["device_id"],
                    "issue": label, "reason": reason, "status": "Open",
                })
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
    st.session_state.auto_refresh = st.toggle("Auto-refresh (3s)", value=st.session_state.auto_refresh)
    refresh_now = st.button("🔄 Refresh now", use_container_width=True)
    st.divider()
    st.markdown("**Network Standard**")
    st.caption(f"Offered max: `{NETWORK_MAX_STANDARD}`")
    st.divider()
    st.markdown("**Export**")


# ----------------------------------------------------------------------------
# Run a diagnostic cycle
# ----------------------------------------------------------------------------

results = run_cycle()
df = pd.DataFrame(results)

# ----------------------------------------------------------------------------
# Header — Network Health
# ----------------------------------------------------------------------------

st.title("Wi-Fi Band Analyzer")
st.caption("Root-cause diagnostics · Kalman-smoothed telemetry · explainable classification")

problem_count = int((df["diagnosis"] != "Optimal").sum())
avg_rssi = round(df["rssi"].mean(), 1)
avg_snr = round(df["snr"].mean(), 1)
open_tickets = sum(1 for t in st.session_state.tickets if t["status"] == "Open")
health_score = max(0, round(100 - (problem_count / len(df)) * 70 - open_tickets * 5))

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Network Health", f"{health_score}%")
c2.metric("Devices Monitored", len(df))
c3.metric("Devices Flagged", problem_count)
c4.metric("Avg RSSI", f"{avg_rssi} dBm")
c5.metric("Open Tickets", open_tickets)

st.divider()

# ----------------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------------

tab_overview, tab_devices, tab_bands, tab_timeline, tab_tickets, tab_export = st.tabs(
    ["🏠 Overview", "📶 Device Summary", "🗺️ Band & Channel", "🕒 Event Timeline", "🎫 Tickets", "⬇️ Export"]
)

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
            st.markdown(row["reason"], unsafe_allow_html=False)
            st.progress(int(row["confidence"]), text=f"Confidence: {row['confidence']}%")

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
    st.subheader("Auto-Generated Support Tickets")
    st.caption("Filed automatically when a device transitions into a ticket-worthy issue (Attenuated Signal, Congestion, Signal Critically Weak).")
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
    )

    if st.session_state.event_log:
        events_csv = pd.DataFrame(st.session_state.event_log).to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download event timeline (CSV)",
            data=events_csv,
            file_name=f"event_timeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    if st.session_state.tickets:
        tickets_csv = pd.DataFrame(st.session_state.tickets).to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download tickets (CSV)",
            data=tickets_csv,
            file_name=f"tickets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

# ----------------------------------------------------------------------------
# Auto-refresh loop
# ----------------------------------------------------------------------------

if refresh_now:
    st.rerun()

if st.session_state.auto_refresh:
    time.sleep(3)
    st.rerun()
