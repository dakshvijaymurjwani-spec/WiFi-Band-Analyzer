from wifi_standards import estimate_distance_from_rssi, get_max_rate, estimate_wall_attenuation

NETWORK_MAX_STANDARD = "wifi6e"


class KalmanFilter1D:
    """
    Smooths a noisy signal (RSSI/SNR) without a motion model.
    Same technique used across RSSI-denoising research — pairs well with
    the log-distance path-loss model in wifi_standards.py.
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


device_filters = {}


def smooth(device):
    did = device["device_id"]
    if did not in device_filters:
        device_filters[did] = {
            "rssi": KalmanFilter1D(),
            "snr": KalmanFilter1D(measurement_variance=2.0),
        }
    device["rssi"] = device_filters[did]["rssi"].update(device["rssi"])
    device["snr"] = device_filters[did]["snr"].update(device["snr"])
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
    # --- Hardware Limited ---
    if device["standard"] == "wifi4" and device["band"] == "2.4GHz":
        return "Hardware Limited", (
            f"Device max standard is {device['standard']}, "
            f"below network's {NETWORK_MAX_STANDARD}"
        ), 95  # capability mismatch is a hard fact, not a fuzzy reading -> high confidence

    # --- Attenuated Signal ---
    if device["rssi"] < -70 and device["snr"] < 15:
        _, atten_db, walls = estimate_wall_attenuation(device["rssi"], freq_mhz)
        wall_note = f" — consistent with ~{walls} wall(s) of excess attenuation ({atten_db}dB)" if walls > 0 else ""
        return "Attenuated Signal", (
            f"Weak RSSI + low SNR indicates obstruction{wall_note}"
        )
    # --- Far Distance (now with estimated distance in meters) ---
    # --- Far Distance ---
    if device["rssi"] < -75 and device["snr"] >= 15:
        est_distance, _, _ = estimate_wall_attenuation(device["rssi"], freq_mhz)
        return "Far Distance", (
            f"Low RSSI but decent SNR ({device['snr']}dB) indicates pure distance "
            f"rather than obstruction — estimated ~{est_distance}m from AP"
        )

    # --- Congestion ---
    if device["retry_rate"] > 15:
        margin = device["retry_rate"] - 15
        return "Congestion", (
            f"Retry rate {device['retry_rate']}% high despite decent signal"
        ), _confidence(margin, scale=15)

    # --- Device-Specific Issue (multi-device check) ---
    if network_devices and len(network_devices) > 1:
        avg_rssi = sum(d["rssi"] for d in network_devices) / len(network_devices)
        if device["rssi"] < avg_rssi - 15:
            margin = (avg_rssi - 15) - device["rssi"]
            return "Device-Specific Issue", (
                f"RSSI {device['rssi']}dBm is far worse than network average "
                f"({avg_rssi:.1f}dBm) — likely local to this device, not the network"
            ), _confidence(margin)

    # --- Optimal (now checks against theoretical max PHY rate if provided) ---
    if device["rssi"] >= -70 and device["snr"] >= 15 and device["retry_rate"] <= 15:
        max_rate = get_max_rate(device["standard"])
        phy_rate = device.get("phy_rate")  # optional field, only checked if present
        if phy_rate is not None and max_rate:
            pct_of_max = round((phy_rate / max_rate) * 100)
            if pct_of_max < 50:
                # Good signal but running far below theoretical max -> likely congestion,
                # not truly optimal, even though retry rate looked fine
                return "Congestion", (
                    f"Signal is healthy but PHY rate {phy_rate}Mbps is only "
                    f"{pct_of_max}% of {device['standard']}'s {max_rate}Mbps max "
                    "— likely channel contention"
                ), 70
            return "Optimal", (
                f"Signal and standard both healthy, PHY rate at {pct_of_max}% of "
                f"theoretical max ({max_rate}Mbps for {device['standard']})"
            ), 90
        return "Optimal", "Signal and standard both healthy", 85

    # --- Fallback ---
    return "Insufficient Information", (
        "Telemetry doesn't clearly match any category — "
        "needs more samples or manual review"
    ), 0


if __name__ == "__main__":
    from synthetic_generator import generate_device, DEVICE_PROFILES

    devices = [
        generate_device(f"dev{i}", profile)
        for i, profile in enumerate(DEVICE_PROFILES.keys())
    ]

    print("Smoothing (2 passes per device):")
    for d in devices:
        raw_rssi = d["rssi"]
        smooth(d)
        smooth(d)
        print(f"  {d['device_id']:6s} raw_rssi={raw_rssi} -> smoothed={d['rssi']}")

    print("\nClassification (with distance estimate, PHY-rate check, confidence):")
    for d in devices:
        label, reason, confidence = classify(d, network_devices=devices)
        print(f"  {d['device_id']:6s} ({d['profile']:11s}) -> {label:22s} "
              f"[{confidence}%] | {reason}")
