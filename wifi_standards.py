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


def log_distance_path_loss(distance_m, freq_mhz, path_loss_exponent=3.5, d0=1.0, rssi_at_d0=-40):
    """
    Log-Distance Path Loss Model.
    Estimates RSSI at a given distance based on a reference measurement at d0.

    distance_m: distance from AP in meters
    freq_mhz: frequency in MHz (2400, 5000, or 6000)
    path_loss_exponent (n): ~2 free space, 3-4 typical indoor with walls
    d0: reference distance in meters (default 1m)
    rssi_at_d0: measured/typical RSSI at the reference distance
    """
    if distance_m <= 0:
        return rssi_at_d0
    path_loss_db = 10 * path_loss_exponent * math.log10(distance_m / d0)
    return round(rssi_at_d0 - path_loss_db, 1)


def estimate_distance_from_rssi(rssi, freq_mhz, path_loss_exponent=3.5, d0=1.0, rssi_at_d0=-40):
    """
    Inverse of the log-distance model: given a measured RSSI, estimate distance.
    Used to compare 'expected RSSI at this distance' vs 'actual RSSI' —
    the gap reveals how much loss is from walls/obstacles vs. distance alone.
    """
    exponent = (rssi_at_d0 - rssi) / (10 * path_loss_exponent)
    return round(d0 * (10 ** exponent), 2)



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


def estimate_wall_attenuation(rssi, freq_mhz, d0=1.0, rssi_at_d0=-40,
                               indoor_exponent=3.5, open_air_exponent=2.0, wall_db=5.0):
    """
    Estimates distance using the indoor exponent (which already assumes typical
    attenuation), then checks how much stronger the signal would be at that same
    distance under open-air propagation. The gap is a rough proxy for excess
    attenuation beyond the indoor baseline — not a true per-device wall count,
    since a single RSSI reading can't fully separate distance from obstruction.
    wall_db=5.0 is a typical interior-wall attenuation figure (see literature survey).
    Returns (indoor_distance_m, attenuation_db, estimated_wall_count).
    """
    indoor_distance = estimate_distance_from_rssi(
        rssi, freq_mhz, path_loss_exponent=indoor_exponent,
        d0=d0, rssi_at_d0=rssi_at_d0
    )
    expected_open_air_rssi = log_distance_path_loss(
        indoor_distance, freq_mhz, path_loss_exponent=open_air_exponent,
        d0=d0, rssi_at_d0=rssi_at_d0
    )
    attenuation_db = round(expected_open_air_rssi - rssi, 1)
    wall_count = max(0, round(attenuation_db / wall_db)) if attenuation_db > 0 else 0
    return round(indoor_distance, 2), attenuation_db, wall_count


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