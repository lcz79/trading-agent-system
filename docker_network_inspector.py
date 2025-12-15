#!/usr/bin/env python3
import json
import subprocess

def sh(*args):
    return subprocess.check_output(args, text=True).strip()

def main():
    # list container names (running)
    names = sh("docker", "ps", "--format", "{{.Names}}").splitlines()
    rows = []

    for name in names:
        raw = sh("docker", "inspect", name)
        data = json.loads(raw)[0]
        networks = data.get("NetworkSettings", {}).get("Networks", {}) or {}
        for net_name, net in networks.items():
            ip = net.get("IPAddress", "")
            rows.append((name, net_name, ip))

    # sort by network then ip then name
    rows.sort(key=lambda x: (x[1], tuple(int(p) if p.isdigit() else 0 for p in x[2].split(".")) if x[2] else (999,), x[0]))

    print(f"{'CONTAINER':35} {'NETWORK':35} {'IP':15}")
    print("-" * 90)
    for name, net_name, ip in rows:
        print(f"{name:35} {net_name:35} {ip:15}")

if __name__ == "__main__":
    main()
