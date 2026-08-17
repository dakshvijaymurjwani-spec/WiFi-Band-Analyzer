from wifi_standards import estimate_distance_from_rssi, get_max_rate, estimate_wall_attenuation

NETWORK_MAX_STANDARD = "wifi6e"


class KalmanFilter1D:
    """
    Base scalar Kalman filter — smooths a noisy signal (RSSI/SNR) without a
    motion model. Kept as-is for backward compatibility.
    """
    def __init__(self, process_variance=1e-3, measurement_variance=4.0):
        self.q = process_variance
        self.r = measurement_variance
        self.estimate = None
        self.error_estimate = 1.0

    def update(self, measurement):
        if self.estimate is None:
            self.estimate = measurement
            return self.estimate
        self.error_estimate += self.q
        k = self.error_estimate / (self.error_estimate + self.r)
        self.estimate += k * (measurement - self.estimate)
        self.error_estimate *= (1 - k)
        return round(self.estimate, 2)


class AdaptiveKalmanFilter1D(KalmanFilter1D):
    """
    Industry-grade refinement over the base filter:
    1. Outlier rejection — a reading far outside recent variance (e.g. a
       spike from interference or a corrupted frame) is down-weighted
       instead of blended in directly like a normal sample.
    2. Adaptive measurement variance — R is estimated from recent residuals
       instead of fixed, so the filter automatically trusts noisy periods
       less and clean periods more, without manual re-tuning.
    """
    def __init__(self, process_variance=1e-3, measurement_variance=4.0,
                 outlier_threshold=3.0, adapt_rate=0.05):
        super().__init__(process_variance, measurement_variance)
        self.outlier_threshold = outlier_threshold
        self.adapt_rate = adapt_rate
        self.recent_residuals = []

    def update(self, measurement):
        if self.estimate is None:
            self.estimate = measurement
            return self.estimate

        residual = measurement - self.estimate
        std_est = (self.error_estimate + self.r) ** 0.5
        is_outlier = abs(residual) > self.outlier_threshold * std_est

        self.error_estimate += self.q
        k = self.error_estimate / (self.error_estimate + self.r)
        if is_outlier:
            k *= 0.2  # trust this reading much less, don't ignore entirely

        self.estimate += k * residual
        self.error_estimate *= (1 - k)

        self.recent_residuals.append(abs(residual))
        if len(self.recent_residuals) > 5:
            self.recent_residuals.pop(0)
        avg_residual = sum(self.recent_residuals) / len(self.recent_residuals)
        target_r = max(1.0, avg_residual * 2)
        self.r += self.adapt_rate * (target_r - self.r)

        return round(self.estimate, 2)


device_filters = {}
device_history = {}  # device_id -> list of recent smoothed RSSI values


def track_trend(device):
    """
    Computes a simple trend label from the last few smoothed RSSI readings:
    Improving, Degrading, or Stable. Adds time-series awareness on top of
    the single-snapshot classifier below.
    """
    did = device["device_id"]
    hist = device_history.setdefault(did, [])
    hist.append(device["rssi"])
    if len(hist) > 5:
        hist.pop(0)

    if len(hist) < 3:
        return "Stable", 0.0

    delta = hist[-1] - hist[0]
    if delta > 3:
        return "Improving", round(delta, 1)
    if delta < -3:
        return "Degrading", round(delta, 1)
    return "Stable", round(delta, 1)


def smooth(device):
    did = device["device_id"]
    if did not in device_filters:
        device_filters[did] = {
            "rssi": AdaptiveKalmanFilter1D(),
            "snr": AdaptiveKalmanFilter1D(measurement_variance=2.0),
        }
    device["rssi"] = device_filters[did]["rssi"].update(device["rssi"])
    device["snr"] = device_filters[did]["snr"].update(device["snr"])
    device["trend"], device["trend_delta"] = track_trend(device)
    return device


def _confidence(margin, scale=10):
    """
    Turns 'how far past the threshold' into a rough 0-100 confidence score.
    margin: how many units past the threshold the value is (always >= 0 when called correctly)
    scale: how many units of margin count as 'fully confident'
    """
    score = min(100, round((margin / scale) * 100))
    return max(score, 40)  # never show below 40 for a rule that did fire


