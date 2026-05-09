import csv
import math
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime
from huawei_lte_api.Connection import Connection
from huawei_lte_api.Client import Client
import speedtest

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


class Tee:
    def __init__(self, console, logfile):
        self.console = console
        self.logfile = logfile

    def write(self, data):
        self.console.write(data)
        self.logfile.write(_ANSI_RE.sub("", data))

    def flush(self):
        self.console.flush()
        self.logfile.flush()

    def isatty(self):
        return self.console.isatty()

# Enable ANSI color codes on Windows
if sys.platform == "win32":
    os.system("")

ROUTER_IP = "192.168.8.1"
USERNAME = "admin"
PASSWORD = "your_router_password"
NETWORK_MODE = "00"
NETWORK_BAND = "2000004400000"

BANDS = [
    ("AUTO",         "7fffffffffffffff"),
    ("B1",           "1"),
    ("B3",           "4"),
    ("B7",           "40"),
    ("B20",          "80000"),
    ("B1+B3",        "5"),
    ("B1+B7",        "41"),
    ("B3+B7",        "44"),
    ("B1+B3+B7",     "45"),
    ("B1+B3+B7+B20", "80045"),
]

BANDS_DICT = dict(BANDS)
BANDS_REVERSE = {v: k for k, v in BANDS_DICT.items()}

LONG_RUNS = 5

CSV_FIELDS_FAST = [
    "Timestamp", "Band_Name", "Actual_Band", "eNodeB_ID",
    "RSRP", "SINR", "DL_Mbps", "UL_Mbps", "Ping", "Cell_ID",
]
CSV_FIELDS_LONG = (
    ["Timestamp", "Band_Name", "Actual_Band", "eNodeB_ID", "RSRP", "SINR"]
    + [f"DL_{i}" for i in range(1, LONG_RUNS + 1)]
    + ["DL_Avg", "DL_Min", "DL_Max", "DL_Std"]
    + [f"UL_{i}" for i in range(1, LONG_RUNS + 1)]
    + ["UL_Avg", "UL_Min", "UL_Max", "UL_Std"]
    + [f"Ping_{i}" for i in range(1, LONG_RUNS + 1)]
    + ["Ping_Avg", "Ping_Min", "Ping_Max", "Ping_Std"]
    + ["Runs_OK", "Cell_ID"]
)

_G = "\033[32m"
_Y = "\033[33m"
_R = "\033[31m"
_X = "\033[0m"

_THRESHOLDS = {
    "rsrp": (-80,  -100),
    "rsrq": (-10,  -15),
    "sinr": ( 13,    0),
    "rssi": (-65,  -80),
}


def colorize(value_str, metric):
    if value_str in ("N/A", None):
        return str(value_str)
    try:
        num = float(str(value_str).replace("dBm", "").replace("dB", "").strip())
    except ValueError:
        return str(value_str)
    good, fair = _THRESHOLDS.get(metric, (None, None))
    if good is None:
        return str(value_str)
    if num >= good:
        return f"{_G}{value_str}{_X}"
    if num >= fair:
        return f"{_Y}{value_str}{_X}"
    return f"{_R}{value_str}{_X}"


def speed_stats(values):
    """Returns (avg, mn, mx, std) rounded to 2dp. All None if list is empty."""
    v = [x for x in values if x is not None and x > 0.1]
    if not v:
        return None, None, None, None
    a  = round(sum(v) / len(v), 2)
    mn = round(min(v), 2)
    mx = round(max(v), 2)
    std = round(math.sqrt(sum((x - a) ** 2 for x in v) / len(v)), 2) if len(v) > 1 else 0.0
    return a, mn, mx, std


def set_lte_band(client, lte_band_hex):
    try:
        client.net.set_net_mode(lte_band_hex, NETWORK_BAND, NETWORK_MODE)
    except Exception:
        pass
    try:
        client.net.reconnect()
    except Exception:
        pass


