import math

# Theoretical max PHY rates (Mbps) — single-stream, simplified for hackathon scope.
# Real max rates depend on channel width/spatial streams, but this gives a
# defensible "is this device underperforming for its class" comparison.
STANDARD_MAX_RATES = {
    "wifi4":  {"name": "802.11n",  "max_mbps": 150,   "bands": ["2.4GHz", "5GHz"]},
    "wifi5":  {"name": "802.11ac", "max_mbps": 866,   "bands": ["5GHz"]},
    "wifi6":  {"name": "802.11ax", "max_mbps": 1201,  "bands": ["2.4GHz", "5GHz"]},
    "wifi6e": {"name": "802.11ax", "max_mbps": 2402,  "bands": ["2.4GHz", "5GHz", "6GHz"]},
    "wifi7":  {"name": "802.11be", "max_mbps": 5764,  "bands": ["2.4GHz", "5GHz", "6GHz"]},
}

def get_max_rate(standard):
    """Return theoretical max PHY rate (Mbps) for a given standard key."""
    return STANDARD_MAX_RATES.get(standard, {}).get("max_mbps")


def free_space_path_loss(distance_km, freq_mhz):
    """
    FSPL(dB) = 20*log10(d) + 20*log10(f) + 32.44
    d in km, f in MHz. Baseline expected loss with zero obstacles.
    """
    if distance_km <= 0:
        return 0
    return 20 * math.log10(distance_km) + 20 * math.log10(freq_mhz) + 32.44


# Empirical anchor: RSSI measured at the reference distance on the reference
# band. Everything else is derived from it, so a single calibration
# measurement propagates to all three bands.
#
# Calibrate by placing a client 1 m from the AP on 2.4 GHz and reading its
# RSSI; substitute that value. -40 dBm is a reasonable consumer default.
RSSI_AT_D0_REF = -40.0
FREQ_REF_MHZ = 2400.0
D0_M = 1.0


def reference_rssi(freq_mhz, rssi_at_d0_ref=RSSI_AT_D0_REF,
                   freq_ref_mhz=FREQ_REF_MHZ, d0=D0_M):
    """RSSI expected at d0 on `freq_mhz`, translated from the reference band.

    The frequency term of the Friis equation is 20*log10(f), so moving the
    reference from 2.4 GHz to 5 GHz costs 20*log10(5000/2400) = 6.4 dB at the
    same distance. Without this, log_distance_path_loss() accepted freq_mhz
    and ignored it — all three bands returned identical predictions, and the
    "2.4 vs 5 vs 6 GHz path loss models" requirement was unmet in fact.
    """
    delta = (free_space_path_loss(d0 / 1000.0, freq_mhz)
             - free_space_path_loss(d0 / 1000.0, freq_ref_mhz))
    return rssi_at_d0_ref - delta


def log_distance_path_loss(distance_m, freq_mhz, path_loss_exponent=3.5,
                           d0=D0_M, rssi_at_d0=None):
    """Log-Distance Path Loss Model, band-aware.

        RSSI(d) = RSSI(d0, f) - 10 * n * log10(d / d0)

    distance_m: distance from AP in metres
    freq_mhz: 2400, 5000 or 6000 — now genuinely used
    path_loss_exponent (n): ~2 free space, 3-4 typical indoor with walls
    rssi_at_d0: override the derived reference with a measured one
    """
    if rssi_at_d0 is None:
        rssi_at_d0 = reference_rssi(freq_mhz, d0=d0)
    if distance_m <= 0:
        return round(rssi_at_d0, 1)
    path_loss_db = 10 * path_loss_exponent * math.log10(distance_m / d0)
    return round(rssi_at_d0 - path_loss_db, 1)


def estimate_distance_from_rssi(rssi, freq_mhz, path_loss_exponent=3.5,
                                d0=D0_M, rssi_at_d0=None):
    """Inverse of the log-distance model: measured RSSI -> estimated distance.

    Band-aware, so the same -75 dBm implies a shorter distance at 5 GHz than
    at 2.4 GHz — which is correct, since the higher band loses more per metre.
    """
    if rssi_at_d0 is None:
        rssi_at_d0 = reference_rssi(freq_mhz, d0=d0)
    exponent = (rssi_at_d0 - rssi) / (10 * path_loss_exponent)
    return round(d0 * (10 ** exponent), 2)


# Per-barrier attenuation by band. A wall costs more at higher frequency;
# that differential is the entire basis of the cross-band wall test.
# Figures are typical interior construction (drywall / plaster over studs).
# Brick, concrete and tiled walls run several times higher.
WALL_ATTENUATION_DB = {"2.4GHz": 3.0, "5GHz": 4.5, "6GHz": 5.0}

# Excess attenuation of a substantial interior barrier at 5/6 GHz over
# 2.4 GHz — brick, concrete, or a tiled bathroom wall rather than plain
# drywall. This is the tunable part of the cross-band threshold.
DIFFERENTIAL_BARRIER_DB = 5.0


def wall_attenuation_db(band):
    return WALL_ATTENUATION_DB.get(band, 4.5)


def expected_band_gap_db(low_band="2.4GHz", high_band="5GHz", d0=D0_M):
    """RSSI gap between two bands attributable to FREQUENCY ALONE.

    At equal distance with no obstruction, a client's 2.4 GHz RSSI exceeds
    its 5 GHz RSSI by this much simply because of the Friis frequency term.
    Anything beyond it is obstruction. Returns ~6.4 dB for 2.4 -> 5 GHz.
    """
    f_lo = band_to_freq_mhz(low_band)
    f_hi = band_to_freq_mhz(high_band)
    return round(free_space_path_loss(d0 / 1000.0, f_hi)
                 - free_space_path_loss(d0 / 1000.0, f_lo), 2)


