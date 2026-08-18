# WiFi Band Analyzer

Wi-Fi root-cause diagnosis on commodity hardware. No enterprise access point
required — a laptop and a phone.

---

## 1. What it does

When Wi-Fi is slow, most tools show you metrics. This one tells you **why**, and
shows its reasoning.

The laptop's own Wi-Fi card is turned into a real access point with `hostapd`.
Client devices associate to it, which is what makes their per-device telemetry
readable at all — signal strength, negotiated PHY rate, retry counters, Wi-Fi
generation. A normal laptop in client mode cannot see any of this about other
devices. Being the access point is what unlocks it.

That telemetry is smoothed, then run through a decision tree that separates five
causes that produce nearly identical symptoms:

| Diagnosis | Distinguishing evidence |
|---|---|
| Hardware Limited | Device has not appeared on 5/6 GHz **while the AP was offering it** |
| Attenuated Signal | Cross-band RSSI gap wider than frequency alone explains, or low RSSI *and* low SNR |
| Far Distance | Low RSSI but healthy SNR — the signal is weak, not dirty |
| Congestion | High retry rate despite a strong signal |
| Device-Specific Issue | This device is >15 dB below its peers on the same network |

When nothing fires confidently the engine returns **Insufficient Information**
and says what measurement it still needs, rather than forcing a guess.

---

## 2. Architecture

```text
┌────────────────────────────────────────────┐
│  hostapd — laptop Wi-Fi card in AP mode    │
│  setup/hostapd-24.conf | hostapd-5.conf    │
│  dnsmasq hands out 192.168.50.x            │
└─────────────────────┬──────────────────────┘
                      │  clients associate
                      ▼
┌────────────────────────────────────────────┐
│  poller.py — `iw station dump` every 2s    │
│  RSSI | derived SNR | retry delta | PHY    │
│  per-band RSSI history for the wall test   │
└─────────────────────┬──────────────────────┘
                      │  HTTP POST
                      ▼
┌────────────────────────────────────────────┐
│  telemetry_server.py — Flask, :5000        │
└─────────────────────┬──────────────────────┘
                      │  HTTP GET
                      ▼
┌────────────────────────────────────────────┐
│  data_source.py — live, else synthetic     │
│  every sample tagged source=live|synthetic │
└─────────────────────┬──────────────────────┘
                      ▼
┌────────────────────────────────────────────┐
│  diagnostic_engine.py                      │
│  KalmanFilter1D → classify()               │
└─────────────────────┬──────────────────────┘
                      ▼
┌────────────────────────────────────────────┐
│  app.py — Streamlit dashboard              │
│  table + per-device reasoning trace        │
└────────────────────────────────────────────┘
```

`wifi_standards.py` holds the RF models (FSPL, log-distance path loss, PHY
rate ceilings) and is called by the engine for distance estimates and the
rate-shortfall check.

---

## 3. Running it

Requires a Wi-Fi card that supports AP mode (`iw list | grep -A 8 "Supported
interface modes"`), plus `hostapd` and `dnsmasq`.

**Your laptop's Wi-Fi card cannot be an AP and a client at the same time.** Get
internet in over USB tethering from a phone *before* starting, or you will go
offline. That phone is the uplink, not part of the experiment — don't move it.

```bash
pip install -r requirements.txt
sudo apt install hostapd dnsmasq
```

Grant `iw` passwordless sudo (it needs root to report signal, but running all of
Python as root breaks user-installed packages):

```bash
echo "$USER ALL=(root) NOPASSWD: $(which iw)" | sudo tee /etc/sudoers.d/wba
```

Hand the interface to hostapd:

```bash
sudo nmcli device set wlp3s0 managed no
sudo ip link set wlp3s0 down && sudo ip addr flush dev wlp3s0
sudo ip link set wlp3s0 up
sudo ip addr add 192.168.50.1/24 dev wlp3s0
```

Route clients out through the tether (substitute your tether interface):

```bash
sudo sysctl -w net.ipv4.ip_forward=1
sudo iptables -t nat -A POSTROUTING -o enx4e7bc5137cbb -j MASQUERADE
sudo iptables -A FORWARD -i wlp3s0 -o enx4e7bc5137cbb -j ACCEPT
sudo iptables -A FORWARD -i enx4e7bc5137cbb -o wlp3s0 \
     -m state --state RELATED,ESTABLISHED -j ACCEPT
```

Clients that get no internet will disassociate themselves, so this matters.

Then one process per terminal:

```bash
sudo hostapd setup/hostapd-24.conf     # the access point
sudo dnsmasq -C setup/dnsmasq.conf -d  # DHCP
python3 telemetry_server.py            # :5000
python3 poller.py                      # reads the AP
streamlit run app.py                   # dashboard
```

On each client phone: mobile data **off**, and MAC randomization **off** for this
SSID (Android: network → Privacy → Use device MAC. iOS: Private Wi-Fi Address
off). A randomized MAC that changes between band switches breaks the cross-band
pairing.

Restore afterwards:

