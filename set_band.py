import sys
from huawei_lte_api.Connection import Connection
from huawei_lte_api.Client import Client

ROUTER_IP = "192.168.8.1"
USERNAME = "admin"
PASSWORD = "your_router_password"
NETWORK_MODE = "00"
NETWORK_BAND = "2000004400000"

BANDS = {
    "AUTO":         "7fffffffffffffff",
    "B1":           "1",
    "B3":           "4",
    "B7":           "40",
    "B20":          "80000",
    "B1+B3":        "5",
    "B1+B7":        "41",
    "B3+B7":        "44",
    "B1+B3+B7":     "45",
    "B1+B3+B7+B20": "80045",
}

BANDS_REVERSE = {v: k for k, v in BANDS.items()}


def apply_band(client, mask, name):
    try:
        client.net.set_net_mode(mask, NETWORK_BAND, NETWORK_MODE)
    except Exception:
        pass
    applied = client.net.net_mode().get("LTEBand", "?")
    match = applied.lower() == mask.lower()
    if match:
        print(f"Done. Router LTEBand set to: {applied}  ({name})")
    else:
        print(f"Warning: requested {mask}, router reports {applied}")


def interactive(client, current):
    current_name = BANDS_REVERSE.get(current, current)
    names = list(BANDS.keys())

    print(f"Current LTEBand: {current}  ({current_name})")
    print()
    for i, name in enumerate(names, 1):
        marker = " ←" if BANDS[name] == current else ""
        print(f"  [{i:>2}]  {name}{marker}")
    print()

    while True:
        choice = input("Choose band number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            target_name = names[int(choice) - 1]
            break
        print(f"  Enter a number between 1 and {len(names)}.")

    target_mask = BANDS[target_name]
    print(f"\nApplying {target_name} (mask: {target_mask})...")
    apply_band(client, target_mask, target_name)


def main():
    with Connection(f"http://{ROUTER_IP}/", username=USERNAME, password=PASSWORD) as conn:
        client = Client(conn)
        current = client.net.net_mode().get("LTEBand", "?")

        if len(sys.argv) > 1:
            arg = sys.argv[1].upper()
            if arg in BANDS:
                mask = BANDS[arg]
                print(f"Applying {arg} (mask: {mask})...")
                apply_band(client, mask, arg)
            elif arg.lower() in BANDS_REVERSE.values():
                name = BANDS_REVERSE[arg.lower()]
                print(f"Applying {name} (mask: {arg.lower()})...")
                apply_band(client, arg.lower(), name)
            else:
                print(f"Unknown band: {sys.argv[1]}")
                print(f"Available: {', '.join(BANDS.keys())}")
                sys.exit(1)
        else:
            interactive(client, current)


if __name__ == "__main__":
    main()