def wait_for_stable_signal(client, max_seconds, poll_interval=5, stable_needed=3, tolerance_dbm=3):
    min_wait = stable_needed * poll_interval
    rsrp_history = []
    start = time.time()

    while True:
        elapsed = int(time.time() - start)
        remaining = max_seconds - elapsed
        if remaining <= 0:
            print("\r" + " " * 55 + "\r", end="", flush=True)
            return

        print(f"\r  Stabilizing... {elapsed:2d}/{max_seconds}s ", end="", flush=True)
        time.sleep(min(poll_interval, remaining))
        elapsed = int(time.time() - start)

        if elapsed < min_wait:
            continue

        try:
            sig = client.device.signal()
            if sig.get("rrc_status", "0") != "1":
                rsrp_history.clear()
                continue
            rsrp_num = float(str(sig.get("rsrp", "0")).replace("dBm", "").strip())
            rsrp_history.append(rsrp_num)
            rsrp_history = rsrp_history[-stable_needed:]
            if len(rsrp_history) >= stable_needed:
                spread = max(rsrp_history) - min(rsrp_history)
                if spread <= tolerance_dbm:
                    saved = max_seconds - elapsed
                    print(f"\r  Signal stable at {elapsed}s  (saved {saved}s){' ' * 10}", flush=True)
                    return
        except Exception:
            pass


def get_signal_info(client):
    try:
        sig = client.device.signal()
        return {
            "rsrp":      sig.get("rsrp", "N/A"),
            "rsrq":      sig.get("rsrq", "N/A"),
            "sinr":      sig.get("sinr", "N/A"),
            "rssi":      sig.get("rssi", "N/A"),
            "cell_id":   sig.get("cell_id", sig.get("pci", "N/A")),
            "band":      sig.get("band", "N/A"),
            "enodeb_id": sig.get("enodeb_id", "N/A"),
            "dlbw":      sig.get("dlbandwidth", "N/A"),
            "ulbw":      sig.get("ulbandwidth", "N/A"),
            "attached":  sig.get("rrc_status", "0") == "1",
        }
    except Exception:
        return {k: "N/A" for k in ("rsrp", "rsrq", "sinr", "rssi", "cell_id", "band", "enodeb_id", "dlbw", "ulbw")} | {"attached": False}


def get_external_ip():
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=5) as r:
            return r.read().decode()
    except Exception:
        return "unavailable"


def warmup_connection(server_url):
    print("  Warming up connection...", end="", flush=True)
    try:
        warmup_url = server_url.rsplit("/", 1)[0] + "/random1000x1000.jpg"
        with urllib.request.urlopen(warmup_url, timeout=15) as r:
            r.read()
        print(" done", flush=True)
    except Exception as e:
        print(f" skipped ({type(e).__name__}: {e})", flush=True)


def pick_speedtest_server():
    print("Selecting speedtest server...", flush=True)
    s = speedtest.Speedtest(secure=True)
    s.get_best_server()
    srv = s.results.server
    print(f"Selected: {srv['name']} ({srv['country']})  id={srv['id']}\n")
    return srv["id"], srv["url"]


def measure_speed(server_id):
    try:
        s = speedtest.Speedtest(secure=True)
        try:
            s.get_servers([server_id])
            s.get_best_server()
        except speedtest.NoMatchedServers:
            s.get_best_server()
        dl = round(s.download() / 1e6, 2)
        ul = round(s.upload() / 1e6, 2)
        ping = round(s.results.ping, 2)
        return dl, ul, ping
    except Exception as e:
        print(f"  Speedtest failed: {type(e).__name__}: {e}", flush=True)
        return None, None, None


def run_speedtests_multi(server_id, runs, pause=20):
    successful = []
    for n in range(1, runs + 1):
        print(f"  Run {n}/{runs}: measuring...", flush=True)
        dl, ul, ping = measure_speed(server_id)
        if dl is not None and dl > 0.1:
            successful.append((dl, ul, ping))
            print(f"    DL={dl} Mbps  UL={ul} Mbps  Ping={ping} ms")
        else:
            print(f"    failed")
        if n < runs:
            for rem in range(pause, 0, -1):
                print(f"\r    Pause... {rem:2d}s ", end="", flush=True)
                time.sleep(1)
            print("\r" + " " * 25 + "\r", end="", flush=True)
    return successful


def _sinr_num(r):
    try:
        return float(str(r.get("SINR", "0")).replace("dB", "").strip())
    except Exception:
        return 0.0


def _balanced_score(r):
    dl = r.get("DL_Mbps")
    if not isinstance(dl, float):
        return 0.0
    std = r.get("DL_Std")
    # stability factor: penalise high coefficient of variation, cap at 50%
    stab = max(0.5, 1.0 - (std / dl)) if std is not None and dl > 0 else 1.0
    # small SINR bonus: every dB above 0 adds 1%, capped at +20%
    sinr_bonus = 1.0 + min(max(_sinr_num(r), 0), 20) / 100
    return dl * stab * sinr_bonus


def make_recommendation(results, long_mode):
    numeric = [r for r in results if isinstance(r.get("DL_Mbps"), float)]
    if not numeric:
        return

    best_speed    = max(numeric, key=lambda r: r["DL_Mbps"])
    best_balanced = max(numeric, key=_balanced_score)
    best_stable   = min(
        (r for r in numeric if r.get("DL_Std") is not None),
        key=lambda r: r["DL_Std"],
        default=None,
    ) if long_mode else None

    def fmt(r):
        std = f"  σ={r['DL_Std']}" if r.get("DL_Std") is not None else ""
        return f"{r['Band_Name']:<16} {r['DL_Mbps']:>7} Mbps{std}  SINR={r.get('SINR','?')}"

    print("\n" + "─" * 62)
    print("  Recommendation")
    print()
    print(f"  Fastest:   {fmt(best_speed)}")
    if best_stable:
        print(f"  Stable:    {fmt(best_stable)}")
    print(f"  Balanced:  {fmt(best_balanced)}")

    speed_is_unstable = (
        best_speed.get("DL_Std") is not None
        and best_speed["DL_Std"] / best_speed["DL_Mbps"] > 0.20
    )

    print()
    suggest = best_balanced
    if suggest["Band_Name"] == best_speed["Band_Name"]:
        reason = "fastest and well-balanced"
    elif speed_is_unstable:
        diff = round(best_speed["DL_Mbps"] - suggest["DL_Mbps"], 1)
        reason = f"{diff} Mbps slower than {best_speed['Band_Name']} but much more stable"
    else:
        reason = "best balance of speed, stability and signal quality"

    print(f"  → Suggest: {suggest['Band_Name']}  —  {reason}")
    print("─" * 62)


def print_summary(results, long_mode):
    dl_label   = "DL Avg" if long_mode else "DL Mbps"
    ul_label   = "UL Avg" if long_mode else "UL Mbps"
    ping_label = "Ping Avg" if long_mode else " Ping ms"

    print("\n" + "=" * 92)
    print(f"  {'Band':<16} {'Actual':>6} {'eNodeB':>8} {'RSRP':<12} {'SINR':<10} {dl_label:>9} {ul_label:>9} {ping_label:>9}")
    print("  " + "-" * 88)
    for r in results:
        dl   = f"{r['DL_Mbps']}" if r['DL_Mbps'] not in ("N/A", None) else "—"
        ul   = f"{r['UL_Mbps']}" if r['UL_Mbps'] not in ("N/A", None) else "—"
        ping = f"{r['Ping']}"    if r['Ping']    not in ("N/A", None) else "—"
        flag = " !" if str(r.get("Actual_Band", "")) not in r["Band_Name"] and r["Band_Name"] != "AUTO" else ""
        rsrp_raw = str(r['RSRP']) if r['RSRP'] is not None else "N/A"
        sinr_raw = str(r['SINR']) if r['SINR'] is not None else "N/A"
        rsrp_str = colorize(r['RSRP'], "rsrp") + " " * max(0, 12 - len(rsrp_raw))
        sinr_str = colorize(r['SINR'], "sinr") + " " * max(0, 10 - len(sinr_raw))
        print(f"  {r['Band_Name']:<16} {str(r['Actual_Band']):>6} {str(r['eNodeB_ID']):>8} {rsrp_str}{sinr_str}{dl:>9} {ul:>9} {ping:>9}{flag}")
    print("=" * 92)

    # Best results
    numeric = [r for r in results if isinstance(r["DL_Mbps"], float)]
    if numeric:
        best_dl   = max(numeric, key=lambda r: r["DL_Mbps"])
        best_ul   = max(numeric, key=lambda r: r["UL_Mbps"])
        best_ping = min(numeric, key=lambda r: r["Ping"])
        sfx = " (avg)" if long_mode else ""

        def std_note(r, key):
            s = r.get(key)
            return f"  σ={s}" if s is not None else ""

        print(f"\n  Best DL{sfx}:    {best_dl['Band_Name']} — {best_dl['DL_Mbps']} Mbps{std_note(best_dl, 'DL_Std')}")
        print(f"  Best UL{sfx}:    {best_ul['Band_Name']} — {best_ul['UL_Mbps']} Mbps{std_note(best_ul, 'UL_Std')}")
        print(f"  Best Ping{sfx}:  {best_ping['Band_Name']} — {best_ping['Ping']} ms{std_note(best_ping, 'Ping_Std')}")

    # Stability table (long mode only)
    if long_mode:
        has_std = any(r.get("DL_Std") is not None for r in numeric)
        if has_std:
            print(f"\n  {'Band':<16} {'DL Avg':>8} {'σ DL':>7} {'DL range':>14}  {'Ping Avg':>9} {'σ Ping':>7}")
            print("  " + "-" * 68)
            for r in results:
                if not isinstance(r.get("DL_Mbps"), float):
                    continue
                dl_std  = f"{r['DL_Std']}"   if r.get("DL_Std")   is not None else "—"
                dl_rng  = f"{r.get('DL_Min','?')}–{r.get('DL_Max','?')}" if r.get("DL_Min") is not None else "—"
                pg_std  = f"{r['Ping_Std']}" if r.get("Ping_Std") is not None else "—"
                runs_ok = r.get("Runs_OK", "")
                runs_str = f" ({runs_ok}/{LONG_RUNS})" if runs_ok != "" and runs_ok < LONG_RUNS else ""
                print(f"  {r['Band_Name']:<16} {r['DL_Mbps']:>8} {dl_std:>7} {dl_rng:>14}  {r['Ping']:>9} {pg_std:>7}{runs_str}")

    make_recommendation(results, long_mode)

    # eNodeB grouping
    enb_groups = defaultdict(list)
    for r in results:
        enb_groups[str(r["eNodeB_ID"])].append(r["Band_Name"])

    if len(enb_groups) > 1:
        print(f"\n  Tower groups  (tests on different towers are not directly comparable):")
        for enb, bands in sorted(enb_groups.items(), key=lambda x: -len(x[1])):
            print(f"    eNB {enb}:  {', '.join(bands)}")


def prompt_apply_band(client, results, original_lte_band):
    original_name = BANDS_REVERSE.get(original_lte_band, original_lte_band)

    print("\n" + "-" * 50)
    print("Apply a band configuration to the router?")
    print()
    print(f"  [Enter]  Keep original  →  {original_name}  (mask: {original_lte_band})")
    for i, r in enumerate(results, 1):
        print(f"  [{i:>2}]    {r['Band_Name']}")
    print()

    while True:
        choice = input("Choice (Enter or number): ").strip()
        if choice == "":
            target_mask = original_lte_band
            target_name = original_name
            break
        if choice.isdigit() and 1 <= int(choice) <= len(results):
            target_name = results[int(choice) - 1]["Band_Name"]
            target_mask = BANDS_DICT[target_name]
            break
        print(f"  Enter a number between 1 and {len(results)}, or press Enter.")

    print(f"\nApplying {target_name} (mask: {target_mask})...")
    set_lte_band(client, target_mask)
    print("Done.")


