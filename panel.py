#!/usr/bin/env python3
"""Kariz control panel — stdlib only. Servers, tunnels, forward ports."""

import base64
import hmac
import json
import os
import re
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DB = os.environ.get("KARIZ_PANEL_DB", "/var/lib/kariz-panel/panel.db")
PORT = int(os.environ.get("KARIZ_PANEL_PORT", "28443"))
ADMIN_USER = os.environ.get("KARIZ_PANEL_USER", "")
ADMIN_PASS = os.environ.get("KARIZ_PANEL_PASS", "")


def connect():
    os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS servers("
              "id INTEGER PRIMARY KEY, name TEXT, token TEXT UNIQUE, "
              "address TEXT, last_seen TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS tunnels("
              "id INTEGER PRIMARY KEY, name TEXT, entry INTEGER, exit INTEGER, "
              "tunnel_port INTEGER, transport TEXT, token TEXT, forwards TEXT)")
    return c


def entry_toml(t, forwards):
    lines = ["mode = \"reverse\"", "profile = \"ultraspeed\"", "role = \"entry\"", ""]
    for f in forwards:
        lines += ["[[forward]]",
                  "listen = \"0.0.0.0:%d\"" % int(f["listen"]),
                  "protocol = \"%s\"" % f.get("protocol", "tcp"),
                  "target = \"127.0.0.1:%d\"" % int(f["target"]), ""]
    lines += ["[tunnel]",
              "listen = \"0.0.0.0:%d\"" % int(t["tunnel_port"]),
              "token = \"%s\"" % t["token"],
              "transport = \"%s\"" % t["transport"]]
    return "\n".join(lines) + "\n"


def exit_toml(t, entry_addr):
    return "\n".join([
        "mode = \"reverse\"", "profile = \"ultraspeed\"", "role = \"exit\"", "",
        "[tunnel]",
        "remote = \"%s:%d\"" % (entry_addr, int(t["tunnel_port"])),
        "token = \"%s\"" % t["token"],
        "transport = \"%s\"" % t["transport"]]) + "\n"


def configs_for(c, sid):
    out = []
    for t in c.execute("SELECT * FROM tunnels WHERE entry=? OR exit=?", (sid, sid)):
        fw = json.loads(t["forwards"] or "[]")
        if t["entry"] == sid:
            out.append({"name": t["name"], "role": "entry", "toml": entry_toml(t, fw)})
        elif t["exit"] == sid:
            ent = c.execute("SELECT address,name FROM servers WHERE id=?", (t["entry"],)).fetchone()
            addr = (ent["address"] or ent["name"]) if ent else ""
            out.append({"name": t["name"], "role": "exit", "toml": exit_toml(t, addr)})
    return out


INDEX = r"""<!doctype html><html><head><meta charset=utf-8><title>Kariz panel</title>
<style>
body{font-family:system-ui,-apple-system,sans-serif;background:#0d0d0d;color:#e0e0e0;max-width:800px;margin:40px auto;line-height:1.5}
input,select,button{font:14px system-ui;padding:8px;margin:4px;background:#1a1a1a;color:#eee;border:1px solid #333;border-radius:4px}
button{cursor:pointer;background:#252525;transition:background 0.2s}
button:hover{background:#333}
pre{background:#050505;padding:15px;overflow:auto;border-radius:6px;border:1px solid #222}
.card{border:1px solid #222;padding:16px;margin:12px 0;border-radius:8px;background:#121212;transition:transform 0.2s, box-shadow 0.2s}
.card:hover{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,0.3);border-color:#444}
.del{color:#f55;cursor:pointer;margin-left:8px;font-weight:bold}
h1,h2{font-weight:600}
h2{border-bottom:1px solid #333;padding-bottom:8px;margin-top:30px}
</style>
</head><body><h1>Kariz panel</h1>
<h2>Servers</h2><div id=servers></div>
<div class=card>
<input id=sname placeholder="server name"><input id=saddr placeholder="address (optional)">
<button onclick=addServer()>Add server</button></div>
<h2>Tunnels</h2><div id=tunnels></div>
<div class=card>
<input id=tname placeholder="tunnel name"><br>
entry <select id=tentry></select> exit <select id=texit></select><br>
port <input id=tport type=number value=3080> transport <select id=ttrans>
<option>auto</option><option>tcp</option><option>tcpmux</option><option>ws</option>
<option>wss</option><option>quic</option><option>kcp</option></select>
<div id=fw></div><button onclick=addFw()>+ forward</button>
<button onclick=addTunnel()>Add tunnel</button></div>
<pre id=out></pre><script>
const q=s=>document.querySelector(s), esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function out(s){q('#out').textContent=s}
async function api(p,m,b){let r=await fetch(p,{method:m||'GET',headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});if(!r.ok)throw Error(await r.text());return r.json()}
async function load(){let [s,t]=await Promise.all([api('/api/servers'),api('/api/tunnels')]);
 q('#servers').innerHTML=s.map(x=>`<div class=card>${esc(x.name)} <small>${esc(x.address||'')} ${esc(x.last_seen||'')}</small> <span class=del onclick=del('servers',${x.id})>\u2715</span><br><small>token: ${esc(x.token)}</small></div>`).join('')||'none';
 q('#tunnels').innerHTML=t.map(x=>`<div class=card>${esc(x.name)} ${esc(x.entry)}\u2192${esc(x.exit)} :${x.tunnel_port} ${esc(x.transport)} <span class=del onclick=del('tunnels',${x.id})>\u2715</span><br><small>listen/target: ${JSON.stringify(x.forwards)}</small></div>`).join('')||'none';
 let opts=s.map(x=>`<option value=${x.id}>${esc(x.name)}</option>`).join('');
 q('#tentry').innerHTML=opts;q('#texit').innerHTML=opts}
async function addServer(){let b=await api('/api/servers','POST',{name:q('#sname').value||'server',address:q('#saddr').value});
 out('On target server, run this one line:\n\ncurl -fsSL https://cdn.jsdelivr.net/gh/Hosein21378/kariz-panel@main/install.sh | bash -s -- --join '+b.token+' --panel '+location.origin);load()}
async function addTunnel(){let fw=[...q('#fw').children].map(d=>({listen:+d.querySelector('.l').value,target:+d.querySelector('.t').value,protocol:'tcp'})).filter(x=>x.listen&&x.target);
 await api('/api/tunnels','POST',{name:q('#tname').value||'tun',entry:+q('#tentry').value,exit:+q('#texit').value,tunnel_port:+q('#tport').value,transport:q('#ttrans').value,forwards:fw});load()}
function addFw(){let d=document.createElement('div');d.innerHTML='<input class=l type=number placeholder=listen><input class=t type=number placeholder=target>';q('#fw').appendChild(d)}
async function del(k,id){await api('/api/'+k+'/'+id,'DELETE');load()}
load()</script></body></html>"""


