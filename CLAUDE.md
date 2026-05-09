# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

LTE band benchmarking tool for Huawei B818-263 router. Switches LTE bands one by one, measures signal quality and internet speed per band, saves results to CSV.

## Running the scripts

```bash
# Full benchmark (9 bands, ~10 min)
python lte_benchmark.py

# Apply a specific band immediately
python set_band.py B7
python set_band.py          # interactive menu

# One-time diagnostics
python diagnose.py
```

Dependencies: `pip install -r requirements.txt` (`huawei-lte-api`, `speedtest-cli`)

## Critical API quirk

`huawei_lte_api.api.Net.set_net_mode` has a **non-obvious parameter order**:

```python
client.net.set_net_mode(lteband, networkband, networkmode)
#                        ^first   ^second      ^third
```

The order is **lteband → networkband → networkmode**, not networkmode first. Passing arguments in the wrong order silently sends swapped XML fields to the router and gets error `112003`.

## Router connection constants

Both scripts share these constants at the top of the file — update them together if the router config changes:

```python
ROUTER_IP    = "192.168.8.1"
USERNAME     = "admin"
PASSWORD     = "..."
NETWORK_MODE = "00"           # auto — must stay "00", "03" (LTE-only) is ignored by this firmware
NETWORK_BAND = "2000004400000"  # router's own saved value — must match what net_mode() returns
```

`NETWORK_BAND` is not a standard "all bands" value — it is the specific value the Elisa Finland firmware stores. Using `"3FFFFFFF"` here causes 112003 errors.

## Band mask encoding

LTE band N = `2**(N-1)` as hex string. Combinations are bitwise OR:

| Name | Hex mask |
|---|---|
| B1 | `1` |
| B3 | `4` |
| B7 | `40` |
| B20 | `80000` |
| B38 | `2000000000` |
| B1+B3+B7 | `45` |
| AUTO (all) | `7fffffffffffffff` |

## How band switching works

1. `set_net_mode(lteband, NETWORK_BAND, NETWORK_MODE)` — always throws exception (`112003`) but the router **does apply the setting**. Exception is swallowed with `pass`.
2. `client.net.reconnect()` — forces the modem to drop and re-establish the radio connection so the new band takes effect immediately. Without this call the router may stay on the previous band until it naturally reconnects.
3. 30-second stabilization wait — router needs time to find and attach to a cell on the new band.

## Known limitations

- `net_feature_switch` returns `lteband_switch: '0'` and `lock_freq_switch: '0'` — these are locked by the operator firmware and cannot be enabled via API. Despite this, band switching works via the mechanism above.
- AT command endpoint (`/api/device/at-command`) requires elevated privileges not accessible via standard admin login.
- PCI/cell locking is not achievable via HTTP API on this firmware — `cell_lock.py` exists for future USB serial AT command approach.
- `speedtest-cli` server selection: the server is picked once before the loop (`pick_speedtest_server()`) and reused for all 9 tests to ensure fair comparison.

## Files

| File | Purpose |
|---|---|
| `lte_benchmark.py` | Main benchmark loop |
| `set_band.py` | Standalone band switcher |
| `cell_lock.py` | USB serial AT command cell lock (requires pyserial + USB cable) |
| `diagnose.py` | Ad-hoc router state inspection |
| `debug_request.py` | HTTP request interceptor for API debugging |
| `raw_test.py` | Raw requests-based API experiments |
