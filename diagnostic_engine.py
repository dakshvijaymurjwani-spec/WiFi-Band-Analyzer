"""Root-cause classification for Wi-Fi performance degradation.

Design commitments:

  * Evidence over inference. A label is only returned when the telemetry
    distinguishes it from its neighbours. "Insufficient Information" names
    the missing measurement instead of guessing.
  * Capability is not the current band. A device on 2.4 GHz is not
    hardware-limited; a device that *cannot reach* 5/6 GHz is.
  * Wall versus distance needs two measurements. One RSSI reading cannot
    separate them — the cross-band gap can, because an obstruction
    attenuates 5/6 GHz far harder than 2.4 GHz while distance degrades
    both roughly proportionally.
"""
from wifi_standards import (
    estimate_wall_attenuation,
    expected_max_rate,
    get_max_rate,
)

NETWORK_MAX_STANDARD = "wifi6e"

# A wall attenuates 5/6 GHz much harder than 2.4 GHz; distance degrades both
# roughly proportionally. A cross-band gap wider than this is evidence of an
# obstruction. Starting value — tune it with a line-of-sight pair and a
# through-wall pair, and set the threshold where the two separate.
WALL_DELTA_DB = 12

# PHY rate below this fraction of the band-realistic ceiling is suspicious,
# but not on its own a diagnosis — see RETRY_CORROBORATION.
PHY_UNDERPERFORM_PCT = 40

# Rate shortfall alone has too many benign causes (power save, a 1x1 radio,
# a narrow channel, rate-control backoff). Congestion is only claimed when
# retries corroborate it.
RETRY_CORROBORATION = 5.0

MODERN_STANDARDS = ("wifi5", "wifi6", "wifi6e", "wifi7")