def _authorized(handler):
    if not ADMIN_USER:
        return True
    hdr = handler.headers.get("Authorization", "")
    if not hdr.startswith("Basic "):
        return False
    try:
        u, p = base64.b64decode(hdr[6:]).decode().split(":", 1)
    except Exception:
        return False
    return hmac.compare_digest(u, ADMIN_USER) and hmac.compare_digest(p, ADMIN_PASS)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _gate(self, path):
        # Agent endpoints carry their own secret (the join token).
        if path.startswith("/api/agent/") or _authorized(self):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Kariz panel"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj))

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path)
        if not self._gate(u.path):
            return
        q = parse_qs(u.query)
        c = connect()
        if u.path == "/":
            return self._send(200, INDEX, "text/html")
        if u.path == "/api/servers":
            return self._json([dict(r) for r in c.execute(
                "SELECT id,name,address,last_seen FROM servers")])
        if u.path == "/api/tunnels":
            return self._json([dict(r) for r in c.execute("SELECT * FROM tunnels")])
        if u.path == "/api/agent/config":
            tok = q.get("token", [""])[0]
            s = c.execute("SELECT id FROM servers WHERE token=?", (tok,)).fetchone()
            if not s:
                return self._json({"error": "bad token"}, 401)
            c.execute("UPDATE servers SET last_seen=datetime('now') WHERE id=?", (s["id"],))
            c.commit()
            return self._json(configs_for(c, s["id"]))
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        if not self._gate(u.path):
            return
        b = self._body()
        c = connect()
        if u.path == "/api/servers":
            tok = "kz1_" + secrets.token_hex(16)
            cur = c.execute("INSERT INTO servers(name,token,address) VALUES(?,?,?)",
                            (b.get("name") or "server", tok, b.get("address", "")))
            c.commit()
            return self._json({"id": cur.lastrowid, "token": tok})
        if u.path == "/api/agent/register":
            r = c.execute("UPDATE servers SET address=?,last_seen=datetime('now') WHERE token=?",
                          (b.get("address", ""), b.get("token", "")))
            c.commit()
            return self._json({"ok": r.rowcount > 0})
        if u.path == "/api/tunnels":
            name = str(b.get("name", ""))
            if not re.fullmatch(r"[a-z0-9-]+", name):
                return self._json({"error": "bad name"}, 400)
            tok = secrets.token_hex(24)
            cur = c.execute("INSERT INTO tunnels(name,entry,exit,tunnel_port,transport,token,forwards) "
                            "VALUES(?,?,?,?,?,?,?)",
                            (name, int(b["entry"]), int(b["exit"]), int(b["tunnel_port"]),
                             b.get("transport", "auto"), tok, json.dumps(b.get("forwards", []))))
            c.commit()
            return self._json({"id": cur.lastrowid})
        return self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        u = urlparse(self.path)
        if not self._gate(u.path):
            return
        parts = u.path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] in ("servers", "tunnels"):
            c = connect()
            c.execute("DELETE FROM %s WHERE id=?" % parts[1], (parts[2],))
            c.commit()
            return self._json({"ok": True})
        return self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
