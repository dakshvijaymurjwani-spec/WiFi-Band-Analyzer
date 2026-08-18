"""
Controlled test scenarios for the diagnostic engine.

Hand-labelled telemetry in, expected label out. This is the project's
validation objective: it proves each rule fires on the case it was written
for, and it catches regressions when thresholds are tuned after a walk test.

Plain asserts, no pytest needed:

    python3 test_classify.py
"""
from diagnostic_engine import (
    PHY_UNDERPERFORM_PCT,
    WALL_DELTA_DB,
    AdaptiveKalmanFilter1D,
    KalmanFilter1D,
    classify,
)
from wifi_standards import expected_max_rate

PASS = FAIL = 0


def dev(**kw):
    """A healthy 5 GHz Wi-Fi 6 client; override any field per case."""
    base = {"device_id": "aa:bb:cc:dd:ee:ff", "band": "5GHz",
            "standard": "wifi6", "rssi": -50, "snr": 30, "retry_rate": 2.0}
    base.update(kw)
    return base


def check(name, device, expected, network_devices=None):
    global PASS, FAIL
    label, reason, conf = classify(device, network_devices=network_devices)
    if label == expected:
        PASS += 1
        print(f"  pass  {name:50s} -> {label} [{conf}%]")
    else:
        FAIL += 1
        print(f"  FAIL  {name:50s} -> {label}  (expected {expected})")
        print(f"        reason: {reason}")


