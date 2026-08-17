aimport streamlit as st
import time
import sys
import os
import requests

sys.path.append(os.path.dirname(__file__))
from synthetic_generator import generate_device, DEVICE_PROFILES
from diagnostic_engine import classify

st.set_page_config(page_title="Wi-Fi Band Analyzer & Ticketing", layout="wide")
st.title("📡 Wi-Fi Band Analyzer & Integrated Ticketing Dashboard")
st.caption("Live diagnostic view of connected devices with backend integration")

placeholder = st.empty()

COLOR_MAP = {
    "Optimal": "🟢",
    "Hardware Limited": "🟡",
    "Far Distance": "🟠",
    "Attenuated Signal": "🔴",
    "Congestion": "🟣",
}

counter = 0
while True:
    counter += 1
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
        st.subheader("Reasoning trace & Backend Ticketing")
        for d in devices:
            with st.expander(f"{d['device_id']} — {d['diagnosis']}"):
                st.write(d["reason"])
                
                unique_key = f"btn_{d['device_id']}_{counter}"
                if st.button(f"File Ticket for {d['device_id']}", key=unique_key):
                    try:
                        payload = {
                            "device_id": d["device_id"], 
                            "issue": d["diagnosis"], 
                            "reason": d["reason"]
                        }
                        response = requests.post("http://localhost:6000/ticket", json=payload)
                        if response.status_code == 200:
                            res_data = response.json()
                            st.success(f"Ticket Filed! ID: {res_data.get('ticket_id')} (Status: {res_data.get('status')})")
                        else:
                            st.error("Failed to reach backend server.")
                    except Exception as e:
                        st.error(f"Connection error: {e}")

    time.sleep(3)
