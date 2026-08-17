"""
Wi-Fi Band Analyzer — Professional Dashboard v2
Run:
    streamlit run src/app.py
"""

import os
import sys
import time
import requests
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import synthetic_generator, diagnostic_engine
from src.wall_overlay import build_overlay_figure, classify_wall_vs_distance

TELEMETRY_URL = "http://localhost:5000/devices"
TICKET_URL = "http://localhost:6000/ticket"

COLORS = {
    "Optimal": "#22c55e",
    "Congestion": "#f59e0b",
    "Far Distance": "#f59e0b",
    "Attenuated Signal": "#ef4444",
    "Hardware Limited": "#f59e0b",
    "Device-Specific Issue": "#ef4444",
    "Insufficient Information": "#94a3b8",
}

st.set_page_config(
    page_title="Wi-Fi Band Analyzer",
    page_icon="📶",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ========================= STYLE =========================
st.markdown("""
<style>
.stApp {
    background:
        radial-gradient(circle at 85% 0%, rgba(45,91,255,.12), transparent 28%),
        radial-gradient(circle at 10% 90%, rgba(0,180,255,.045), transparent 25%),
        #06111f;
    color: #f4f7fb;
}
[data-testid="stHeader"] { background: rgba(6,17,31,.92); }
[data-testid="stSidebar"] {
    background: linear-gradient(180deg,#071625 0%,#06111f 100%);
    border-right: 1px solid #19324b;
}
.block-container {
    max-width: 1480px;
    padding: 1.1rem 1.8rem 2.2rem;
}
h1,h2,h3,h4 { color:#f8fafc !important; }
hr { border-color:#19324b !important; }

.brand-row {
    display:flex; align-items:center; justify-content:space-between;
    margin-bottom:.75rem;
}
.brand-left { display:flex; align-items:center; gap:12px; }
.brand-icon {
    width:46px;height:46px;border-radius:14px;
    display:flex;align-items:center;justify-content:center;
    background:linear-gradient(135deg,#1687ff,#5a35ff);
    box-shadow:0 0 26px rgba(42,124,255,.28);
    font-size:24px;
}
.brand-title { font-size:1.45rem;font-weight:850;line-height:1.1; }
.brand-sub { color:#8095ac;font-size:.76rem;margin-top:3px; }
.live {
    display:flex;align-items:center;gap:7px;
    padding:6px 11px;border-radius:999px;
    color:#4ade80;background:rgba(34,197,94,.08);
    border:1px solid rgba(34,197,94,.28);
    font-size:.73rem;font-weight:800;
}
.dot { width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 9px #22c55e; }

.hero {
    border:1px solid #1b3855;border-radius:16px;
    padding:1.05rem 1.25rem;
    background:
      radial-gradient(circle at 80% 50%,rgba(64,76,255,.16),transparent 34%),
      linear-gradient(135deg,#0b1b31,#091526);
    box-shadow:0 12px 35px rgba(0,0,0,.18);
    margin-bottom:1rem;
}
.hero-title { font-size:1.48rem;font-weight:850; }
.hero-sub { color:#8ca0b7;font-size:.8rem;margin-top:4px; }

.kpi {
    min-height:132px;padding:1rem;
    border:1px solid #1a3550;border-radius:15px;
    background:linear-gradient(145deg,#0b1b2f,#091525);
    box-shadow:0 9px 26px rgba(0,0,0,.16);
}
.kpi.blue{border-color:rgba(47,140,255,.36)}
.kpi.purple{border-color:rgba(139,92,246,.36)}
.kpi.green{border-color:rgba(34,197,94,.30)}
.kpi.amber{border-color:rgba(245,158,11,.34)}
.kpi-icon {
    width:36px;height:36px;border-radius:11px;
    display:flex;align-items:center;justify-content:center;
    font-weight:900;font-size:17px;margin-bottom:.55rem;
}
.ib{background:rgba(47,140,255,.13);color:#60a5fa}
.ip{background:rgba(139,92,246,.13);color:#a78bfa}
.ig{background:rgba(34,197,94,.12);color:#4ade80}
.ia{background:rgba(245,158,11,.12);color:#fbbf24}
.kpi-label{color:#8297ae;font-size:.67rem;letter-spacing:.08em;font-weight:700}
.kpi-value{font-size:1.62rem;font-weight:850;margin-top:4px}
.kpi-sub{color:#6f859d;font-size:.7rem;margin-top:4px}

.card {
    border:1px solid #19334d;border-radius:15px;
    background:linear-gradient(145deg,#0b1b2d,#081423);
    box-shadow:0 10px 30px rgba(0,0,0,.15);
    padding:1rem 1.05rem;
    margin-top:1rem;
}
.card-title{font-size:1rem;font-weight:850}
.card-sub{color:#7e94ab;font-size:.72rem;margin-top:3px}

.status {
    display:inline-block;padding:5px 9px;border-radius:8px;
    font-size:.69rem;font-weight:850;border:1px solid;
    white-space:nowrap;
}
.s-green{color:#4ade80;background:rgba(34,197,94,.08);border-color:rgba(34,197,94,.28)}
.s-amber{color:#fbbf24;background:rgba(245,158,11,.08);border-color:rgba(245,158,11,.28)}
.s-red{color:#f87171;background:rgba(239,68,68,.08);border-color:rgba(239,68,68,.28)}

.device-name{font-size:.83rem;font-weight:850;color:#f5f8fc}
.device-meta{font-size:.69rem;color:#71879f;margin-top:3px}
.field-label{font-size:.61rem;color:#6f859c;letter-spacing:.07em;font-weight:700}
.field-value{font-size:.84rem;color:#eef3f8;font-weight:800;margin-top:2px}

.insight {
    border:1px solid #19344f;border-radius:11px;
    background:#0a1829;padding:.68rem .75rem;margin:.48rem 0;
}
.insight-title{font-size:.75rem;font-weight:800}
.insight-text{font-size:.68rem;color:#7d92aa;margin-top:3px}

.sidebar-brand{padding:.35rem .25rem 1rem;border-bottom:1px solid #183149}
.sidebar-title{font-size:1.03rem;font-weight:850;color:#fff}
.sidebar-sub{font-size:.68rem;color:#70869e;margin-top:3px}
.nav-item{padding:.55rem .2rem;color:#b8c7d8;font-size:.84rem}
.nav-active{
    padding:.6rem .75rem;border-radius:9px;
    background:linear-gradient(90deg,#0c67d9,#1454a5);
    color:#fff;font-weight:800;
    box-shadow:0 6px 18px rgba(20,84,165,.2);
}
.mode-box{
    margin-top:.7rem;padding:.75rem;border:1px solid #19344e;
    border-radius:11px;background:#091828;
}
.muted{color:#71879f;font-size:.68rem}
.footer{text-align:center;color:#4d647b;font-size:.65rem;margin-top:1.4rem}
</style>
""", unsafe_allow_html=True)

# ========================= SIDEBAR =========================
with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
      <div style="font-size:28px;margin-bottom:5px;">📶</div>
      <div class="sidebar-title">Wi-Fi Band Analyzer</div>
      <div class="sidebar-sub">Network Insights · Better Connections</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### Navigation")
    st.markdown('<div class="nav-active">⌂ &nbsp; Dashboard</div>', unsafe_allow_html=True)
    for item in ["▣  Devices", "◉  Network", "⌁  Diagnostics", "⚙  Settings"]:
        st.markdown(f'<div class="nav-item">{item}</div>', unsafe_allow_html=True)

    st.markdown("---")
    auto_refresh = st.checkbox("Auto-refresh (3s)", value=False)

    st.markdown("""
    <div class="mode-box">
      <div class="muted">ANALYSIS MODE</div>
      <div style="font-weight:850;margin-top:4px;">Synthetic & Integrated</div>
      <div class="muted" style="margin-top:4px;">Connected to Flask Backend</div>
    </div>
    <div class="footer">Wi-Fi Band Analyzer<br>v1.0.0</div>
    """, unsafe_allow_html=True)

# ========================= DATA FETCHERS =========================
def fetch_live_devices():
    try:
        r = requests.get(TELEMETRY_URL, timeout=1.5)
        if r.status_code == 200:
            return r.json(), "live"
    except requests.exceptions.RequestException:
        pass
    return None, None

def fetch_synthetic_devices():
    raw = [synthetic_generator.generate_device(f"dev{i}", profile) for i, profile in enumerate(synthetic_generator.DEVICE_PROFILES.keys())]
    smoothed = [diagnostic_engine.smooth(d) for d in raw]
    for d in smoothed:
        diagnosis, reason = diagnostic_engine.classify(d, smoothed)
        d["diagnosis"] = diagnosis
        d["reason"] = reason
    return smoothed

def fetch_devices():
    live, source = fetch_live_devices()
    if live:
        return live, source
    return fetch_synthetic_devices(), "synthetic (fallback)"

def fetch_ticket_status():
    try:
        r = requests.get("http://localhost:6000/tickets", timeout=1.0)
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.RequestException:
        pass
    return []

devices, source = fetch_devices()
tickets = fetch_ticket_status()

# ========================= HEADER =========================
st.markdown(f"""
<div class="brand-row">
  <div class="brand-left">
    <div class="brand-icon">📶</div>
    <div>
      <div class="brand-title">Wi-Fi Band Analyzer</div>
      <div class="brand-sub">Live network diagnostics & optimization</div>
    </div>
  </div>
  <div class="live"><span class="dot"></span> Live</div>
</div>

<div class="hero">
  <div class="hero-title">Wi-Fi Band Analyzer — Live Dashboard</div>
  <div class="hero-sub">Data source: <b>{source}</b> &nbsp;·&nbsp; {len(devices)} device(s) &nbsp;·&nbsp; {time.strftime('%H:%M:%S')}</div>
</div>
""", unsafe_allow_html=True)

# ========================= KPI =========================
if devices:
    avg_rssi = sum(float(d["rssi"]) for d in devices) / len(devices)
    avg_snr = sum(float(d["snr"]) for d in devices) / len(devices)
    issues = sum(d.get("diagnosis") != "Optimal" for d in devices)

    kpis = [
        ("blue","ib","▣","DEVICES ONLINE",str(len(devices)),f"/ {len(devices)} connected"),
        ("purple","ip","◉","AVG RSSI",f"{avg_rssi:.1f} dBm","Signal strength"),
        ("green","ig","⌁","AVG SNR",f"{avg_snr:.1f} dB","Signal quality"),
        ("amber","ia","!","DEVICES WITH ISSUES",str(issues),"Needs attention"),
    ]
    cols = st.columns(4)
    for c, (kind, icon_kind, icon, label, value, sub) in zip(cols, kpis):
        with c:
            st.markdown(f"""
            <div class="kpi {kind}">
              <div class="kpi-icon {icon_kind}">{icon}</div>
              <div class="kpi-label">{label}</div>
              <div class="kpi-value">{value}</div>
              <div class="kpi-sub">{sub}</div>
            </div>
            """, unsafe_allow_html=True)

    # ========================= QUALITY + INSIGHTS =========================
    order = ["Attenuated Signal","Congestion","Far Distance","Hardware Limited","Optimal"]
    scores = {
        "Attenuated Signal": 0.42,
        "Congestion": 0.62,
        "Far Distance": 0.56,
        "Hardware Limited": 0.70,
        "Optimal": 0.92,
    }
    score_labels = {k: f"{scores[k]:.2f}" for k in order}

    fig = go.Figure()
    for name in order:
        fig.add_trace(go.Bar(
            x=[name],
            y=[scores[name]],
            marker=dict(color=COLORS.get(name, "#94a3b8"), line=dict(width=0)),
            text=[score_labels[name]],
            textposition="outside",
            textfont=dict(color="#cbd8e6", size=10),
            hovertemplate=f"<b>{name}</b><br>Quality score: {scores[name]:.2f}<extra></extra>",
            showlegend=False
        ))
    fig.update_layout(
        height=285,
        margin=dict(l=5,r=5,t=15,b=50),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#91a4b9"),
        yaxis=dict(range=[0,1.08],gridcolor="rgba(120,150,185,.11)",zeroline=False,title="Quality score"),
        xaxis=dict(tickfont=dict(size=10)),
        showlegend=False,
    )

    left, right = st.columns([1.65, 1])
    with left:
        st.markdown("""
        <div class="card">
          <div class="card-title">Network Channel & Band Quality</div>
          <div class="card-sub">Current network conditions across key performance indicators</div>
        """, unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})
        st.markdown("</div>", unsafe_allow_html=True)

    optimal = int(sum(d.get("diagnosis") == "Optimal" for d in devices))
    poor = int(sum(d.get("diagnosis") in ("Attenuated Signal","Far Distance") for d in devices))
    congestion = int(sum(d.get("diagnosis") == "Congestion" for d in devices))

    with right:
        st.markdown("""
        <div class="card">
          <div class="card-title">Quick Insights</div>
          <div class="card-sub">Automatically generated from current telemetry</div>
        """, unsafe_allow_html=True)

        if optimal >= len(devices)/2:
            title, text = "🟢 Good overall network health", f"{optimal} of {len(devices)} devices are currently optimal."
        else:
            title, text = "🟠 Network needs attention", f"{optimal} of {len(devices)} devices are currently optimal."
        st.markdown(f'<div class="insight"><div class="insight-title">{title}</div><div class="insight-text">{text}</div></div>', unsafe_allow_html=True)

        if poor:
            st.markdown(f'<div class="insight"><div class="insight-title">🔴 {poor} device(s) have weak signal</div><div class="insight-text">Check distance, walls and router placement.</div></div>', unsafe_allow_html=True)

        if congestion:
            st.markdown(f'<div class="insight"><div class="insight-title">🟠 Channel optimization recommended</div><div class="insight-text">{congestion} device(s) show congestion symptoms.</div></div>', unsafe_allow_html=True)

        st.markdown('<div class="insight"><div class="insight-title">🔵 Signal varies by location</div><div class="insight-text">RSSI-based distance and wall attenuation are included.</div></div></div>', unsafe_allow_html=True)

    # ========================= DEVICES WITH TICKETING =========================
    st.markdown("""
    <div class="card">
      <div class="card-title">Connected Devices & Ticketing Integration</div>
      <div class="card-sub">Live device-level diagnosis, signal quality, and backend ticket generation</div>
    </div>
    """, unsafe_allow_html=True)

    for idx, dev in enumerate(devices):
        diagnosis = dev.get("diagnosis","Unknown")
        distance, gap, wall_label = classify_wall_vs_distance(dev)

        if "Optimal" in diagnosis:
            scls = "s-green"; icon = "✓"
        elif any(x in diagnosis for x in ["Attenuated Signal", "Device-Specific Issue", "🔴"]):
            scls = "s-red"; icon = "!"
        else:
            scls = "s-amber"; icon = "⚠"

        with st.container(border=True):
            c1, c2, c3, c4, c5, c6 = st.columns([1.45, 1.45, .9, .9, 1.0, 1.55])
            with c1:
                st.markdown(f'<div class="device-name">{dev["device_id"]}</div><div class="device-meta">{dev.get("band","?")} · {dev.get("standard","?")}</div>', unsafe_allow_html=True)
            with c2:
                st.markdown(f'<span class="status {scls}">{icon} {diagnosis}</span>', unsafe_allow_html=True)
            with c3:
                st.markdown(f'<div class="field-label">RSSI</div><div class="field-value">{dev["rssi"]} dBm</div>', unsafe_allow_html=True)
            with c4:
                st.markdown(f'<div class="field-label">SNR</div><div class="field-value">{dev["snr"]} dB</div>', unsafe_allow_html=True)
            with c5:
                st.markdown(f'<div class="field-label">DISTANCE</div><div class="field-value">~{distance} m</div>', unsafe_allow_html=True)
            with c6:
                st.markdown(f'<div class="field-label">ASSESSMENT</div><div class="field-value" style="font-size:.74rem;">{wall_label}</div>', unsafe_allow_html=True)

            with st.expander(f"Analysis, recommendation & Backend Ticketing — {dev['device_id']}"):
                st.markdown(f"**Why:** {dev.get('reason','No additional reasoning available.')}")
                
                # Recommendation logic
                diag_clean = diagnosis.replace("🟢 ", "").replace("🟡 ", "").replace("🟠 ", "").replace("🔴 ", "").replace("🟣 ", "").strip()
                if diag_clean == "Attenuated Signal":
                    st.error("Recommendation: relocate the router or add a mesh node near this device.")
                elif diag_clean == "Far Distance":
                    st.warning("Recommendation: move the device closer or add a range extender.")
                elif diag_clean == "Hardware Limited":
                    st.warning("Recommendation: this device's Wi-Fi adapter limits capability; a network change may not solve it.")
                elif diag_clean == "Congestion":
                    st.warning("Recommendation: move this device to a less congested channel or band.")
                else:
                    st.success("Recommendation: no immediate action required.")

                # Backend Ticket integration button
                unique_key = f"btn_{dev['device_id']}_{idx}_{time.time()}"
                if st.button(f"🚀 File Backend Ticket for {dev['device_id']}", key=unique_key):
                    try:
                        payload = {
                            "device_id": dev["device_id"],
                            "issue": diag_clean,
                            "reason": dev["reason"]
                        }
                        response = requests.post(TICKET_URL, json=payload)
                        if response.status_code == 200:
                            res_data = response.json()
                            st.success(f"Ticket Successfully Filed! ID: {res_data.get('ticket_id')} (Status: {res_data.get('status')})")
                        else:
                            st.error("Failed to reach backend mock server on port 6000.")
                    except Exception as e:
                        st.error(f"Connection error to backend: {e}")

    # ========================= MAP + INSIGHTS =========================
    map_left, map_right = st.columns([1.7, .8])
    with map_left:
        st.markdown("""
        <div class="card">
          <div class="card-title">Wall / Distance Overlay</div>
          <div class="card-sub">Implied device position from RSSI · router at center · rings represent increasing distance</div>
        """, unsafe_allow_html=True)
        st.plotly_chart(build_overlay_figure(devices), use_container_width=True, config={"displayModeBar":False})
        st.markdown("</div>", unsafe_allow_html=True)

    with map_right:
        st.markdown("""
        <div class="card">
          <div class="card-title">Network Readout</div>
          <div class="card-sub">At-a-glance interpretation</div>
        """, unsafe_allow_html=True)
        st.markdown(f'<div class="insight"><div class="insight-title">🟢 Optimal</div><div class="insight-text">{optimal} device(s) in healthy range.</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="insight"><div class="insight-title">🟠 Attention</div><div class="insight-text">{len(devices)-optimal-poor} congestion/hardware cases.</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="insight"><div class="insight-title">🔴 Weak coverage</div><div class="insight-text">{poor} device(s) affected by distance or walls.</div></div>', unsafe_allow_html=True)
        st.markdown('<div class="insight"><div class="insight-title">📍 Placement insight</div><div class="insight-text">Use the map to identify devices far from the router.</div></div></div>', unsafe_allow_html=True)

else:
    st.info("No devices reporting yet.")

# ========================= TICKETS LOG =========================
if tickets:
    st.markdown("---")
    st.markdown(f"### 🎫 Recent Backend Tickets Log ({len(tickets)} total)")
    with st.expander("View all synced tickets payload"):
        st.json(tickets)

if auto_refresh:
    time.sleep(3)
    st.rerun()