# ---------------------------------------------------------------------------
# Smoothing
# ---------------------------------------------------------------------------
class KalmanFilter1D:
    """Scalar Kalman filter — smooths a noisy signal without a motion model.

    Defaults give a steady-state gain near 0.15, so the estimate tracks a
    real change in roughly 7 samples (~14 s at 2 s polling). The original
    q=1e-3 / r=4.0 gave a gain near 0.016 — about 60 samples — which made
    the walk test appear frozen.
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


class AdaptiveKalmanFilter1D(KalmanFilter1D):
    """Kalman filter with outlier rejection and adaptive measurement variance.

    Two refinements over the base filter, and one correction that matters
    more than either:

    1. Outlier rejection — a reading far outside recent variance (an
       interference spike, a corrupted frame) is down-weighted rather than
       blended in at full gain.

    2. Adaptive R — measurement variance is estimated from recent residuals,
       so the filter trusts noisy periods less without manual re-tuning.
       Only non-outlier residuals train it; otherwise a genuine step change
       inflates R and slows the filter exactly when it needs to be fast.

    3. CONSECUTIVE-OUTLIER RECOVERY. A single 20 dB jump is noise. Three in
       a row in the same direction is a person walking away from the access
       point, and the correct conclusion is that the *estimate* is stale,
       not that the measurements are wrong. Without this, a sustained change
       is rejected indefinitely: the previous version still reported
       -60 dBm after 40 samples of a true -70, and never converged.
    """

    def __init__(self, process_variance=0.05, measurement_variance=2.0,
                 outlier_threshold=3.0, adapt_rate=0.05, outlier_patience=3):
        super().__init__(process_variance, measurement_variance)
        self.outlier_threshold = outlier_threshold
        self.adapt_rate = adapt_rate
        self.outlier_patience = outlier_patience
        self.recent_residuals = []
        self._run_length = 0
        self._run_sign = 0
        self.rejected = 0          # exposed for the evidence trace

    def update(self, measurement):
        if self.estimate is None:
            self.estimate = measurement
            return self.estimate

        residual = measurement - self.estimate
        std_est = (self.error_estimate + self.r) ** 0.5
        is_outlier = abs(residual) > self.outlier_threshold * std_est
        sign = 1 if residual > 0 else -1

        if is_outlier:
            self._run_length = self._run_length + 1 if sign == self._run_sign else 1
            self._run_sign = sign
            if self._run_length >= self.outlier_patience:
                # Sustained and one-directional: this is a real shift.
                is_outlier = False
                self.error_estimate = max(self.error_estimate, self.r)
                self._run_length = 0
            else:
                self.rejected += 1
        else:
            self._run_length = 0
            self._run_sign = 0

        self.error_estimate += self.q
        k = self.error_estimate / (self.error_estimate + self.r)
        if is_outlier:
            k *= 0.2

        self.estimate += k * residual
        self.error_estimate *= (1 - k)

        if not is_outlier:
            self.recent_residuals.append(abs(residual))
            if len(self.recent_residuals) > 5:
                self.recent_residuals.pop(0)
            avg = sum(self.recent_residuals) / len(self.recent_residuals)
            self.r += self.adapt_rate * (max(1.0, avg * 2) - self.r)

        return round(self.estimate, 2)


device_filters = {}
device_history = {}   # device_id -> recent smoothed RSSI


def track_trend(device, window=5, threshold=2.0):
    """Improving / Degrading / Stable from the last few smoothed readings.

    Adds time-series awareness on top of the single-snapshot classifier.
    """
    hist = device_history.setdefault(device["device_id"], [])
    hist.append(device["rssi"])
    if len(hist) > window:
        hist.pop(0)
    if len(hist) < 3:
        return "Stable", 0.0
    delta = hist[-1] - hist[0]
    if delta > threshold:
        return "Improving", round(delta, 1)
    if delta < -threshold:
        return "Degrading", round(delta, 1)
    return "Stable", round(delta, 1)


def smooth(device):
    """Smooth in place, preserving the raw reading for the evidence trace."""
    did = device["device_id"]
    if did not in device_filters:
        device_filters[did] = {
            "rssi": AdaptiveKalmanFilter1D(),
            "snr": AdaptiveKalmanFilter1D(measurement_variance=1.5),
        }
    device.setdefault("rssi_raw", device["rssi"])
    device.setdefault("snr_raw", device["snr"])
    device["rssi"] = device_filters[did]["rssi"].update(device["rssi"])
    device["snr"] = device_filters[did]["snr"].update(device["snr"])
    device["trend"], device["trend_delta"] = track_trend(device)
    return device


def reset_state():
    """Clear per-device filters and history. Call when the data source flips
    between live and synthetic, or the two blend into one estimate."""
    device_filters.clear()
    device_history.clear()


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------
def _confidence(margin, scale=10, floor=40):
    """Distance past the threshold, expressed as a rough 0-100 score."""
    return max(floor, min(100, round((margin / scale) * 100)))


def band_capability(device):
    """Can this device use 5/6 GHz? Returns (True | False | None, basis).

    None means genuinely unknown, which is a different thing from False and
    must not be reported as a hardware limitation.

      observed  — seen associated on 5 or 6 GHz
      phy       — VHT/HE/EHT negotiation implies a dual-band radio
      unknown   — plain HT or legacy: may be 2.4-only, or may just be
                  talking to a 2.4 GHz AP that never advertised better
    """
    if "supports_5ghz" in device:
        return bool(device["supports_5ghz"]), "observed"
    if device.get("standard") in MODERN_STANDARDS:
        return True, "phy"
    return None, "unknown"


def wall_evidence(device):
    """Cross-band RSSI gap for one device. Returns (has_evidence, delta_db)."""
    seen = device.get("band_rssi") or {}
    r24 = seen.get("2.4GHz")
    r_high = seen.get("5GHz", seen.get("6GHz"))
    if r24 is None or r_high is None:
        return False, None
    return True, round(r24 - r_high, 1)


def _trend_note(device):
    t = device.get("trend")
    if t == "Degrading":
        return f" (trending down {abs(device.get('trend_delta', 0))}dB)"
    if t == "Improving":
        return f" (trending up {abs(device.get('trend_delta', 0))}dB)"
    return ""


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
def classify(device, network_devices=None, freq_mhz=5000):
    """Returns (label, reason, confidence).

    Rule order is deliberate: capability first (a permanent property beats a
    transient reading), then unusability, then the band-specific tests.
    """
    rssi = device["rssi"]
    snr = device["snr"]
    retry = device.get("retry_rate", 0) or 0
    band = device.get("band", "5GHz")
    std = device.get("standard", "legacy")
    note = _trend_note(device)

    can_5, basis = band_capability(device)
    ap_offered_5 = device.get("ap_offered_5ghz")

    # -- 1. Hardware ceiling: a capability test, not a current-band test ----
    # Observed absence is proof only if the AP actually offered the band. On
    # a 2.4-only AP session every client looks 2.4-only, which is what made
    # the previous rule label every modern phone Hardware Limited.
    if can_5 is False and ap_offered_5 is not False:
        return "Hardware Limited", (
            f"Device negotiated {std} and has not appeared on 5/6 GHz while "
            f"the AP offered it — it cannot exceed 2.4 GHz rates regardless of "
            f"placement. Network offers {NETWORK_MAX_STANDARD}. New hardware "
            f"is the only fix.{note}"
        ), 95

    # -- 2. Unusable signal: decline to attribute a cause -------------------
    if rssi < -85 and snr < 8:
        return "Signal Critically Weak", (
            f"RSSI {rssi}dBm / SNR {snr}dB is at the edge of usability — "
            f"distance and obstruction cannot be separated at this signal "
            f"level. Restore basic coverage first, then re-diagnose.{note}"
        ), 30

    # -- 3. Capable device sitting on 2.4 GHz: the flagship case ------------
    if band == "2.4GHz" and can_5 is not False:
        has_ev, delta = wall_evidence(device)
        if has_ev:
            if delta > WALL_DELTA_DB:
                return "Attenuated Signal", (
                    f"{std} device fell back to 2.4 GHz. Cross-band gap is "
                    f"{delta}dB — wider than frequency alone explains, so an "
                    f"obstruction is attenuating 5 GHz. Move the device or the "
                    f"router out of the blocked path; new hardware won't "
                    f"help.{note}"
                ), _confidence(delta - WALL_DELTA_DB, scale=10, floor=60)
            return "Far Distance", (
                f"{std} device fell back to 2.4 GHz. Cross-band gap is only "
                f"{delta}dB, consistent with plain distance rather than an "
                f"obstruction. Move closer or add an access point.{note}"
            ), _confidence(WALL_DELTA_DB - delta, scale=10, floor=60)
        if can_5:
            return "Insufficient Information", (
                f"{std} device is on 2.4 GHz despite supporting 5 GHz — it "
                f"likely abandoned a weak 5 GHz signal. A 5 GHz sample from "
                f"this device is needed to separate wall from distance. "
                f"Trigger a band switch.{note}"
            ), 0
        return "Insufficient Information", (
            f"{std} device on 2.4 GHz and the AP has not offered 5/6 GHz this "
            f"session, so its capability is unproven ({basis}). Run the 5 GHz "
            f"AP to find out whether it can follow.{note}"
        ), 0

    # -- 4. Signal quality on 5/6 GHz --------------------------------------
    if rssi < -70 and snr < 15:
        _, atten_db, walls = estimate_wall_attenuation(rssi, freq_mhz)
        wall_note = (f" — excess path loss ~{atten_db}dB, on the order of "
                     f"{walls} interior wall(s)") if walls > 0 else ""
        return "Attenuated Signal", (
            f"RSSI {rssi}dBm and SNR {snr}dB both poor on {band}{wall_note}. "
            f"Single-band estimate: run the cross-band test to confirm "
            f"obstruction over distance.{note}"
        ), 70

    # Threshold is -70, not -75, deliberately: paired with the -70 Optimal
    # floor it partitions the RSSI axis with no gap. At -75 there was a dead
    # band from -71 to -75 where a weak-but-clean link matched no rule and
    # returned Insufficient Information, which then counted against network
    # health as though it were a fault.
    if rssi < -70 and snr >= 15:
        est_distance, _, _ = estimate_wall_attenuation(rssi, freq_mhz)
        return "Far Distance", (
            f"RSSI {rssi}dBm is weak but SNR {snr}dB is reasonable — "
            f"consistent with distance rather than obstruction. The model puts "
            f"the device around {est_distance}m from the AP.{note}"
        ), 75

    # -- 5. Congestion: retries are the primary evidence --------------------
    if retry > 15:
        return "Congestion", (
            f"Retry rate {retry}% is high despite RSSI {rssi}dBm — the channel "
            f"is busy, not the link weak. Change channel.{note}"
        ), _confidence(retry - 15, scale=15)

    # -- 6. Worse than its peers -------------------------------------------
    if network_devices and len(network_devices) > 1:
        others = [d for d in network_devices
                  if d.get("device_id") != device.get("device_id")]
        same_band = [d for d in others if d.get("band") == band] or others
        if same_band:
            avg = sum(d["rssi"] for d in same_band) / len(same_band)
            if rssi < avg - 15:
                return "Device-Specific Issue", (
                    f"RSSI {rssi}dBm is {abs(rssi - avg):.0f}dB below the "
                    f"average of its {len(same_band)} peer(s) on {band} "
                    f"({avg:.1f}dBm) — the problem is local to this device, "
                    f"not the network.{note}"
                ), _confidence((avg - 15) - rssi)

    # -- 7. Healthy --------------------------------------------------------
    if rssi >= -70 and snr >= 15 and retry <= 15:
        ceiling = expected_max_rate(std, band) or get_max_rate(std)
        phy = device.get("phy_rate")
        if phy and ceiling:
            pct = round(phy / ceiling * 100)
            if pct < PHY_UNDERPERFORM_PCT and retry > RETRY_CORROBORATION:
                return "Congestion", (
                    f"Signal is healthy but PHY rate {phy}Mbps is {pct}% of "
                    f"the {ceiling}Mbps realistic ceiling for {std} on {band}, "
                    f"and retries are {retry}% — consistent with channel "
                    f"contention.{note}"
                ), 65
            rate_note = (
                f" PHY {phy}Mbps is {pct}% of the {ceiling}Mbps ceiling for "
                f"{std} on {band}; below par, but retries are only {retry}%, "
                f"so contention is not demonstrated — more likely a 1x1 radio "
                f"or a narrow channel."
                if pct < PHY_UNDERPERFORM_PCT else
                f" PHY {phy}Mbps, {pct}% of the {ceiling}Mbps ceiling for "
                f"{std} on {band}."
            )
            return "Optimal", (
                f"RSSI {rssi}dBm, SNR {snr}dB, retries {retry}% — all "
                f"healthy.{rate_note}{note}"
            ), 90
        return "Optimal", (
            f"RSSI {rssi}dBm, SNR {snr}dB, retries {retry}% — all healthy, "
            f"and the device is on its best available band.{note}"
        ), 85

    # -- 8. Decline --------------------------------------------------------
    return "Insufficient Information", (
        f"RSSI {rssi}dBm / SNR {snr}dB / retries {retry}% fall between "
        f"category boundaries — more samples are needed before a confident "
        f"call.{note}"
    ), 0


if __name__ == "__main__":
    from synthetic_generator import DEVICE_PROFILES, generate_device

    devices = [generate_device(f"dev{i}", p)
               for i, p in enumerate(DEVICE_PROFILES.keys())]
    for d in devices:
        d.setdefault("supports_5ghz", d["band"] != "2.4GHz")

    print("Smoothing (3 passes, to populate trend history):")
    for _ in range(3):
        for d in devices:
            smooth(d)
    for d in devices:
        print(f"  {d['device_id']:6s} rssi={d['rssi']:>7} "
              f"trend={d['trend']:9s} ({d['trend_delta']:>5}dB)")

    print("\nClassification:")
    for d in devices:
        label, reason, conf = classify(d, network_devices=devices)
        print(f"  {d['device_id']:6s} ({d['profile']:11s}) -> {label:24s} [{conf}%]")
        print(f"          {reason}")