import os
import sys
import time
import math
import requests
import streamlit as st
import plotly.graph_objects as go

sys.path.append(os.path.dirname(__file__))

from diagnostic_engine import classify, smooth


# ============================================================
# CONFIGURATION
# ============================================================

TELEMETRY_URL = "http://localhost:5000/telemetry"
TICKET_URL = "http://localhost:6000/ticket"

st.set_page_config(
    page_title="Wi-Fi Band Analyzer",
    page_icon="📶",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# PROFESSIONAL DARK UI
# ============================================================

st.markdown("""
<style>

/* ---------- MAIN ---------- */

.stApp {
    background:
        radial-gradient(
            circle at 85% 0%,
            rgba(45, 91, 255, 0.13),
            transparent 28%
        ),
        #06111f;
    color: #f4f7fb;
}

[data-testid="stHeader"] {
    background: rgba(6, 17, 31, 0.94);
}

[data-testid="stSidebar"] {
    background:
        linear-gradient(
            180deg,
            #071625 0%,
            #06111f 100%
        );
    border-right: 1px solid #19324b;
}

.block-container {
    max-width: 1480px;
    padding: 1rem 1.7rem 2rem;
}

h1, h2, h3, h4 {
    color: #f8fafc !important;
}

hr {
    border-color: #19324b !important;
}


/* ---------- BRAND ---------- */

.brand {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}

.brand-left {
    display: flex;
    align-items: center;
    gap: 12px;
}

.logo {
    width: 48px;
    height: 48px;
    border-radius: 14px;

    display: flex;
    align-items: center;
    justify-content: center;

    background:
        linear-gradient(
            135deg,
            #1687ff,
            #5a35ff
        );

    font-size: 25px;

    box-shadow:
        0 0 28px rgba(42, 124, 255, 0.25);
}

.title {
    font-size: 1.5rem;
    font-weight: 850;
    line-height: 1.05;
}

.subtitle {
    color: #8095ac;
    font-size: 0.76rem;
    margin-top: 4px;
}

.live {
    display: flex;
    align-items: center;
    gap: 7px;

    padding: 6px 12px;
    border-radius: 999px;

    color: #4ade80;
    background: rgba(34, 197, 94, 0.08);
    border: 1px solid rgba(34, 197, 94, 0.28);

    font-size: 0.72rem;
    font-weight: 800;
}

.dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;

    background: #22c55e;

    box-shadow:
        0 0 9px #22c55e;
}


/* ---------- HERO ---------- */

.hero {
    border: 1px solid #1b3855;
    border-radius: 16px;

    padding: 1rem 1.2rem;

    background:
        radial-gradient(
            circle at 80% 50%,
            rgba(64, 76, 255, 0.15),
            transparent 34%
        ),
        linear-gradient(
            135deg,
            #0b1b31,
            #091526
        );

    margin-bottom: 1rem;
}

.hero-title {
    font-size: 1.45rem;
    font-weight: 850;
}

.hero-sub {
    color: #8ca0b7;
    font-size: 0.78rem;
    margin-top: 5px;
}


/* ---------- KPI CARDS ---------- */

.kpi {
    min-height: 130px;

    padding: 1rem;

    border: 1px solid #1a3550;
    border-radius: 15px;

    background:
        linear-gradient(
            145deg,
            #0b1b2f,
            #091525
        );

    box-shadow:
        0 9px 26px rgba(0, 0, 0, 0.15);
}

.kpi.blue {
    border-color: rgba(47, 140, 255, 0.36);
}

.kpi.purple {
    border-color: rgba(139, 92, 246, 0.36);
}

.kpi.green {
    border-color: rgba(34, 197, 94, 0.30);
}

.kpi.amber {
    border-color: rgba(245, 158, 11, 0.34);
}

.ki {
    width: 36px;
    height: 36px;

    border-radius: 11px;

    display: flex;
    align-items: center;
    justify-content: center;

    font-weight: 900;

    margin-bottom: 0.55rem;
}

.ib {
    background: rgba(47, 140, 255, 0.13);
    color: #60a5fa;
}

.ip {
    background: rgba(139, 92, 246, 0.13);
    color: #a78bfa;
}

.ig {
    background: rgba(34, 197, 94, 0.12);
    color: #4ade80;
}

.ia {
    background: rgba(245, 158, 11, 0.12);
    color: #fbbf24;
}

.kl {
    color: #8297ae;
    font-size: 0.66rem;
    letter-spacing: 0.08em;
    font-weight: 700;
}

.kv {
    font-size: 1.6rem;
    font-weight: 850;
    margin-top: 4px;
}

.ks {
    color: #6f859d;
    font-size: 0.7rem;
    margin-top: 4px;
}


/* ---------- CARDS ---------- */

.card {
    border: 1px solid #19334d;
    border-radius: 15px;

    background:
        linear-gradient(
            145deg,
            #0b1b2d,
            #081423
        );

    padding: 1rem 1.05rem;

    margin-top: 1rem;

    box-shadow:
        0 10px 30px rgba(0, 0, 0, 0.12);
}

.ct {
    font-size: 1rem;
    font-weight: 850;
}

.cs {
    color: #7e94ab;
    font-size: 0.72rem;
    margin-top: 3px;
}


/* ---------- STATUS BADGES ---------- */

.badge {
    display: inline-block;

    padding: 5px 9px;

    border-radius: 8px;

    font-size: 0.68rem;
    font-weight: 850;

    border: 1px solid;

    white-space: nowrap;
}

.green {
    color: #4ade80;
    background: rgba(34, 197, 94, 0.08);
    border-color: rgba(34, 197, 94, 0.28);
}

.amber {
    color: #fbbf24;
    background: rgba(245, 158, 11, 0.08);
    border-color: rgba(245, 158, 11, 0.28);
}

.red {
    color: #f87171;
    background: rgba(239, 68, 68, 0.08);
    border-color: rgba(239, 68, 68, 0.28);
}

.purple {
    color: #c084fc;
    background: rgba(168, 85, 247, 0.08);
    border-color: rgba(168, 85, 247, 0.28);
}

.gray {
    color: #cbd5e1;
    background: rgba(148, 163, 184, 0.08);
    border-color: rgba(148, 163, 184, 0.28);
}


/* ---------- DEVICE ---------- */

.device-head {
    font-size: 0.84rem;
    font-weight: 850;
}

.meta {
    font-size: 0.68rem;
    color: #71879f;
    margin-top: 3px;
}

.fl {
    font-size: 0.59rem;
    color: #6f859c;
    letter-spacing: 0.07em;
    font-weight: 700;
}

.fv {
    font-size: 0.82rem;
    color: #eef3f8;
    font-weight: 800;
    margin-top: 2px;
}


/* ---------- INSIGHTS ---------- */

.insight {
    border: 1px solid #19344f;
    border-radius: 11px;

    background: #0a1829;

    padding: 0.65rem 0.72rem;

    margin: 0.45rem 0;
}

.it {
    font-size: 0.74rem;
    font-weight: 800;
}

.ix {
    font-size: 0.67rem;
    color: #7d92aa;
    margin-top: 3px;
}


/* ---------- SIDEBAR ---------- */

.sidebar-title {
    font-size: 1.02rem;
    font-weight: 850;
}

.sidebar-sub {
    font-size: 0.68rem;
    color: #70869e;
    margin-top: 3px;
}

.nav-active {
    padding: 0.6rem 0.75rem;

    border-radius: 9px;

    background:
        linear-gradient(
            90deg,
            #0c67d9,
            #1454a5
        );

    font-weight: 800;
}

.nav-item {
    padding: 0.55rem 0.2rem;

    color: #b8c7d8;

    font-size: 0.84rem;
}

.mode {
    margin-top: 0.8rem;

    padding: 0.75rem;

    border: 1px solid #19344e;

    border-radius: 11px;

    background: #091828;
}

.muted {
    color: #71879f;
    font-size: 0.68rem;
}

</style>
""", unsafe_allow_html=True)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown("""
    <div style="
        padding:.35rem .25rem 1rem;
        border-bottom:1px solid #183149;
    ">
        <div style="font-size:28px;">📶</div>

        <div class="sidebar-title">
            Wi-Fi Band Analyzer
        </div>

        <div class="sidebar-sub">
            Network Insights · Better Connections
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### Navigation")

    st.markdown(
        '<div class="nav-active">⌂ &nbsp; Dashboard</div>',
        unsafe_allow_html=True
    )

    for item in [
        "▣  Devices",
        "◉  Network",
        "⌁  Diagnostics",
        "⚙  Settings"
    ]:
        st.markdown(
            f'<div class="nav-item">{item}</div>',
            unsafe_allow_html=True
        )

    st.markdown("---")

    auto_refresh = st.checkbox(
        "Auto-refresh (3s)",
        value=True
    )

    st.markdown("""
    <div class="mode">

        <div class="muted">
            DATA SOURCE
        </div>

        <div style="font-weight:850;margin-top:4px;">
            Linux Wi-Fi Telemetry
        </div>

        <div class="muted" style="margin-top:4px;">
            localhost:5000
        </div>

    </div>
    """, unsafe_allow_html=True)


# ============================================================
# REAL TELEMETRY
# ============================================================

def get_devices():

    try:

        response = requests.get(
            TELEMETRY_URL,
            timeout=2
        )

        response.raise_for_status()

        data = response.json()

        # Flask server returns latest_data directly.
        if isinstance(data, dict):

            # Also support wrapped responses.
            if isinstance(data.get("devices"), list):
                data = data["devices"]

            elif isinstance(data.get("data"), list):
                data = data["data"]

            elif isinstance(data.get("telemetry"), list):
                data = data["telemetry"]

            else:
                data = [data]

        if not isinstance(data, list):
            return [], "Invalid telemetry format"

        devices = []

        for i, item in enumerate(data):

            if not isinstance(item, dict):
                continue

            d = dict(item)

            # ------------------------------------------------
            # Accept several possible field names
            # ------------------------------------------------

            d.setdefault(
                "device_id",
                d.get(
                    "mac",
                    d.get(
                        "station",
                        f"device_{i + 1}"
                    )
                )
            )

            d.setdefault(
                "band",
                d.get(
                    "wifi_band",
                    "Unknown"
                )
            )

            d.setdefault(
                "standard",
                d.get(
                    "wifi_standard",
                    "Unknown"
                )
            )

            d.setdefault(
                "rssi",
                d.get(
                    "rssi_dbm",
                    d.get(
                        "signal",
                        -100
                    )
                )
            )

            d.setdefault(
                "snr",
                d.get(
                    "snr_db",
                    0
                )
            )

            d.setdefault(
                "retry_rate",
                d.get(
                    "retries",
                    d.get(
                        "retry",
                        0
                    )
                )
            )

            # ------------------------------------------------
            # Convert numeric values safely
            # ------------------------------------------------

            try:
                d["rssi"] = float(d["rssi"])
            except Exception:
                d["rssi"] = -100.0

            try:
                d["snr"] = float(d["snr"])
            except Exception:
                d["snr"] = 0.0

            try:
                d["retry_rate"] = float(
                    d["retry_rate"]
                )
            except Exception:
                d["retry_rate"] = 0.0

            d["source"] = "live"

            devices.append(d)

        return devices, "live"

    except requests.exceptions.ConnectionError:

        return [], "Telemetry server unavailable"

    except requests.exceptions.Timeout:

        return [], "Telemetry server timeout"

    except Exception as e:

        return [], f"Telemetry error: {e}"


# ============================================================
# DIAGNOSTIC COLORS
# ============================================================

COLOR_MAP = {

    "Optimal":
        ("✓", "green"),

    "Hardware Limited":
        ("▣", "amber"),

    "Far Distance":
        ("↗", "amber"),

    "Attenuated Signal":
        ("!", "red"),

    "Congestion":
        ("⚠", "purple"),

    "Device-Specific Issue":
        ("!", "red"),

    "Insufficient Information":
        ("?", "gray"),
}


# ============================================================
# DISTANCE ESTIMATION
# ============================================================

def distance_from_rssi(rssi):

    try:

        tx_power = -30
        path_loss_exponent = 3.0

        distance = 10 ** (
            (tx_power - float(rssi))
            /
            (10 * path_loss_exponent)
        )

        return round(
            max(0.1, distance),
            2
        )

    except Exception:

        return 0.0


# ============================================================
# GET LIVE DATA
# ============================================================

devices, source = get_devices()


# ============================================================
# HEADER
# ============================================================

source_text = (
    "LIVE Wi-Fi telemetry"
    if source == "live"
    else source
)

st.markdown(f"""

<div class="brand">

    <div class="brand-left">

        <div class="logo">
            📶
        </div>

        <div>

            <div class="title">
                Wi-Fi Band Analyzer
            </div>

            <div class="subtitle">
                Live network diagnostics & optimization
            </div>

        </div>

    </div>

    <div class="live">
        <span class="dot"></span>
        LIVE
    </div>

</div>


<div class="hero">

    <div class="hero-title">
        Wi-Fi Band Analyzer — Live Dashboard
    </div>

    <div class="hero-sub">

        Data source:
        <b>{source_text}</b>

        &nbsp;·&nbsp;

        {len(devices)} device(s)

        &nbsp;·&nbsp;

        {time.strftime("%H:%M:%S")}

    </div>

</div>

""", unsafe_allow_html=True)


# ============================================================
# NO DATA
# ============================================================

if not devices:

    st.error(
        "No telemetry data received from "
        "http://localhost:5000/telemetry"
    )

    st.info(
        "Make sure your friend's "
        "telemetry_server.py and Wi-Fi poller "
        "are running."
    )

    if auto_refresh:

        time.sleep(3)
        st.rerun()

    st.stop()


# ============================================================
# RUN DIAGNOSTIC ENGINE
# ============================================================

for device in devices:

    try:

        smooth(device)

    except Exception:

        pass


for device in devices:

    try:

        result = classify(
            device,
            network_devices=devices
        )

        # Support both:
        #
        # label, reason
        #
        # and:
        #
        # label, reason, confidence

        if len(result) >= 2:

            label = result[0]
            reason = result[1]

        else:

            label = "Insufficient Information"
            reason = (
                "Diagnostic engine returned "
                "insufficient information."
            )

    except Exception as e:

        label = "Insufficient Information"

        reason = (
            f"Diagnostic engine error: {e}"
        )

    device["diagnosis_label"] = label
    device["reason"] = reason


# ============================================================
# KPI CALCULATIONS
# ============================================================

avg_rssi = sum(
    d["rssi"]
    for d in devices
) / len(devices)

avg_snr = sum(
    d["snr"]
    for d in devices
) / len(devices)

issues = sum(
    d["diagnosis_label"] != "Optimal"
    for d in devices
)

optimal = len(devices) - issues


# ============================================================
# KPI CARDS
# ============================================================

kpis = [

    (
        "blue",
        "ib",
        "▣",
        "DEVICES ONLINE",
        str(len(devices)),
        f"/ {len(devices)} connected"
    ),

    (
        "purple",
        "ip",
        "◉",
        "AVG RSSI",
        f"{avg_rssi:.1f} dBm",
        "Signal strength"
    ),

    (
        "green",
        "ig",
        "⌁",
        "AVG SNR",
        f"{avg_snr:.1f} dB",
        "Signal quality"
    ),

    (
        "amber",
        "ia",
        "!",
        "ATTENTION REQUIRED",
        str(issues),
        "Non-optimal devices"
    )

]


cols = st.columns(4)


for col, item in zip(cols, kpis):

    kind, icon_class, icon, label, value, sub = item

    with col:

        st.markdown(f"""

        <div class="kpi {kind}">

            <div class="ki {icon_class}">
                {icon}
            </div>

            <div class="kl">
                {label}
            </div>

            <div class="kv">
                {value}
            </div>

            <div class="ks">
                {sub}
            </div>

        </div>

        """, unsafe_allow_html=True)


# ============================================================
# NETWORK QUALITY SCORES
# ============================================================

score_map = {

    "Optimal": 0.92,

    "Hardware Limited": 0.70,

    "Far Distance": 0.56,

    "Attenuated Signal": 0.42,

    "Congestion": 0.62,

    "Device-Specific Issue": 0.48,

    "Insufficient Information": 0.30

}


chart_colors = {

    "Optimal": "#22c55e",

    "Hardware Limited": "#f59e0b",

    "Far Distance": "#f59e0b",

    "Attenuated Signal": "#ef4444",

    "Congestion": "#a855f7",

    "Device-Specific Issue": "#ef4444",

    "Insufficient Information": "#94a3b8"

}


active_labels = []


for label in score_map:

    if any(
        d["diagnosis_label"] == label
        for d in devices
    ):

        active_labels.append(label)


fig = go.Figure()


for label in active_labels:

    score = score_map[label]

    fig.add_trace(

        go.Bar(

            x=[label],

            y=[score],

            marker_color=chart_colors[label],

            text=[f"{score:.2f}"],

            textposition="outside",

            textfont=dict(
                color="#cbd8e6",
                size=10
            ),

            hovertemplate=(
                f"<b>{label}</b>"
                f"<br>Quality score: {score:.2f}"
                f"<extra></extra>"
            ),

            showlegend=False

        )

    )


fig.update_layout(

    height=285,

    margin=dict(
        l=5,
        r=5,
        t=15,
        b=55
    ),

    paper_bgcolor="rgba(0,0,0,0)",

    plot_bgcolor="rgba(0,0,0,0)",

    font=dict(
        color="#91a4b9"
    ),

    yaxis=dict(
        range=[0, 1.08],

        gridcolor=(
            "rgba(120,150,185,.11)"
        ),

        zeroline=False,

        title="Quality score"
    ),

    xaxis=dict(
        tickfont=dict(
            size=9
        )
    )

)


# ============================================================
# CHART + INSIGHTS
# ============================================================

left, right = st.columns(
    [1.65, 1]
)


with left:

    st.markdown("""

    <div class="card">

        <div class="ct">
            Network Channel & Band Quality
        </div>

        <div class="cs">
            Current conditions from real
            Linux Wi-Fi telemetry
        </div>

    """, unsafe_allow_html=True)

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "displayModeBar": False
        }
    )

    st.markdown(
        "</div>",
        unsafe_allow_html=True
    )


with right:

    st.markdown("""

    <div class="card">

        <div class="ct">
            Quick Insights
        </div>

        <div class="cs">
            Automatically generated
            from live telemetry
        </div>

    """, unsafe_allow_html=True)


    if optimal > 0:

        st.markdown(f"""

        <div class="insight">

            <div class="it">
                🟢 {optimal} device(s) optimal
            </div>

            <div class="ix">
                Healthy connection conditions detected.
            </div>

        </div>

        """, unsafe_allow_html=True)


    if issues > 0:

        st.markdown(f"""

        <div class="insight">

            <div class="it">
                🟠 {issues} device(s) need attention
            </div>

            <div class="ix">
                Open device analysis
                for the recommended action.
            </div>

        </div>

        """, unsafe_allow_html=True)


    weak = sum(

        d["diagnosis_label"]
        in (
            "Attenuated Signal",
            "Far Distance"
        )

        for d in devices

    )


    if weak > 0:

        st.markdown(f"""

        <div class="insight">

            <div class="it">
                🔴 {weak} weak-coverage case(s)
            </div>

            <div class="ix">
                Check distance, walls
                and AP placement.
            </div>

        </div>

        """, unsafe_allow_html=True)


    st.markdown(f"""

    <div class="insight">

        <div class="it">
            📡 Live source connected
        </div>

        <div class="ix">
            {len(devices)}
            device(s) received from
            localhost:5000.
        </div>

    </div>

    </div>

    """, unsafe_allow_html=True)


# ============================================================
# CONNECTED DEVICES
# ============================================================

st.markdown("""

<div class="card">

    <div class="ct">
        Connected Devices
    </div>

    <div class="cs">
        Real device telemetry · diagnosis ·
        signal quality · estimated distance
    </div>

</div>

""", unsafe_allow_html=True)


for device in devices:

    label = device["diagnosis_label"]

    icon, badge_class = COLOR_MAP.get(
        label,
        ("?", "gray")
    )

    distance = distance_from_rssi(
        device["rssi"]
    )


    with st.container(border=True):

        c1, c2, c3, c4, c5, c6 = st.columns(
            [1.45, 1.45, .95, .95, 1.0, 1.45]
        )


        with c1:

            st.markdown(

                f"""
                <div class="device-head">
                    {device.get("device_id", "unknown")}
                </div>

                <div class="meta">
                    {device.get("band", "Unknown")}
                    ·
                    {device.get("standard", "Unknown")}
                </div>
                """,

                unsafe_allow_html=True
            )


        with c2:

            st.markdown(

                f"""
                <span class="badge {badge_class}">
                    {icon} {label}
                </span>
                """,

                unsafe_allow_html=True
            )


        with c3:

            st.markdown(

                f"""
                <div class="fl">
                    RSSI
                </div>

                <div class="fv">
                    {device["rssi"]:.1f} dBm
                </div>
                """,

                unsafe_allow_html=True
            )


        with c4:

            st.markdown(

                f"""
                <div class="fl">
                    SNR
                </div>

                <div class="fv">
                    {device["snr"]:.1f} dB
                </div>
                """,

                unsafe_allow_html=True
            )


        with c5:

            st.markdown(

                f"""
                <div class="fl">
                    RETRY
                </div>

                <div class="fv">
                    {device["retry_rate"]:.2f}%
                </div>
                """,

                unsafe_allow_html=True
            )


        with c6:

            st.markdown(

                f"""
                <div class="fl">
                    EST. DISTANCE
                </div>

                <div class="fv">
                    ~{distance} m
                </div>
                """,

                unsafe_allow_html=True
            )


        # ----------------------------------------------------
        # DEVICE DETAILS
        # ----------------------------------------------------

        with st.expander(
            f"Analysis & recommendation — "
            f"{device.get('device_id', 'unknown')}"
        ):

            st.markdown(
                f"**Diagnosis:** {label}"
            )

            st.markdown(
                f"**Reason:** {device['reason']}"
            )


            if label == "Optimal":

                st.success(
                    "Recommendation: "
                    "No immediate action required."
                )


            elif label == "Attenuated Signal":

                st.error(
                    "Recommendation: "
                    "Check walls, obstructions "
                    "and AP placement."
                )


            elif label == "Far Distance":

                st.warning(
                    "Recommendation: "
                    "Move closer to the AP "
                    "or improve coverage."
                )


            elif label == "Hardware Limited":

                st.warning(
                    "Recommendation: "
                    "Check the client's "
                    "Wi-Fi hardware capability."
                )


            elif label == "Congestion":

                st.warning(
                    "Recommendation: "
                    "Investigate channel utilization "
                    "and band selection."
                )


            else:

                st.info(
                    "Recommendation: "
                    "Collect more telemetry "
                    "before making a network change."
                )


            st.caption(

                f"Raw RSSI: "
                f"{device.get('rssi_raw', device.get('rssi'))} dBm"
                f" · Smoothed RSSI: "
                f"{device.get('rssi')} dBm"
                f" · Retry rate: "
                f"{device.get('retry_rate')}%"
                f" · Band: "
                f"{device.get('band', 'n/a')}"
                f" · Standard: "
                f"{device.get('standard', 'n/a')}"

            )


            # ------------------------------------------------
            # TICKET BUTTON
            # ------------------------------------------------

            if label != "Optimal":

                ticket_key = (
                    "ticket_"
                    + str(device.get("device_id"))
                )

                if st.button(
                    f"🎫 File Ticket for "
                    f"{device.get('device_id')}",
                    key=ticket_key
                ):

                    payload = {

                        "device_id":
                            device.get(
                                "device_id"
                            ),

                        "issue":
                            label,

                        "reason":
                            device.get(
                                "reason",
                                ""
                            )

                    }

                    try:

                        response = requests.post(
                            TICKET_URL,
                            json=payload,
                            timeout=3
                        )


                        if response.status_code == 200:

                            result = response.json()

                            st.success(

                                "Ticket filed successfully! "
                                f"ID: "
                                f"{result.get('ticket_id', 'N/A')} "
                                f"· Status: "
                                f"{result.get('status', 'created')}"

                            )

                        else:

                            st.error(
                                "Ticket backend returned "
                                f"HTTP {response.status_code}"
                            )


                    except Exception as e:

                        st.error(
                            f"Ticket server connection error: {e}"
                        )


# ============================================================
# WALL / DISTANCE OVERLAY
# ============================================================

st.markdown("""

<div class="card">

    <div class="ct">
        Wall / Distance Overlay
    </div>

    <div class="cs">
        RSSI-derived implied position ·
        router at center ·
        rings show increasing distance
    </div>

""", unsafe_allow_html=True)


map_fig = go.Figure()


# ------------------------------------------------------------
# DISTANCE RINGS
# ------------------------------------------------------------

for radius in [2, 5, 10, 15]:

    theta = [

        i / 120 * 2 * math.pi

        for i in range(121)

    ]

    x = [
        radius * math.cos(a)
        for a in theta
    ]

    y = [
        radius * math.sin(a)
        for a in theta
    ]


    map_fig.add_trace(

        go.Scatter(

            x=x,
            y=y,

            mode="lines",

            line=dict(
                color="rgba(100,145,185,.20)",
                dash="dot",
                width=1
            ),

            hoverinfo="skip",

            showlegend=False

        )

    )


# ------------------------------------------------------------
# ROUTER
# ------------------------------------------------------------

map_fig.add_trace(

    go.Scatter(

        x=[0],
        y=[0],

        mode="markers+text",

        text=["★ Router"],

        textposition="top center",

        marker=dict(

            size=22,

            symbol="star",

            color="#22c55e",

            line=dict(
                color="#e8fff0",
                width=2
            )

        ),

        textfont=dict(
            size=11,
            color="#f1f6fb"
        ),

        hovertemplate=(
            "<b>Router / Access Point</b>"
            "<extra></extra>"
        ),

        showlegend=False

    )

)


# ------------------------------------------------------------
# DEVICES ON MAP
# ------------------------------------------------------------

number_devices = max(
    len(devices),
    1
)


map_color = {

    "Optimal": "#22c55e",

    "Hardware Limited": "#f59e0b",

    "Far Distance": "#f59e0b",

    "Attenuated Signal": "#ef4444",

    "Congestion": "#a855f7",

    "Device-Specific Issue": "#ef4444",

    "Insufficient Information": "#94a3b8"

}


for index, device in enumerate(devices):

    distance = distance_from_rssi(
        device["rssi"]
    )


    angle = (

        (2 * math.pi / number_devices)
        * index

        + math.pi / 8

    )


    x = distance * math.cos(angle)

    y = distance * math.sin(angle)


    color = map_color.get(

        device["diagnosis_label"],

        "#94a3b8"

    )


    # Connector

    map_fig.add_trace(

        go.Scatter(

            x=[0, x],
            y=[0, y],

            mode="lines",

            line=dict(

                color="rgba(120,155,190,.10)",

                width=1

            ),

            hoverinfo="skip",

            showlegend=False

        )

    )


    # Device

    map_fig.add_trace(

        go.Scatter(

            x=[x],
            y=[y],

            mode="markers+text",

            text=[
                device.get(
                    "device_id",
                    "device"
                )
            ],

            textposition="bottom center",

            marker=dict(

                size=15,

                color=color,

                line=dict(
                    color="#edf5ff",
                    width=1.3
                )

            ),

            textfont=dict(

                size=10,

                color="#dce7f2"

            ),

            hovertemplate=(

                f"<b>"
                f"{device.get('device_id', 'device')}"
                f"</b>"

                f"<br>RSSI: "
                f"{device['rssi']:.1f} dBm"

                f"<br>SNR: "
                f"{device['snr']:.1f} dB"

                f"<br>Retry: "
                f"{device['retry_rate']:.2f}%"

                f"<br>Estimated distance: "
                f"{distance} m"

                f"<br>Diagnosis: "
                f"{device['diagnosis_label']}"

                "<extra></extra>"

            ),

            showlegend=False

        )

    )


map_fig.update_layout(

    height=430,

    margin=dict(
        l=10,
        r=10,
        t=10,
        b=10
    ),

    paper_bgcolor="rgba(0,0,0,0)",

    plot_bgcolor="rgba(0,0,0,0)",

    xaxis=dict(
        visible=False,
        scaleanchor="y",
        scaleratio=1
    ),

    yaxis=dict(
        visible=False
    ),

    hoverlabel=dict(

        bgcolor="#0b1829",

        bordercolor="#294764",

        font=dict(
            color="#fff"
        )

    )

)


st.plotly_chart(

    map_fig,

    use_container_width=True,

    config={
        "displayModeBar": False
    }

)

st.markdown(
    "</div>",
    unsafe_allow_html=True
)


# ============================================================
# FOOTER
# ============================================================

st.markdown(
    """
    <div style="
        text-align:center;
        color:#4d647b;
        font-size:.65rem;
        margin-top:1.2rem;
    ">
        Wi-Fi Band Analyzer ·
        Real Linux telemetry ·
        Diagnostic intelligence
    </div>
    """,
    unsafe_allow_html=True
)


# ============================================================
# AUTO REFRESH
# ============================================================

if auto_refresh:

    time.sleep(3)

    st.rerun()
