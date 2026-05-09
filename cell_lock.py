import sys
import time
import serial
import serial.tools.list_ports

BAUD_RATE = 115200
TIMEOUT = 3

TARGET_EARFCN = 523
TARGET_PCI = 489
TARGET_BAND = 1


def find_huawei_ports():
    ports = []
    for p in serial.tools.list_ports.comports():
        desc = (p.description or "").lower()
        mfr  = (p.manufacturer or "").lower()
        if "huawei" in desc or "huawei" in mfr or "mobile connect" in desc:
            ports.append(p)
    return ports


def send_at(ser, cmd, delay=0.5):
    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode())
    time.sleep(delay)
    response = ser.read(ser.in_waiting or 1024).decode(errors="ignore").strip()
    return response


def probe_port(port_name):
    try:
        with serial.Serial(port_name, BAUD_RATE, timeout=TIMEOUT) as ser:
            resp = send_at(ser, "AT")
            if "OK" in resp:
                return True
    except Exception:
        pass
    return False


def query_lock(ser):
    resp = send_at(ser, "AT^FREQLOCK?", delay=1)
    print(f"  Current lock: {resp}")


def apply_lock(ser, earfcn, pci, band):
    cmd = f"AT^FREQLOCK=1,6,{band},{earfcn},{pci}"
    print(f"  Sending: {cmd}")
    resp = send_at(ser, cmd, delay=1)
    print(f"  Response: {resp}")
    return "OK" in resp


def remove_lock(ser):
    resp = send_at(ser, "AT^FREQLOCK=0", delay=1)
    print(f"  Unlock response: {resp}")
    return "OK" in resp


def interactive(ser):
    print(f"\nTarget cell:  EARFCN={TARGET_EARFCN}  PCI={TARGET_PCI}  Band=B{TARGET_BAND}")
    print()
    print("  [1]  Query current lock")
    print("  [2]  Lock to target cell")
    print("  [3]  Remove lock (auto)")
    print("  [q]  Quit")
    print()

    while True:
        choice = input("Choice: ").strip().lower()
        if choice == "1":
            query_lock(ser)
        elif choice == "2":
            ok = apply_lock(ser, TARGET_EARFCN, TARGET_PCI, TARGET_BAND)
            if ok:
                print("  Lock applied. Router will reconnect to target cell.")
            else:
                print("  Failed — command not supported or port is wrong.")
        elif choice == "3":
            ok = remove_lock(ser)
            if ok:
                print("  Lock removed. Router returns to auto cell selection.")
        elif choice == "q":
            break
        else:
            print("  Enter 1, 2, 3 or q.")
        print()


def main():
    print("Scanning for Huawei COM ports...")
    huawei_ports = find_huawei_ports()

    if huawei_ports:
        print(f"Found: {[p.device for p in huawei_ports]}")
    else:
        print("No Huawei ports detected by name. Scanning all ports for AT response...")

    all_ports = [p.device for p in (huawei_ports or serial.tools.list_ports.comports())]

    at_port = None
    for port in all_ports:
        print(f"  Probing {port}...", end=" ", flush=True)
        if probe_port(port):
            print("AT OK")
            at_port = port
            break
        else:
            print("no response")

    if not at_port:
        print("\nNo AT command port found.")
        print("Make sure the USB cable is connected and Huawei drivers are installed.")
        print("Check Device Manager → Ports (COM & LPT) for Huawei entries.")
        sys.exit(1)

    print(f"\nUsing port: {at_port}")
    with serial.Serial(at_port, BAUD_RATE, timeout=TIMEOUT) as ser:
        resp = send_at(ser, "ATI")
        print(f"Modem info: {resp}")
        interactive(ser)


if __name__ == "__main__":
    main()