def classify(device, network_devices=None, freq_mhz=5000):
    """
    Returns (label, reason, confidence). Falls back to 'Insufficient Information'
    when no rule confidently fires, instead of forcing a guess.
    """
    trend_note = ""
    if device.get("trend") == "Degrading":
        trend_note = f" (trending down {device.get('trend_delta', 0)}dB recently)"
    elif device.get("trend") == "Improving":
        trend_note = f" (trending up {abs(device.get('trend_delta', 0))}dB recently)"

    # --- Hardware Limited ---
    if device["standard"] == "wifi4" and device["band"] == "2.4GHz":
        return "Hardware Limited", (
            f"Device max standard is {device['standard']}, "
            f"below network's {NETWORK_MAX_STANDARD}"
        ), 95

    # --- Signal Critically Weak (Overrides others if completely unusable) ---
    if device["rssi"] < -85 and device["snr"] < 8:
        return "Signal Critically Weak", (
            f"RSSI {device['rssi']}dBm / SNR {device['snr']}dB is at the edge of "
            "usability — root cause (distance vs. obstruction) can't be reliably "
            f"distinguished at this signal level{trend_note}"
        ), 30

    # --- Attenuated Signal ---
    if device["rssi"] < -70 and device["snr"] < 15:
        _, atten_db, walls = estimate_wall_attenuation(device["rssi"], freq_mhz)
        wall_note = f" — consistent with ~{walls} wall(s) of excess attenuation" if walls > 0 else ""
        return "Attenuated Signal", (
            f"RSSI {device['rssi']}dBm and SNR {device['snr']}dB both low"
            f"{wall_note}{trend_note}"
        ), 85

    # --- Far Distance ---
    if device["rssi"] < -75 and device["snr"] >= 15:
        est_distance, _, _ = estimate_wall_attenuation(device["rssi"], freq_mhz)
        return "Far Distance", (
            f"Low RSSI but decent SNR ({device['snr']}dB) indicates pure distance "
            f"rather than obstruction — estimated ~{est_distance}m from AP{trend_note}"
        ), 85

    # --- Congestion ---
    if device.get("retry_rate", 0) > 15:
        margin = device["retry_rate"] - 15
        return "Congestion", (
            f"Retry rate {device['retry_rate']}% high despite decent signal{trend_note}"
        ), _confidence(margin, scale=15)

    # --- Device-Specific Issue (multi-device check) ---
    if network_devices and len(network_devices) > 1:
        avg_rssi = sum(d["rssi"] for d in network_devices) / len(network_devices)
        if device["rssi"] < avg_rssi - 15:
            margin = (avg_rssi - 15) - device["rssi"]
            return "Device-Specific Issue", (
                f"RSSI {device['rssi']}dBm is far worse than network average "
                f"({avg_rssi:.1f}dBm) — likely local to this device, not the network{trend_note}"
            ), _confidence(margin)

    # --- Optimal (checks against theoretical max PHY rate if provided) ---
    if device["rssi"] >= -70 and device["snr"] >= 15 and device.get("retry_rate", 0) < 15:
        max_rate = get_max_rate(device["standard"])
        phy_rate = device.get("phy_rate")
        if phy_rate is not None and max_rate:
            pct_of_max = round((phy_rate / max_rate) * 100)
            if pct_of_max < 50:
                return "Congestion", (
                    f"Signal is healthy but PHY rate {phy_rate}Mbps is only "
                    f"{pct_of_max}% of {device['standard']}'s {max_rate}Mbps max "
                    f"— likely channel contention{trend_note}"
                ), 70
            return "Optimal", (
                f"Signal and standard both healthy, PHY rate at {pct_of_max}% of "
                f"theoretical max ({max_rate}Mbps for {device['standard']}){trend_note}"
            ), 90
        return "Optimal", f"Signal and standard both healthy{trend_note}", 85

    # --- Fallback ---
    return "Insufficient Information", (
        "Telemetry doesn't clearly match any category — needs more samples or manual review"
    ), 0


if __name__ == "__main__":
    from synthetic_generator import generate_device, DEVICE_PROFILES

    devices = [
        generate_device(f"dev{i}", profile)
        for i, profile in enumerate(DEVICE_PROFILES.keys())
    ]

    print("Smoothing (3 passes per device, to populate trend history):")
    for _ in range(3):
        for d in devices:
            smooth(d)
    for d in devices:
        print(f"  {d['device_id']:6s} smoothed_rssi={d['rssi']} trend={d['trend']} ({d['trend_delta']}dB)")

    print("\nClassification (with distance estimate, PHY-rate check, confidence, trend):")
    for d in devices:
        label, reason, confidence = classify(d, network_devices=devices)
        print(f"  {d['device_id']:6s} ({d['profile']:11s}) -> {label:22s} "
              f"[{confidence}%] | {reason}")
