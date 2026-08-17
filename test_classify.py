"""
Controlled test scenarios for the diagnostic engine.

Hand-labelled telemetry in, expected label out. This is the project's
validation objective: it proves each rule fires on the case it was written
for, and it catches regressions when you tune WALL_DELTA_DB or the RSSI
thresholds after a walk test.

Plain asserts, no pytest needed:

    python3 test_classify.py
"""
from diagnostic_engine import WALL_DELTA_DB, KalmanFilter1D, classify

PASS = FAIL = 0


def dev(**kw):
    """A healthy 5 GHz Wi-Fi 6 client; override any field per case."""
    base = {
        "device_id": "aa:bb:cc:dd:ee:ff",
        "band": "5GHz",
        "standard": "wifi6",
        "rssi": -50,
        "snr": 30,
        "retry_rate": 2.0,
    }
    base.update(kw)
    return base


def check(name, device, expected, network_devices=None):
    global PASS, FAIL
    label, reason = classify(device, network_devices=network_devices)
    if label == expected:
        PASS += 1
        print(f"  pass  {name:44s} -> {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {name:44s} -> {label}  (expected {expected})")
        print(f"        reason given: {reason}")


print("Capability / hardware ceiling")
# REGRESSION GUARD, live-data false positive.
# A modern phone reports plain HT when the AP only advertises HT. Reading
# that as "the client is 2.4-only" labelled every phone Hardware Limited.
# With no proof either way the engine must decline, not guess.
check("wifi4 on 2.4GHz, AP never offered 5GHz",
      dev(standard="wifi4", band="2.4GHz", ap_offered_5ghz=False,
          rssi=-45, snr=45),
      "Insufficient Information")
check("legacy on 2.4GHz, AP never offered 5GHz",
      dev(standard="legacy", band="2.4GHz", ap_offered_5ghz=False,
          rssi=-45, snr=45),
      "Insufficient Information")
# Observed absence IS proof: the AP offered 5 GHz and the device never came.
check("AP offered 5GHz, device never appeared there",
      dev(standard="wifi4", band="2.4GHz", supports_5ghz=False,
          ap_offered_5ghz=True, rssi=-45, snr=45),
      "Hardware Limited")
check("explicit ground truth, no AP context (synthetic)",
      dev(standard="wifi4", band="2.4GHz", supports_5ghz=False,
          rssi=-40, snr=50),
      "Hardware Limited")
# PHY evidence cuts one way only: VHT/HE/EHT proves dual-band.
check("wifi6 PHY proves capability without observation",
      dev(standard="wifi6", band="2.4GHz", ap_offered_5ghz=False,
          rssi=-60, snr=30),
      "Insufficient Information")
# REGRESSION GUARD: the original engine keyed on (wifi4 AND 2.4GHz) and
# mislabelled a Wi-Fi 4 device that was actually associated on 5 GHz.
check("wifi4 seen on 5GHz is NOT hardware limited",
      dev(standard="wifi4", band="5GHz", supports_5ghz=True,
          rssi=-50, snr=30),
      "Optimal")

print("\nCapable device sitting on 2.4 GHz — the flagship case")
check("no cross-band sample yet",
      dev(band="2.4GHz", supports_5ghz=True, ap_offered_5ghz=True,
          rssi=-60, snr=30),
      "Insufficient Information")
check("wide cross-band gap = wall",
      dev(band="2.4GHz", supports_5ghz=True, rssi=-60, snr=30,
          band_rssi={"2.4GHz": -60, "5GHz": -85}),
      "Attenuated Signal")
check("narrow cross-band gap = distance",
      dev(band="2.4GHz", supports_5ghz=True, rssi=-60, snr=30,
          band_rssi={"2.4GHz": -60, "5GHz": -66}),
      "Far Distance")
check(f"gap exactly {WALL_DELTA_DB}dB stays distance",
      dev(band="2.4GHz", supports_5ghz=True, rssi=-60, snr=30,
          band_rssi={"2.4GHz": -60, "5GHz": -60 - WALL_DELTA_DB}),
      "Far Distance")
check("6GHz counts as the high band",
      dev(band="2.4GHz", supports_5ghz=True, rssi=-55, snr=30,
          band_rssi={"2.4GHz": -55, "6GHz": -80}),
      "Attenuated Signal")

print("\nSignal quality on 5/6 GHz")
check("low rssi + low snr = obstruction",
      dev(rssi=-75, snr=10), "Attenuated Signal")
check("low rssi + decent snr = distance",
      dev(rssi=-80, snr=18), "Far Distance")
check("high retries despite strong signal",
      dev(rssi=-50, snr=28, retry_rate=30.0), "Congestion")
check("wifi7 on 6GHz, all healthy",
      dev(standard="wifi7", band="6GHz", rssi=-45, snr=40,
          supports_5ghz=True), "Optimal")

print("\nPeer comparison")
peers = [dev(device_id="peer1", rssi=-45), dev(device_id="peer2", rssi=-45)]
target = dev(device_id="target", rssi=-68, snr=25, retry_rate=1.0)
check("far below the network average",
      target, "Device-Specific Issue", network_devices=[target] + peers)
check("only one device on the network — rule must not fire",
      dev(rssi=-68, snr=25), "Insufficient Information",
      network_devices=[dev(rssi=-68, snr=25)])

print("\nBoundaries")
check("rssi exactly -70 with snr 14 is not attenuated",
      dev(rssi=-70, snr=14), "Insufficient Information")
check("retry exactly 15 is not congestion",
      dev(rssi=-50, snr=25, retry_rate=15.0), "Optimal")
check("rssi -67 snr 20 is the optimal floor",
      dev(rssi=-67, snr=20, retry_rate=0.0), "Optimal")
check("rssi -68 falls short of optimal",
      dev(rssi=-68, snr=20, retry_rate=0.0), "Insufficient Information")
check("mid-range rssi with good snr is unclassifiable",
      dev(rssi=-72, snr=20), "Insufficient Information")
check("missing retry_rate defaults to 0",
      {"device_id": "x", "band": "5GHz", "standard": "wifi6",
       "rssi": -50, "snr": 30, "supports_5ghz": True},
      "Optimal")

print("\nKalman responsiveness")
# The filter must track a real 20dB drop within ~10 samples, or the walk
# test looks frozen. This is what the q=0.05 / r=2.0 retune bought.
k = KalmanFilter1D()
k.update(-50)
for _ in range(10):
    est = k.update(-70)
moved = abs(est - (-50))
if moved > 10:
    PASS += 1
    print(f"  pass  tracks a 20dB drop in 10 samples      -> reached {est}dBm")
else:
    FAIL += 1
    print(f"  FAIL  filter too slow                       -> only {est}dBm "
          f"after 10 samples (moved {moved:.1f}dB of 20)")

print(f"\n{PASS} passed, {FAIL} failed")
raise SystemExit(1 if FAIL else 0)
