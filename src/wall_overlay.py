"""
Wall / Distance overlay.
 
Idea (from the log-distance path-loss research cited in the writeup):
  predicted_rssi(d) = tx_power - 10 * n * log10(d)
 
If we invert this, a measured RSSI implies a "distance-only" estimate of
where the device should be. We plot each device on a 2D sketch (router at
the center) at that implied distance, at an evenly spaced angle (we don't
have real angle-of-arrival data, so angle is just for visual separation).
 
We color each point by the GAP between:
  - the RSSI you'd expect at that distance in free space (n ~ 2-3), and
  - the RSSI you'd expect at that distance with typical indoor obstruction (n ~ 4-5)
 
A device whose actual RSSI sits far below even the "obstructed" curve is
flagged as wall-attenuated rather than just far away.
"""
import math
import plotly.graph_objects as go
 
TX_POWER = -30       # dBm at 1 meter, typical for a home AP
N_FREE = 2.2          # path-loss exponent, open air / line of sight
N_OBSTRUCTED = 4.2     # path-loss exponent, through walls (indoor range 3-5)
 
 
def implied_distance(rssi, n=3.0, tx_power=TX_POWER):
    """Invert the log-distance model to estimate distance in meters."""
    return round(10 ** ((tx_power - rssi) / (10 * n)), 2)
 
 
def predicted_rssi(distance_m, n, tx_power=TX_POWER):
    if distance_m <= 0:
        distance_m = 0.1
    return tx_power - 10 * n * math.log10(distance_m)
 
 
def classify_wall_vs_distance(device):
    """
    Returns (distance_m, gap_db, label) for one device dict
    (must contain 'rssi').
    """
    d = implied_distance(device["rssi"], n=N_OBSTRUCTED)
    free_space_expected = predicted_rssi(d, N_FREE)
    gap = round(free_space_expected - device["rssi"], 1)  # how much worse than free space
 
    if gap > 15:
        label = "Heavily attenuated (walls)"
    elif gap > 7:
        label = "Some attenuation"
    else:
        label = "Mostly distance"
    return d, gap, label
 
 
def build_overlay_figure(devices):
    """Build a plotly figure: router at center, devices placed by implied
    distance, colored by attenuation gap."""
    fig = go.Figure()
 
    # Router marker
    fig.add_trace(go.Scatter(
        x=[0], y=[0], mode="markers+text", text=["Router"],
        textposition="top center",
        marker=dict(size=18, symbol="star", color="#f2c744"),
        showlegend=False,
    ))
 
    n = max(len(devices), 1)
    for i, dev in enumerate(devices):
        distance, gap, label = classify_wall_vs_distance(dev)
        angle = (2 * math.pi / n) * i
        x = distance * math.cos(angle)
        y = distance * math.sin(angle)
 
        color = "#e74c3c" if gap > 15 else ("#f39c12" if gap > 7 else "#2ecc71")
 
        fig.add_trace(go.Scatter(
            x=[x], y=[y], mode="markers+text",
            text=[dev["device_id"]],
            textposition="bottom center",
            marker=dict(size=14, color=color),
            hovertext=(
                f"{dev['device_id']}<br>"
                f"RSSI: {dev['rssi']} dBm<br>"
                f"Implied distance: {distance} m<br>"
                f"Attenuation gap: {gap} dB<br>"
                f"{label}"
            ),
            hoverinfo="text",
            showlegend=False,
        ))
 
    # distance rings for reference
    for r in [5, 10, 15, 20]:
        theta = [t / 100 * 2 * math.pi for t in range(101)]
        fig.add_trace(go.Scatter(
            x=[r * math.cos(t) for t in theta],
            y=[r * math.sin(t) for t in theta],
            mode="lines", line=dict(color="rgba(150,150,150,0.25)", dash="dot"),
            showlegend=False, hoverinfo="skip",
        ))
 
    fig.update_layout(
        title="Wall / Distance Overlay (implied position from RSSI)",
        xaxis=dict(visible=False, scaleanchor="y"),
        yaxis=dict(visible=False),
        height=500,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig