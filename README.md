# Huawei LTE Band Benchmark

A small Python tool that switches your Huawei LTE router through every LTE band (and common combinations), measures signal quality and internet speed on each, and tells you which band gives the best result. Results are saved to CSV; full console output is saved to `logs/`.

## Supported routers

Built and tested on a **Huawei B818-263** (Elisa Finland firmware). It will likely work on other Huawei LTE routers that expose the standard `huawei-lte-api` HTTP interface (B525, B528, B535, B618, B715, E5186, E5576 and similar), but you may need to tweak the `NETWORK_BAND` constant — see the "Known quirks" section.

## What you need

- A Huawei LTE router reachable on your local network
- Your router's admin password
- Python 3.9 or newer
- Internet access from the router (the speed test contacts speedtest.net)

## Installation

### 1. Install Python

Download and install Python 3.9+ from [python.org](https://www.python.org/downloads/). On Windows, **tick "Add Python to PATH"** during install.

Verify:

```bash
python --version
```

### 2. Get the code

```bash
git clone https://github.com/mmaljutin/huawei-lte-scanner.git
cd huawei-lte-scanner
```

(Or download the ZIP from GitHub and extract it.)

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

This installs `huawei-lte-api` and `speedtest-cli`.

### 4. Configure router credentials

Open **`lte_benchmark.py`** and **`set_band.py`** in any text editor and edit the constants near the top of each file:

```python
ROUTER_IP    = "192.168.8.1"           # your router's LAN IP
USERNAME     = "admin"                 # router admin user
PASSWORD     = "your_router_password"  # router admin password
NETWORK_MODE = "00"                    # "00" = auto, leave as is
NETWORK_BAND = "2000004400000"         # see "Known quirks" below
```

The two files share the same constants — keep them in sync.

> ⚠️ **Don't commit your real password.** If you fork this repo, keep the placeholder or use a local-only branch.

## Running

### Full benchmark (all bands, ~10 minutes)

```bash
python lte_benchmark.py
```

The script will:
1. Read the router's current band setting (and restore it at the end).
2. Pick the closest speedtest.net server.
3. For each of the 10 band configurations: switch the router, wait for the signal to stabilize, run a speed test, record signal/speed/ping.
4. Print a summary, save results to `lte_benchmark.csv`, and offer to apply the best band.

Long mode (5 speed tests per band, more reliable, slower):

```bash
python lte_benchmark.py --long
```

### Switch band manually

Apply a specific band immediately:

```bash
python set_band.py B7
```

Or run interactively:

```bash
python set_band.py
```

Available presets: `AUTO`, `B1`, `B3`, `B7`, `B20`, `B1+B3`, `B1+B7`, `B3+B7`, `B1+B3+B7`, `B1+B3+B7+B20`.

## Output

- `lte_benchmark.csv` / `lte_benchmark_long.csv` — per-band results (timestamp, RSRP, SINR, DL/UL Mbps, ping, cell ID, …)
- `logs/<timestamp>.log` — full console output of each run

Both are excluded from git via `.gitignore`.

## Known quirks

- `NETWORK_BAND = "2000004400000"` is the value the **Elisa Finland** firmware happens to store. On other firmware/operators this will probably differ. The simplest way to find your value: configure any band via the router admin web UI, then read `client.net.net_mode()` and copy the `NetworkBand` field.
- `set_net_mode()` always raises a `112003` error on this firmware, but the router applies the setting anyway — the exception is intentionally swallowed.
- `set_net_mode(lteband, networkband, networkmode)` parameter order matters — passing them in any other order silently fails.

## Files

| File | Purpose |
|---|---|
| `lte_benchmark.py` | Main benchmark script |
| `set_band.py` | Standalone band switcher |
| `cell_lock.py` | (Optional / experimental) PCI lock via USB serial AT commands |
| `requirements.txt` | Python dependencies |

## License

MIT — do whatever you like, no warranty.
