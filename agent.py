#!/usr/bin/env python3
"""Kariz panel agent: join panel, pull tunnel configs, write TOMLs, restart kariz."""
import json
import os
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

JOIN = os.environ["KARIZ_JOIN"]
PANEL = os.environ["KARIZ_PANEL"].rstrip("/")
KARIZ_DIR = os.environ.get("KARIZ_DIR", "/etc/kariz")
INTERVAL = int(os.environ.get("KARIZ_INTERVAL", "30"))


def api(path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(PANEL + path, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def apply(cfg):
    name = cfg["name"]
    if not name or not all(c.isalnum() or c == "-" for c in name):
        return
    path = Path(KARIZ_DIR) / (name + ".toml")
    if path.exists() and path.read_text() == cfg["toml"]:
        return
    path.write_text(cfg["toml"])
    subprocess.run(["systemctl", "enable", "--now", "kariz@" + name],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    subprocess.run(["systemctl", "restart", "kariz@" + name],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def main():
    try:
        api("/api/agent/register",
            {"token": JOIN, "address": socket.gethostbyname(socket.gethostname())})
    except Exception as exc:
        print("register failed:", exc, flush=True)
    Path(KARIZ_DIR).mkdir(parents=True, exist_ok=True)
    while True:
        try:
            query = urllib.parse.urlencode({"token": JOIN})
            for cfg in api("/api/agent/config?" + query):
                apply(cfg)
        except Exception as exc:
            print("poll failed:", exc, flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
