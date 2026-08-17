NETWORK_MAX_STANDARD = "wifi6e"

# A wall attenuates 5/6 GHz much harder than 2.4 GHz.
# Pure distance degrades both roughly proportionally.
# A cross-band gap wider than this is evidence of an obstruction.
# Tune this from your own walk test — see README.
WALL_DELTA_DB = 12


class KalmanFilter1D:
    """
    Smooths a noisy signal (RSSI/SNR) without a motion model.

    Tuning note: q/r sets the response speed. q=0.05, r=2.0 gives a
    steady-state gain around 0.15, so the estimate tracks a real change
    in roughly 7 samples (~14s at 2s polling). The earlier q=1e-3, r=4.0
    gave a gain near 0.016 — about 60 samples, which made the live
    walk test appear frozen.
    """

    def __init__(self, process_variance=0.05, measurement_variance=2.0):
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
    """Smooths in place but preserves the raw reading for the evidence trace."""
    did = device["device_id"]
    if did not in device_filters:
        device_filters[did] = {
            "rssi": KalmanFilter1D(),
            "snr": KalmanFilter1D(measurement_variance=1.5),
        }
    device.setdefault("rssi_raw", device["rssi"])
    device.setdefault("snr_raw", device["snr"])
    device["rssi"] = device_filters[did]["rssi"].update(device["rssi"])
    device["snr"] = device_filters[did]["snr"].update(device["snr"])
    return device


DUAL_BAND_STANDARDS = ("wifi5", "wifi6", "wifi6e", "wifi7")


def _capability(device):
    """
    Can this device use 5/6 GHz? Returns 'capable', 'not_capable', or 'unknown'.

    The negotiated PHY mode is only weak evidence, and it cuts one way:
    a VHT/HE/EHT client is effectively always dual-band, so that proves
    capability. The converse does NOT hold. A client reports plain HT when
    the AP only advertises HT — so 'wifi4 on 2.4 GHz' may be describing our
    own access point's configuration, not the client's radio.

    Calling that 'Hardware Limited' was a false positive that fired for every
    modern phone. The honest answer is 'unknown' until either:
      - we see the device on 5/6 GHz             -> capable
      - the AP offers 5/6 GHz and it never shows -> not capable
    """
    if device.get("supports_5ghz") is True:
        return "capable"
    if device.get("standard") in DUAL_BAND_STANDARDS:
        return "capable"
    if device.get("supports_5ghz") is False and device.get("ap_offered_5ghz"):
        return "not_capable"
    if device.get("supports_5ghz") is False and "ap_offered_5ghz" not in device:
        # Explicit ground truth with no AP context — synthetic data.
        return "not_capable"
    return "unknown"


def _wall_evidence(device):
    """
    Cross-band comparison: same device, both bands.
    Returns (has_evidence, delta_db).
    """
    seen = device.get("band_rssi") or {}
    r24 = seen.get("2.4GHz")
    r_high = seen.get("5GHz", seen.get("6GHz"))
    if r24 is None or r_high is None:
        return False, None
    return True, round(r24 - r_high, 1)


def classify(device, network_devices=None):
    """
    Returns (label, reason).

    Falls back to 'Insufficient Information' rather than forcing a
    low-confidence guess — the confidence-gated decision tree pattern
    from the Cisco-style root-cause patents.
    """
    rssi = device["rssi"]
    snr = device["snr"]
    retry = device.get("retry_rate", 0)
    band = device["band"]
    std = device.get("standard", "legacy")

    # ---- 1. Hardware ceiling: a capability test, not a current-band test ----
    cap = _capability(device)

    if cap == "not_capable":
        return "Hardware Limited", (
            f"Device negotiated {std} and never appeared on 5/6 GHz even though "
            f"the AP offered it — the radio is 2.4 GHz only, so no amount of "
            f"repositioning will help. Network offers {NETWORK_MAX_STANDARD}."
        )

    if cap == "unknown":
        return "Insufficient Information", (
            f"Device negotiated {std}, but the AP has only beaconed on {band} "
            f"so far — that cannot distinguish a 2.4-only radio from a capable "
            f"one. Switch the AP to 5 GHz and see whether this device follows."
        )

    # ---- 2. Capable device sitting on 2.4 GHz: the interesting case ----
    if band == "2.4GHz":
        has_ev, delta = _wall_evidence(device)
        if has_ev:
            if delta > WALL_DELTA_DB:
                return "Attenuated Signal", (
                    f"{std} device on 2.4 GHz. Cross-band gap is {delta}dB — "
                    f"wider than frequency alone explains, so an obstruction is "
                    f"attenuating 5 GHz. Move the device or the router out of the "
                    f"blocked path; new hardware won't help."
                )
            return "Far Distance", (
                f"{std} device on 2.4 GHz. Cross-band gap is only {delta}dB, "
                f"consistent with plain distance rather than a wall. "
                f"Move closer or add an access point."
            )
        return "Insufficient Information", (
            f"{std} device is on 2.4 GHz despite supporting 5 GHz — it likely "
            f"abandoned a weak 5 GHz signal. Need a 5 GHz sample from this "
            f"device to separate wall from distance. Trigger a band switch."
        )

    # ---- 3. On 5/6 GHz: signal quality rules ----
    if rssi < -70 and snr < 15:
        return "Attenuated Signal", (
            f"RSSI {rssi}dBm and SNR {snr}dB both poor on {band} — "
            f"likely obstruction rather than distance alone"
        )

    if rssi < -75 and snr >= 15:
        return "Far Distance", (
            f"RSSI {rssi}dBm is weak but SNR {snr}dB is reasonable — "
            f"consistent with pure distance"
        )

    if retry > 15:
        return "Congestion", (
            f"Retry rate {retry}% is high despite RSSI {rssi}dBm — "
            f"the channel is busy, not the link weak. Change channel."
        )

    # ---- 4. Is this device worse than its peers? ----
    if network_devices and len(network_devices) > 1:
        others = [d for d in network_devices
                  if d["device_id"] != device["device_id"]]
        if others:
            avg = sum(d["rssi"] for d in others) / len(others)
            if rssi < avg - 15:
                return "Device-Specific Issue", (
                    f"RSSI {rssi}dBm is {abs(rssi - avg):.0f}dB below the "
                    f"network average ({avg:.1f}dBm) — the problem is local to "
                    f"this device, not the network"
                )

    if rssi >= -67 and snr >= 20 and retry <= 15:
        return "Optimal", (
            f"RSSI {rssi}dBm, SNR {snr}dB, retries {retry}% — all healthy, "
            f"and the device is on its best available band"
        )

    return "Insufficient Information", (
        f"RSSI {rssi}dBm / SNR {snr}dB / retries {retry}% fall between "
        f"category boundaries — needs more samples before a confident call"
    )


if __name__ == "__main__":
    from synthetic_generator import DEVICE_PROFILES, generate_device

    devices = [generate_device(f"dev{i}", p)
               for i, p in enumerate(DEVICE_PROFILES.keys())]

    print("Smoothing:")
    for d in devices:
        raw = d["rssi"]
        smooth(d)
        smooth(d)
        print(f"  {d['device_id']:6s} raw={raw} -> smoothed={d['rssi']}")

    print("\nClassification:")
    for d in devices:
        label, reason = classify(d, network_devices=devices)
        print(f"  {d['device_id']:6s} ({d.get('profile', '?'):11s}) -> {label}")
        print(f"          {reason}")