def main():
    long_mode     = "--long" in sys.argv
    stabilization = 60 if long_mode else 45
    output_csv    = "lte_benchmark_long.csv" if long_mode else "lte_benchmark.csv"
    csv_fields    = CSV_FIELDS_LONG if long_mode else CSV_FIELDS_FAST

    os.makedirs("logs", exist_ok=True)
    log_path = os.path.join("logs", datetime.now().strftime("%Y%m%d_%H%M%S") + ".log")
    log_file = open(log_path, "w", encoding="utf-8")
    sys.stdout = Tee(sys.__stdout__, log_file)

    try:
        _run(long_mode, stabilization, output_csv, csv_fields, log_path)
    finally:
        sys.stdout = sys.__stdout__
        log_file.close()


def _run(long_mode, stabilization, output_csv, csv_fields, log_path):
    mode_label = f"LONG  ({LONG_RUNS} runs per band, 60s stabilization)" if long_mode else "FAST  (1 run per band, 45s stabilization)"
    print(f"Mode:        {mode_label}")
    print(f"Log:         {log_path}")
    print(f"External IP: {get_external_ip()}")

    # Read original band once with a short-lived connection
    with Connection(f"http://{ROUTER_IP}/", username=USERNAME, password=PASSWORD) as conn:
        original_lte_band = Client(conn).net.net_mode().get("LTEBand", "7fffffffffffffff")
    print(f"Original LTEBand: {original_lte_band}  ({BANDS_REVERSE.get(original_lte_band, 'custom')})")
    print(f"Testing {len(BANDS)} band configurations.\n")
    server_id, server_url = pick_speedtest_server()

    results = []

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        f.flush()

        try:
            for i, (band_name, band_mask) in enumerate(BANDS, 1):
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ({i}/{len(BANDS)}) Testing {band_name}  (mask: {band_mask})")

                # Fresh connection per band — prevents session expiry on long runs
                with Connection(f"http://{ROUTER_IP}/", username=USERNAME, password=PASSWORD) as conn:
                    client = Client(conn)
                    set_lte_band(client, band_mask)
                    wait_for_stable_signal(client, stabilization)
                    warmup_connection(server_url)
                    sig = get_signal_info(client)

                print(f"  Signal:  RSRP={colorize(sig['rsrp'], 'rsrp')}  RSRQ={colorize(sig['rsrq'], 'rsrq')}  SINR={colorize(sig['sinr'], 'sinr')}  RSSI={colorize(sig['rssi'], 'rssi')}")
                print(f"  Cell:    ID={sig['cell_id']}  Band={sig['band']}  DL-BW={sig['dlbw']}  UL-BW={sig['ulbw']}")

                base = {
                    "Timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Band_Name":   band_name,
                    "Actual_Band": sig["band"],
                    "eNodeB_ID":   sig["enodeb_id"],
                    "RSRP":        sig["rsrp"],
                    "SINR":        sig["sinr"],
                    "Cell_ID":     sig["cell_id"],
                }

                if not sig["attached"]:
                    print(f"  No LTE connection on {band_name}, skipping speedtest.")
                    dl_disp = ul_disp = ping_disp = "N/A"
                    display_extra = {}
                    if long_mode:
                        na = {
                            **{f"DL_{j+1}": "N/A" for j in range(LONG_RUNS)},
                            "DL_Avg":"N/A","DL_Min":"N/A","DL_Max":"N/A","DL_Std":"N/A",
                            **{f"UL_{j+1}": "N/A" for j in range(LONG_RUNS)},
                            "UL_Avg":"N/A","UL_Min":"N/A","UL_Max":"N/A","UL_Std":"N/A",
                            **{f"Ping_{j+1}": "N/A" for j in range(LONG_RUNS)},
                            "Ping_Avg":"N/A","Ping_Min":"N/A","Ping_Max":"N/A","Ping_Std":"N/A",
                            "Runs_OK": 0,
                        }
                        row = {**base, **na}
                    else:
                        row = {**base, "DL_Mbps": "N/A", "UL_Mbps": "N/A", "Ping": "N/A"}

                elif long_mode:
                    runs = run_speedtests_multi(server_id, LONG_RUNS)
                    dl_vals   = [r[0] for r in runs]
                    ul_vals   = [r[1] for r in runs]
                    ping_vals = [r[2] for r in runs]

                    dl_avg,   dl_mn,   dl_mx,   dl_std   = speed_stats(dl_vals)
                    ul_avg,   ul_mn,   ul_mx,   ul_std   = speed_stats(ul_vals)
                    ping_avg, ping_mn, ping_mx, ping_std = speed_stats(ping_vals)

                    dl_disp   = dl_avg   if dl_avg   is not None else "N/A"
                    ul_disp   = ul_avg   if ul_avg   is not None else "N/A"
                    ping_disp = ping_avg if ping_avg is not None else "N/A"
                    runs_ok   = len(runs)

                    if runs:
                        ok_str = f" ({runs_ok}/{LONG_RUNS})" if runs_ok < LONG_RUNS else ""
                        print(f"  Avg{ok_str}:   DL={dl_disp} Mbps  UL={ul_disp} Mbps  Ping={ping_disp} ms")
                        if runs_ok > 1:
                            print(f"  Spread: DL {dl_mn}–{dl_mx} (σ={dl_std})  UL {ul_mn}–{ul_mx} (σ={ul_std})  Ping {ping_mn}–{ping_mx} (σ={ping_std})")

                    def nth(lst, n): return lst[n] if n < len(lst) else "N/A"
                    row = {
                        **base,
                        **{f"DL_{j+1}": nth(dl_vals, j) for j in range(LONG_RUNS)},
                        "DL_Avg": dl_disp, "DL_Min": dl_mn or "N/A", "DL_Max": dl_mx or "N/A", "DL_Std": dl_std or "N/A",
                        **{f"UL_{j+1}": nth(ul_vals, j) for j in range(LONG_RUNS)},
                        "UL_Avg": ul_disp, "UL_Min": ul_mn or "N/A", "UL_Max": ul_mx or "N/A", "UL_Std": ul_std or "N/A",
                        **{f"Ping_{j+1}": nth(ping_vals, j) for j in range(LONG_RUNS)},
                        "Ping_Avg": ping_disp, "Ping_Min": ping_mn or "N/A", "Ping_Max": ping_mx or "N/A", "Ping_Std": ping_std or "N/A",
                        "Runs_OK": runs_ok,
                    }
                    display_extra = {"DL_Std": dl_std, "UL_Std": ul_std, "Ping_Std": ping_std,
                                     "DL_Min": dl_mn, "DL_Max": dl_mx, "Runs_OK": runs_ok}

                else:
                    print("  Speedtest: measuring download...", flush=True)
                    dl_disp, ul_disp, ping_disp = measure_speed(server_id)
                    if dl_disp is None:
                        dl_disp = ul_disp = ping_disp = "N/A"
                    else:
                        print("  Speedtest: measuring upload...", flush=True)
                        print(f"  Result:  DL={dl_disp} Mbps  UL={ul_disp} Mbps  Ping={ping_disp} ms")
                    row = {**base, "DL_Mbps": dl_disp, "UL_Mbps": ul_disp, "Ping": ping_disp}
                    display_extra = {}

                print()
                writer.writerow(row)
                f.flush()
                results.append({**base, "DL_Mbps": dl_disp, "UL_Mbps": ul_disp, "Ping": ping_disp, **display_extra})

        except KeyboardInterrupt:
            print("\n\nInterrupted.")
        finally:
            with Connection(f"http://{ROUTER_IP}/", username=USERNAME, password=PASSWORD) as conn:
                set_lte_band(Client(conn), original_lte_band)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Router restored to LTEBand: {original_lte_band}  ({BANDS_REVERSE.get(original_lte_band, 'custom')})")

    if results:
        print_summary(results, long_mode)
        print(f"\nResults saved to {output_csv}")
        with Connection(f"http://{ROUTER_IP}/", username=USERNAME, password=PASSWORD) as conn:
            prompt_apply_band(Client(conn), results, original_lte_band)


if __name__ == "__main__":
    main()
