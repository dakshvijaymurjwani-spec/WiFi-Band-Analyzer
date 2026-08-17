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
| Hardware Limited | Device has never been seen on 5/6 GHz and its PHY mode implies a 2.4-only radio |
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

`wifi_standards.py` holds the RF models (FSPL, log-distance path loss,
theoretical max PHY rates). Not yet wired into the pipeline — see Known Gaps.

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

- `wifi_standards.py` is not called by the pipeline. Note that
  `estimate_distance_from_rssi` is the algebraic inverse of
  `log_distance_path_loss`, so comparing them yields zero by construction —
  excess path loss is only meaningful if distance is an independent input.
- `synthetic_generator.py` draws independent uniforms per call, so there is no
  temporal continuity for the Kalman filter to smooth and no way to simulate
  walking away from the AP.
- No persistence. `data_source.py` is the live/synthetic fallback; nothing is
  stored between runs.
- `active_probe.py` is a stub — the iperf3 server address is a placeholder and
  `file_ticket` is never called.
- `telemetry_server.py` runs with `debug=True` and no auth. Demo-only.
