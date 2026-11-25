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


def check_update():
    """Self-update path: local mock CDN, temp copy of panel, no service touched."""
    import functools
    import http.server
    import shutil
    import threading
    remote = os.path.join(tmp, "remote")
    local = os.path.join(tmp, "local")
    os.makedirs(remote)
    os.makedirs(local)
    names = ("panel.py", "install.sh", "agent.py")
    for f in names:
        with open(os.path.join(remote, f), "w") as fh:
            fh.write("# REMOTE " + f + "\n")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=remote)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        shutil.copy("/root/kariz-panel/panel.py", os.path.join(local, "panel.py"))
        code = ("import sys; sys.path.insert(0,%r); "
                "import panel; print(','.join(panel.update_files()))" % local)
        e2 = dict(os.environ, KARIZ_BASE="http://127.0.0.1:%d" % srv.server_port)
        out = subprocess.check_output([sys.executable, "-c", code], env=e2, text=True).strip()
        assert out == ",".join(names), out
        for f in names:
            with open(os.path.join(local, f)) as fh:
                assert fh.read() == "# REMOTE " + f + "\n", f
    finally:
        srv.shutdown()


def check_login():
    """Custom login page + signed cookie session. Temp panel, no service touched."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    op = urllib.request.build_opener(NoRedirect)

    def raw(path, method="GET", data=None, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        body = json.dumps(data).encode() if data is not None else None
        r = urllib.request.Request(BASE + path, data=body, headers=h, method=method)
        try:
            with op.open(r, timeout=5) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    s, _, h = raw("/")
    assert s == 302 and h["Location"] == "/login", (s, h.get("Location"))
    s, page, _ = raw("/login")
    assert s == 200 and b"Kariz Panel" in page and b"id=p" in page, "login page failed"
    s, _, _ = raw("/api/servers")
    assert s == 401, s
    s, _, _ = raw("/login", "POST", {"user": "admin", "pass": "wrong"})
    assert s == 401, s
    s, _, h = raw("/login", "POST", {"user": "admin", "pass": "secret123"})
    assert s == 200, s
    cookie = h["Set-Cookie"].split(";")[0]
    s, body, _ = raw("/api/servers", headers={"Cookie": cookie})
    assert s == 200 and isinstance(json.loads(body), list), (s, body)
    print("PASS: login page, redirect gate, bad/good credentials, signed cookie")


try:
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/", timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    s, b = req("/", auth=True)
    assert s == 200 and b"<h1>Kariz panel" in b, "UI failed"

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

    check_login()
    check_update()

    print("PASS: UI, auth, add-server, add-tunnel, forward ports, entry/exit TOML, bad-token, delete, self-update")
    print("--- entry TOML sample ---")
    print(e["toml"])
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
