import streamlit as st
import time
import sys
import os

sys.path.append(os.path.dirname(__file__))
from synthetic_generator import generate_device, DEVICE_PROFILES
from diagnostic_engine import classify

st.set_page_config(page_title="Wi-Fi Band Analyzer", layout="wide")
st.title("📡 Wi-Fi Band Analyzer")
st.caption("Live diagnostic view of connected devices")

placeholder = st.empty()

COLOR_MAP = {
    "Optimal": "🟢",
    "Hardware Limited": "🟡",
    "Far Distance": "🟠",
    "Attenuated Signal": "🔴",
    "Congestion": "🟣",
}

while True:
    devices = []
    for i, profile in enumerate(DEVICE_PROFILES.keys()):
        d = generate_device(f"dev{i}", profile)
        label, reason = classify(d)
        d["diagnosis"] = f"{COLOR_MAP.get(label, '')} {label}"
        d["reason"] = reason
        devices.append(d)

    with placeholder.container():
        cols = ["device_id", "band", "standard", "rssi", "snr", "retry_rate", "diagnosis"]
        st.dataframe(
            [{k: d[k] for k in cols} for d in devices],
            use_container_width=True,
        )
        st.subheader("Reasoning trace")
        for d in devices:
            with st.expander(f"{d['device_id']} — {d['diagnosis']}"):
                st.write(d["reason"])

    time.sleep(3)
