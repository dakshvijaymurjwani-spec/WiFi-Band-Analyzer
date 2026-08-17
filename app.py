import os
import sys
import time

import streamlit as st

sys.path.append(os.path.dirname(__file__))
from data_source import get_devices
from diagnostic_engine import classify, smooth

st.set_page_config(page_title="Wi-Fi Band Analyzer", layout="wide")
st.title("📡 Wi-Fi Band Analyzer")
st.caption("Live diagnostic view of connected devices")

status = st.empty()
placeholder = st.empty()

COLOR_MAP = {
    "Optimal": "🟢",
    "Hardware Limited": "🟡",
    "Far Distance": "🟠",
    "Attenuated Signal": "🔴",
    "Congestion": "🟣",
    "Device-Specific Issue": "🔵",
    "Insufficient Information": "⚪",
}

while True:
    devices = get_devices()

    for d in devices:
        smooth(d)
        label, reason = classify(d, network_devices=devices)
        d["diagnosis"] = f"{COLOR_MAP.get(label, '⚪')} {label}"
        d["reason"] = reason

    src = devices[0].get("source", "unknown") if devices else "none"
    with status.container():
        if src == "live":
            st.success(f"Data source: LIVE — {len(devices)} device(s) from the AP")
        else:
            st.warning(f"Data source: {src.upper()} — not measured data")

    with placeholder.container():
        cols = ["device_id", "band", "standard", "rssi", "snr",
                "retry_rate", "diagnosis"]
        st.dataframe(
            [{k: d.get(k) for k in cols} for d in devices],
            use_container_width=True,
        )
        st.subheader("Reasoning trace")
        for d in devices:
            with st.expander(f"{d['device_id']} — {d['diagnosis']}"):
                st.write(d["reason"])
                if d.get("data_quality"):
                    st.warning(f"Data quality — {d['data_quality']}")
                st.caption(
                    f"raw rssi={d.get('rssi_raw')}dBm  "
                    f"smoothed={d.get('rssi')}dBm  "
                    f"bands seen={list((d.get('band_rssi') or {}).keys())}  "
                    f"capability={d.get('capability_confidence', 'n/a')}  "
                    f"AP offered 5GHz={d.get('ap_offered_5ghz', 'n/a')}"
                )

    time.sleep(3)
