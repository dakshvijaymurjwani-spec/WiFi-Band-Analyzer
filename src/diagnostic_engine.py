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


# one filter pair per device — each device's signal has its own noise profile
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


def classify(device, network_devices=None):
    """
    Returns (label, reason). Falls back to 'Insufficient Information'
    when no rule confidently fires, instead of forcing a guess —
    mirrors the confidence-gated decision tree pattern from the
    Cisco-style root-cause patents.
    """
    if device["standard"] == "wifi4" and device["band"] == "2.4GHz":
        return "Hardware Limited", (
            f"Device max standard is {device['standard']}, "
            f"below network's {NETWORK_MAX_STANDARD}"
        )

    if device["rssi"] < -70 and device["snr"] < 15:
        return "Attenuated Signal", (
            f"RSSI {device['rssi']}dBm and SNR {device['snr']}dB both low "
            "— likely obstruction, not distance alone"
        )

    if device["rssi"] < -75 and device["snr"] >= 15:
        return "Far Distance", (
            f"RSSI {device['rssi']}dBm low but SNR {device['snr']}dB reasonable "
            "— likely pure distance"
        )

    if device["retry_rate"] > 15:
        return "Congestion", (
            f"Retry rate {device['retry_rate']}% high despite decent signal"
        )

    if network_devices and len(network_devices) > 1:
        avg_rssi = sum(d["rssi"] for d in network_devices) / len(network_devices)
        if device["rssi"] < avg_rssi - 15:
            return "Device-Specific Issue", (
                f"RSSI {device['rssi']}dBm is far worse than network average "
                f"({avg_rssi:.1f}dBm) — likely local to this device, not the network"
            )

    if device["rssi"] >= -70 and device["snr"] >= 15 and device["retry_rate"] <= 15:
        return "Optimal", "Signal and standard both healthy"

    return "Insufficient Information", (
        "Telemetry doesn't clearly match any category — "
        "needs more samples or manual review"
    )


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

    print("\nClassification (with single-vs-multi-device check):")
    for d in devices:
        label, reason = classify(d, network_devices=devices)
        print(f"  {d['device_id']:6s} ({d['profile']:11s}) -> {label:22s} | {reason}")