```bash
sudo iptables -t nat -F && sudo iptables -F FORWARD
sudo nmcli device set wlp3s0 managed yes
```

---

## 4. The cross-band test

One radio beacons on one band, so the wall-vs-distance comparison is a
**sequential** procedure, not a passive measurement:

1. Run the 2.4 GHz AP, let the device associate, wait for a poll.
2. **Leave `poller.py` running.** Ctrl-C hostapd, start `hostapd-5.conf`.
3. Device rejoins on 5 GHz. `_band_seen` now holds both bands.

The label resolves from Insufficient Information into Attenuated Signal or Far
Distance depending on the gap. Keep the device physically still between the two
samples, or you measure movement instead of frequency-dependent loss.

`_band_seen` lives in the poller's memory. Restart the poller and the pairing is
lost.

`WALL_DELTA_DB = 12` is a starting value. Tune it: take a reading pair with clear
line of sight and another with a wall in between, and set the threshold where the
two separate.

---

## 5. Validation

```bash
python3 test_classify.py
```

22 hand-labelled scenarios covering every label, both capability-inference paths,
the cross-band threshold, boundary values at the RSSI and retry cutoffs, and
Kalman responsiveness. Run it after changing any threshold.

```bash
python3 diagnostic_engine.py     # synthetic end-to-end
python3 poller.py --once --no-post
```

---

## 6. Assumptions worth stating

**SNR is derived, not measured.** The driver has no survey support, so
`poller.py` subtracts an assumed noise floor (`NOISE_FLOOR`: −90 dBm at 2.4 GHz,
−95 at 5/6). Absolute SNR values are therefore approximate; relative comparisons
between devices on the same band are sound.

**RSSI is the uplink.** It is how strongly the laptop hears the client, not what
the client's own signal bars show. The two are usually close but not identical.

**Retry rate is a delta.** `tx retries` from `iw` is cumulative since
association, so the rate is computed between consecutive polls. The first poll
for any device always reports 0.0%.

**Capability can be inferred rather than observed.** `capability_confidence`
reports which. VHT/HE/EHT clients are treated as dual-band without direct
observation; plain HT and legacy clients are treated as possibly 2.4-only.

---

## 7. Known gaps

- **SNR is not an independent variable.** `poller.py` derives it as
  `rssi - noise_floor`, so on live data every SNR rule is really an RSSI rule.
  Attenuated Signal and Far Distance are therefore only separable by the
  cross-band test, not by the single-band SNR comparison. The single-band
  branch says so in its own reason string.
- `estimate_distance_from_rssi` is the algebraic inverse of
  `log_distance_path_loss`, so excess path loss computed by comparing them is
  bounded by the choice of exponents, not by an independent distance
  measurement. Treat the wall count as an order-of-magnitude hint.
- `synthetic_generator.py` draws independent uniforms per call, so there is no
  temporal continuity for the Kalman filter to smooth and no way to simulate
  walking away from the AP. Trend detection only does useful work on live data.
- No persistence. `data_source.py` is the live/synthetic fallback; nothing is
  stored between runs, and `_band_seen` dies with the poller.
- `run_throughput_test` measures the AP laptop's uplink, not any client's
  Wi-Fi link, unless you run `iperf3 -s` here and the client on the phone.
- `telemetry_server.py` has no auth. Demo-only.
- **Network Health is a presentation statistic, not a measurement.** There is
  no ground truth for it in this project. It is the complement of observed
  severity as a fraction of maximum possible severity; its only justification
  is that it moves in the right direction and saturates correctly.

---

## 8. Fixed, and worth knowing about

- **Hardware Limited was firing on every modern phone.** The rule keyed on
  `wifi4 AND 2.4GHz`, but a phone reports plain HT when the AP only advertises
  HT — so a 2.4 GHz-only session labelled every client Hardware Limited and
  pinned health at 30%. It now requires that the AP actually offered 5/6 GHz
  (`ap_offered_5ghz`, tracked by the poller) before absence counts as evidence.
- **The adaptive Kalman filter never converged.** Outlier rejection treated
  every sample of a sustained change as noise, so after 40 samples of a true
  −70 dBm it still reported −60 and never caught up. Three same-direction
  outliers now count as a real shift. Guarded by `test_classify.py`.
- **PHY-rate shortfall was compared against the headline rate** for the
  generation, so a healthy 2x2 HE client on 2.4 GHz read as 12% of maximum and
  flipped to Congestion. `REALISTIC_PHY_CEILING` is per (standard, band), and
  a shortfall now needs elevated retries before Congestion is claimed.
- **The −71 to −75 dBm dead band** returned Insufficient Information, which
  then counted against health as a fault. Far Distance now starts at −70,
  partitioning the RSSI axis with no gap.
- **Tickets were double-counted and never deduplicated.** Health subtracted
  both the flagged device and its ticket; a device flickering across a
  threshold filed a fresh ticket per crossing. Auto-filing is now guarded by
  `has_open_ticket`, and tickets no longer enter the health score.