def assert_true(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  pass  {name:50s} {detail}")
    else:
        FAIL += 1
        print(f"  FAIL  {name:50s} {detail}")


print("Capability / hardware ceiling")
# REGRESSION GUARD, live-data false positive.
# A modern phone reports plain HT when the AP only advertises HT. Reading
# that as "the client is 2.4-only" labelled every phone Hardware Limited and
# pinned network health at its floor. With no proof either way, decline.
check("wifi4 on 2.4GHz, AP never offered 5GHz",
      dev(standard="wifi4", band="2.4GHz", ap_offered_5ghz=False,
          rssi=-45, snr=45), "Insufficient Information")
check("legacy on 2.4GHz, AP never offered 5GHz",
      dev(standard="legacy", band="2.4GHz", ap_offered_5ghz=False,
          rssi=-45, snr=45), "Insufficient Information")
# Observed absence IS proof: the AP offered 5 GHz and the device never came.
check("AP offered 5GHz, device never appeared there",
      dev(standard="wifi4", band="2.4GHz", supports_5ghz=False,
          ap_offered_5ghz=True, rssi=-45, snr=45), "Hardware Limited")
check("explicit ground truth, no AP context (synthetic)",
      dev(standard="wifi4", band="2.4GHz", supports_5ghz=False,
          rssi=-40, snr=50), "Hardware Limited")
# PHY evidence cuts one way only: VHT/HE/EHT proves dual-band.
check("wifi6 PHY proves capability without observation",
      dev(standard="wifi6", band="2.4GHz", ap_offered_5ghz=False,
          rssi=-60, snr=30), "Insufficient Information")
# REGRESSION GUARD: the original engine keyed on (wifi4 AND 2.4GHz) and
# mislabelled a Wi-Fi 4 device that was actually associated on 5 GHz.
check("wifi4 seen on 5GHz is NOT hardware limited",
      dev(standard="wifi4", band="5GHz", supports_5ghz=True,
          rssi=-50, snr=30), "Optimal")

print("\nCapable device sitting on 2.4 GHz — the flagship case")
check("no cross-band sample yet",
      dev(band="2.4GHz", supports_5ghz=True, ap_offered_5ghz=True,
          rssi=-60, snr=30), "Insufficient Information")
check("wide cross-band gap = wall",
      dev(band="2.4GHz", supports_5ghz=True, rssi=-60, snr=30,
          band_rssi={"2.4GHz": -60, "5GHz": -85}), "Attenuated Signal")
check("narrow cross-band gap = distance",
      dev(band="2.4GHz", supports_5ghz=True, rssi=-60, snr=30,
          band_rssi={"2.4GHz": -60, "5GHz": -66}), "Far Distance")
check(f"gap exactly {WALL_DELTA_DB}dB stays distance",
      dev(band="2.4GHz", supports_5ghz=True, rssi=-60, snr=30,
          band_rssi={"2.4GHz": -60, "5GHz": -60 - WALL_DELTA_DB}), "Far Distance")
check("6GHz counts as the high band",
      dev(band="2.4GHz", supports_5ghz=True, rssi=-55, snr=30,
          band_rssi={"2.4GHz": -55, "6GHz": -80}), "Attenuated Signal")

print("\nSignal quality on 5/6 GHz")
check("low rssi + low snr = obstruction", dev(rssi=-75, snr=10), "Attenuated Signal")
check("low rssi + decent snr = distance", dev(rssi=-80, snr=18), "Far Distance")
check("weak but clean at -72 is diagnosable, not a gap",
      dev(rssi=-72, snr=20), "Far Distance")
check("unusable signal declines to attribute a cause",
      dev(rssi=-90, snr=5), "Signal Critically Weak")
check("high retries despite strong signal",
      dev(rssi=-50, snr=28, retry_rate=30.0), "Congestion")
check("wifi7 on 6GHz, all healthy",
      dev(standard="wifi7", band="6GHz", rssi=-45, snr=40,
          supports_5ghz=True), "Optimal")

print("\nPHY rate: shortfall needs corroboration")
# REGRESSION GUARD. Comparing a real negotiated rate against the headline
# figure for the generation made a healthy 2x2 HE client on 2.4 GHz read as
# 12% of maximum and flip to Congestion at a perfect signal.
check("2x2 HE client on 2.4GHz at its real ceiling",
      dev(band="2.4GHz", supports_5ghz=True, rssi=-45, snr=45,
          phy_rate=143.0, retry_rate=1.0,
          band_rssi={"2.4GHz": -45, "5GHz": -50}), "Far Distance")
check("rate shortfall with no retries is not congestion",
      dev(rssi=-50, snr=40, phy_rate=200.0, retry_rate=1.0), "Optimal")
check("rate shortfall WITH retries is congestion",
      dev(rssi=-50, snr=40, phy_rate=200.0, retry_rate=8.0), "Congestion")
assert_true("realistic ceiling differs from headline",
            expected_max_rate("wifi6", "2.4GHz") < expected_max_rate("wifi6", "5GHz"),
            f"2.4GHz={expected_max_rate('wifi6','2.4GHz')} "
            f"5GHz={expected_max_rate('wifi6','5GHz')}")

print("\nPeer comparison")
peers = [dev(device_id="peer1", rssi=-45), dev(device_id="peer2", rssi=-45)]
target = dev(device_id="target", rssi=-68, snr=25, retry_rate=1.0)
check("far below the network average", target, "Device-Specific Issue",
      network_devices=[target] + peers)
check("only one device on the network — rule must not fire",
      dev(rssi=-68, snr=25), "Optimal",
      network_devices=[dev(rssi=-68, snr=25)])

print("\nBoundaries")
check("rssi exactly -70 with snr 14 is not attenuated",
      dev(rssi=-70, snr=14), "Insufficient Information")
check("retry exactly 15 is not congestion",
      dev(rssi=-50, snr=25, retry_rate=15.0), "Optimal")
check("rssi -70 is the optimal floor", dev(rssi=-70, snr=20, retry_rate=0.0), "Optimal")
check("rssi -71 falls to Far Distance", dev(rssi=-71, snr=20, retry_rate=0.0),
      "Far Distance")
check("missing retry_rate defaults to 0",
      {"device_id": "x", "band": "5GHz", "standard": "wifi6",
       "rssi": -50, "snr": 30, "supports_5ghz": True}, "Optimal")

print("\nKalman responsiveness")
# The filter must track a real 20dB drop, or the walk test looks frozen.
k = KalmanFilter1D()
k.update(-50)
est = [k.update(-70) for _ in range(10)][-1]
assert_true("base filter tracks a 20dB drop in 10 samples",
            abs(est - (-50)) > 10, f"reached {est}dBm")

# REGRESSION GUARD, and the most severe bug this suite covers.
# Outlier rejection treated every sample of a sustained change as noise, so
# the adaptive filter never converged: after 40 samples of a true -70 it was
# still reporting -60, and every downstream label read that fiction.
a = AdaptiveKalmanFilter1D()
a.update(-50)
ests = [a.update(-70) for _ in range(20)]
converged = next((i + 1 for i, e in enumerate(ests) if abs(e + 70) < 2), None)
assert_true("adaptive filter converges on a sustained shift",
            converged is not None and converged <= 15,
            f"within 2dB at sample {converged}, final {ests[-1]}dBm")

# ...but a single spike must still be rejected.
b = AdaptiveKalmanFilter1D()
for _ in range(8):
    b.update(-50)
spike = b.update(-78)
assert_true("adaptive filter still rejects a lone spike",
            abs(spike - (-50)) < 5, f"28dB spike moved estimate only to {spike}dBm")

print(f"\n{PASS} passed, {FAIL} failed")
raise SystemExit(1 if FAIL else 0)