def derive_wall_delta_threshold(low_band="2.4GHz", high_band="5GHz",
                                barrier_db=DIFFERENTIAL_BARRIER_DB):
    """Cross-band gap above which an obstruction is the better explanation.

    = frequency-only gap + one substantial barrier's differential loss.

    This replaces a hand-picked constant. Only `barrier_db` is a judgement
    call; the rest follows from Friis. Tune barrier_db during the walk test
    by taking one line-of-sight reading pair and one through-wall pair, and
    setting it where the two separate.
    """
    return round(expected_band_gap_db(low_band, high_band) + barrier_db, 1)





# Realistic per-client ceilings, not the marketing figure for the standard.
#
# STANDARD_MAX_RATES above lists the headline rate for the generation. Real
# clients rarely reach it: a phone is usually 1x1 or 2x2, often on a 20 or
# 40 MHz channel. Comparing a real negotiated rate against the headline
# number makes a perfectly healthy 2x2 HE client on 2.4 GHz read as 12% of
# maximum, which previously triggered a false Congestion diagnosis.
#
# These are 2x2 figures for the channel width normally available on each
# band, which is the sensible ceiling for a well-behaved consumer client.
REALISTIC_PHY_CEILING = {
    ("wifi4",  "2.4GHz"): 144,    # 2x2 HT20, short GI
    ("wifi4",  "5GHz"):   300,    # 2x2 HT40
    ("wifi5",  "5GHz"):   867,    # 2x2 VHT80
    ("wifi6",  "2.4GHz"): 287,    # 2x2 HE20
    ("wifi6",  "5GHz"):  1201,    # 2x2 HE80
    ("wifi6e", "2.4GHz"): 287,
    ("wifi6e", "5GHz"):  1201,
    ("wifi6e", "6GHz"):  2402,    # 2x2 HE160
    ("wifi7",  "2.4GHz"): 688,    # 2x2 EHT20
    ("wifi7",  "5GHz"):  2882,    # 2x2 EHT160
    ("wifi7",  "6GHz"):  5764,    # 2x2 EHT320
}


def expected_max_rate(standard, band):
    """Realistic ceiling for this standard on this band, or None if unknown.

    Prefer this over get_max_rate() when judging whether a live client is
    underperforming: get_max_rate() answers "what can the generation do",
    this answers "what should this link actually be reaching".
    """
    return REALISTIC_PHY_CEILING.get((standard, band))


def band_to_freq_mhz(band):
    """Representative centre frequency for path-loss maths."""
    return {"2.4GHz": 2400, "5GHz": 5000, "6GHz": 6000}.get(band, 5000)


def freq_to_band(freq_mhz):
    """Inverse of band_to_freq_mhz, for functions that only receive a freq."""
    if freq_mhz > 5900:
        return "6GHz"
    if freq_mhz > 3000:
        return "5GHz"
    return "2.4GHz"


def estimate_wall_attenuation(rssi, freq_mhz, d0=D0_M, rssi_at_d0=None,
                              indoor_exponent=3.5, open_air_exponent=2.0,
                              wall_db=None):
    """Excess path loss beyond free space, and a rough barrier count.

    Estimates distance with the indoor exponent, then asks how much stronger
    the signal would be at that same distance in open air. The gap is a proxy
    for obstruction.

    CAVEAT, and it is a real one: because estimate_distance_from_rssi is the
    algebraic inverse of log_distance_path_loss, this comparison is bounded
    by the choice of the two exponents rather than by an independent distance
    measurement. Treat the barrier count as an order-of-magnitude hint. The
    cross-band gap in diagnostic_engine is the sound test; this is the
    single-band fallback for when only one band has been sampled.

    Returns (indoor_distance_m, attenuation_db, estimated_barrier_count).
    """
    if wall_db is None:
        wall_db = wall_attenuation_db(freq_to_band(freq_mhz))
    indoor_distance = estimate_distance_from_rssi(
        rssi, freq_mhz, path_loss_exponent=indoor_exponent,
        d0=d0, rssi_at_d0=rssi_at_d0)
    expected_open_air_rssi = log_distance_path_loss(
        indoor_distance, freq_mhz, path_loss_exponent=open_air_exponent,
        d0=d0, rssi_at_d0=rssi_at_d0)
    attenuation_db = round(expected_open_air_rssi - rssi, 1)
    count = max(0, round(attenuation_db / wall_db)) if attenuation_db > 0 else 0
    return round(indoor_distance, 2), attenuation_db, count


if __name__ == "__main__":
    # Quick sanity checks
    print("Max rates:")
    for std, info in STANDARD_MAX_RATES.items():
        print(f"  {std:8s} -> {info['max_mbps']} Mbps ({info['name']})")

    print("\nFSPL at 10m, 5GHz band:")
    print(f"  {free_space_path_loss(0.01, 5000):.1f} dB")

    print("\nLog-distance predicted RSSI at 5m, 10m, 20m (5GHz, indoor n=3.5):")
    for d in [5, 10, 20]:
        print(f"  {d}m -> {log_distance_path_loss(d, 5000)} dBm")

    print("\nEstimated distance from RSSI -75dBm (5GHz, indoor n=3.5):")
    print(f"  {estimate_distance_from_rssi(-75, 5000)} m")
