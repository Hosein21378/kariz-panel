#!/usr/bin/env python3
"""Self-check: panel API + TOML generation. No frameworks, no servers touched."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

PORT = 28999
BASE = f"http://127.0.0.1:{PORT}"
tmp = tempfile.mkdtemp(prefix="kariz-test-")
env = dict(os.environ, KARIZ_PANEL_DB=f"{tmp}/panel.db",
           KARIZ_PANEL_PORT=str(PORT), KARIZ_PANEL_USER="admin",
           KARIZ_PANEL_PASS="secret123")
proc = subprocess.Popen([sys.executable, "/root/kariz-panel/panel.py"],
                        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def req(path, method="GET", data=None, auth=False):
    body = json.dumps(data).encode() if data is not None else None
    h = {"Content-Type": "application/json"}
    if auth:
        h["Authorization"] = "Basic " + base64.b64encode(b"admin:secret123").decode()
    r = urllib.request.Request(BASE + path, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            raw = resp.read()
            return resp.status, (raw if path == "/" else json.loads(raw))
    except urllib.error.HTTPError as e:
        return e.code, e.read()


try:
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/", timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    s, b = req("/", auth=True)
    assert s == 200 and b"<h1>Kariz panel</h1>" in b, "UI failed"

    s, _ = req("/api/servers")
    assert s == 401, f"auth gate failed: {s}"

    s, a = req("/api/servers", "POST", {"name": "entry-srv", "address": "1.2.3.4"}, auth=True)
    assert s == 200 and a["token"].startswith("kz1_"), a
    s, z = req("/api/servers", "POST", {"name": "exit-srv", "address": "5.6.7.8"}, auth=True)
    assert s == 200 and z["token"].startswith("kz1_"), z

    fw = [{"listen": 1080, "target": 8793, "protocol": "tcp"},
          {"listen": 4440, "target": 8792, "protocol": "tcp"}]
    s, t = req("/api/tunnels", "POST",
               {"name": "arno-test", "entry": a["id"], "exit": z["id"],
                "tunnel_port": 3080, "transport": "auto", "forwards": fw}, auth=True)
    assert s == 200 and t["id"] > 0, t

    q = urllib.parse.urlencode({"token": a["token"]})
    s, cfg = req("/api/agent/config?" + q)
    assert s == 200 and len(cfg) == 1, cfg
    e = cfg[0]
    assert e["role"] == "entry" and e["name"] == "arno-test"
    assert 'mode = "reverse"' in e["toml"]
    assert 'profile = "ultraspeed"' in e["toml"]
    assert 'role = "entry"' in e["toml"]
    assert 'listen = "0.0.0.0:1080"' in e["toml"]
    assert 'target = "127.0.0.1:8793"' in e["toml"]
    assert 'listen = "0.0.0.0:3080"' in e["toml"]

    s, cfg2 = req("/api/agent/config?" + urllib.parse.urlencode({"token": z["token"]}))
    assert s == 200 and len(cfg2) == 1, cfg2
    x = cfg2[0]
    assert x["role"] == "exit"
    assert 'role = "exit"' in x["toml"]
    assert 'remote = "1.2.3.4:3080"' in x["toml"], x["toml"]

    s, _ = req("/api/agent/config?token=bad")
    assert s == 401, f"bad token gate failed: {s}"

    s, _ = req("/api/tunnels/" + str(t["id"]), "DELETE", auth=True)
    assert s == 200
    s, cfg = req("/api/agent/config?" + q)
    assert len(cfg) == 0, "delete did not propagate"

    print("PASS: UI, auth, add-server, add-tunnel, forward ports, entry/exit TOML, bad-token, delete")
    print("--- entry TOML sample ---")
    print(e["toml"])
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
