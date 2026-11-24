#!/usr/bin/env python3
"""Kariz control panel — stdlib only. Servers, tunnels, forward ports."""

import base64
import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
import urllib.request
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


def update_files():
    """Download latest files next to the running panel.py. Returns files."""
    base = os.environ.get("KARIZ_BASE", "https://cdn.jsdelivr.net/gh/Hosein21378/kariz-panel@main")
    prefix = os.path.dirname(os.path.abspath(__file__))
    got = []
    for f in ("panel.py", "install.sh", "agent.py"):
        data = urllib.request.urlopen(base + "/" + f, timeout=30).read()
        if f == "panel.py":
            compile(data, f, "exec")  # never replace running panel with broken syntax
        tmp = os.path.join(prefix, f + ".new")
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, os.path.join(prefix, f))
        got.append(f)
    return got


INDEX = r"""<!doctype html><html lang=fa dir=rtl><head><meta charset=utf-8><title>Kariz panel</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:#0b0d12;color:#e2e8f0;margin:0;line-height:1.5}
.app{display:flex;min-height:100vh}
.sidebar{width:236px;flex:0 0 236px;background:#11141c;border-inline-start:1px solid #202532;display:flex;flex-direction:column;padding:16px 12px;transition:width .2s,flex-basis .2s;overflow:hidden}
.sidebar.collapsed{width:64px;flex-basis:64px}
.brand{display:flex;align-items:center;gap:10px;padding:4px 8px 18px;border-bottom:1px solid #202532;margin-bottom:14px;white-space:nowrap}
.brand .logo{font-size:22px}
.brand h1{font-size:16px;margin:0;font-weight:700;color:#fff}
nav{display:flex;flex-direction:column;gap:4px;flex:1}
nav a{padding:10px 12px;border-radius:8px;color:#9aa5bb;cursor:pointer;display:flex;align-items:center;gap:12px;font-size:14px;white-space:nowrap;transition:background .15s,color .15s}
nav a:hover{background:#1a1f2c;color:#e2e8f0}
nav a.active{background:#1d2440;color:#8fa6ff}
.foot{margin-top:auto;display:flex;flex-direction:column;gap:8px}
button{font:13px system-ui;padding:9px 12px;background:#1e2433;color:#e2e8f0;border:1px solid #2b3245;border-radius:8px;cursor:pointer;transition:background .15s,transform .15s}
button:hover{background:#2a3247}
button:active{transform:scale(.98)}
.btn-accent{background:#4f6ef7;border-color:#4f6ef7;color:#fff}
.btn-accent:hover{background:#3d59dd}
.upd{display:flex;align-items:center;gap:8px}
.sidebar.collapsed .brand h1,.sidebar.collapsed nav a span,.sidebar.collapsed .lbl{display:none}
main{flex:1;min-width:0}
.topbar{height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;border-bottom:1px solid #202532;background:#0e1118}
.topbar h2{margin:0;font-size:18px;font-weight:600}
.hint{color:#6b7690;font-size:12px}
.content{padding:24px 28px;max-width:1100px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:24px}
.stat{background:#151924;border:1px solid #232a3a;border-radius:12px;padding:18px;transition:transform .2s,box-shadow .2s,border-color .2s}
.stat:hover{transform:translateY(-3px);box-shadow:0 8px 20px rgba(0,0,0,.35);border-color:#3a4a6b}
.stat .v{font-size:28px;font-weight:700;color:#8fa6ff}
.stat .l{color:#8b95a8;font-size:13px;margin-top:4px}
.view{display:none}
.section{background:#12161f;border:1px solid #232a3a;border-radius:12px;padding:20px;margin-bottom:20px}
.section h3{margin:0 0 14px;font-size:15px;font-weight:600}
.card{background:#171c28;border:1px solid #262d3e;border-radius:10px;padding:14px;margin:10px 0;transition:transform .2s,box-shadow .2s,border-color .2s}
.card:hover{transform:translateY(-2px);box-shadow:0 6px 16px rgba(0,0,0,.35);border-color:#3a4a6b}
.muted{color:#8b95a8;font-size:12px}
.del{color:#ff6b6b;cursor:pointer;font-weight:bold;margin-inline-end:8px}
.token{font-family:ui-monospace,monospace;font-size:11px;color:#7f8aa3;word-break:break-all;direction:ltr;display:inline-block}
input,select{font:13px system-ui;padding:9px 10px;background:#0e1118;color:#e2e8f0;border:1px solid #2b3245;border-radius:8px;margin:4px 4px 4px 0}
input:focus,select:focus{outline:none;border-color:#4f6ef7}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px}
pre{background:#080a0f;padding:14px;border-radius:10px;border:1px solid #202532;overflow:auto;font-size:12px;max-height:220px;color:#9fe0a0;direction:ltr;text-align:left}
.empty{color:#6b7690;font-size:13px;padding:8px 0}
@media(max-width:720px){.sidebar{width:64px;flex-basis:64px}.brand h1,nav a span,.lbl{display:none}.content{padding:16px}}
</style></head><body><div class=app>
<aside class=sidebar id=sidebar>
<div class=brand><span class=logo>🛡️</span><h1>Kariz panel</h1></div>
<nav>
<a data-view=dashboard class=active onclick="view('dashboard')">📊 <span>داشبورد</span></a>
<a data-view=servers onclick="view('servers')">🖥️ <span>سرورها</span></a>
<a data-view=tunnels onclick="view('tunnels')">🔐 <span>تونل‌ها</span></a>
</nav>
<div class=foot>
<button class=upd onclick=updatePanel() title="بروزرسانی">🔄 <span class=lbl>بروزرسانی</span></button>
<button onclick="q('#sidebar').classList.toggle('collapsed')" title="جمع کردن منو">☰ <span class=lbl>جمع کردن</span></button>
</div>
</aside>
<main>
<div class=topbar><h2 id=page-title>داشبورد</h2><span class=hint>Kariz Control Panel</span></div>
<div class=content>
<div class=stats>
<div class=stat><div class=v id=st-servers>0</div><div class=l>سرورها</div></div>
<div class=stat><div class=v id=st-tunnels>0</div><div class=l>تونل‌ها</div></div>
<div class=stat><div class=v id=st-fw>0</div><div class=l>پورت‌های فوروارد</div></div>
</div>
<div class="view" id=v-dashboard style="display:block">
<div class=section><h3>نمای کلی</h3><div class=muted>سرورها و تونل‌های فعال خود را مدیریت کنید.</div>
<div class=row><button class=btn-accent onclick="view('servers')">+ افزودن سرور</button><button onclick="view('tunnels')">+ ساخت تونل</button></div></div>
<div class=section><h3>آخرین سرورها</h3><div id=dash-servers></div></div>
<div class=section><h3>آخرین تونل‌ها</h3><div id=dash-tunnels></div></div>
</div>
<div class="view" id=v-servers>
<div class=section><h3>سرورها</h3><div id=servers></div>
<div class=row><input id=sname placeholder="نام سرور"><input id=saddr placeholder="آدرس (اختیاری)"><button class=btn-accent onclick=addServer()>افزودن سرور</button></div></div>
</div>
<div class="view" id=v-tunnels>
<div class=section><h3>تونل‌ها</h3><div id=tunnels></div>
<div class=row><input id=tname placeholder="نام تونل"></div>
<div class=row>entry <select id=tentry></select> exit <select id=texit></select>
port <input id=tport type=number value=3080> transport <select id=ttrans>
<option>auto</option><option>tcp</option><option>tcpmux</option><option>ws</option><option>wss</option><option>quic</option><option>kcp</option></select></div>
<div id=fw></div>
<div class=row><button onclick=addFw()>+ فوروارد</button><button class=btn-accent onclick=addTunnel()>ساخت تونل</button></div></div>
</div>
<pre id=out></pre>
</div>
</main></div>
<script>
const q=s=>document.querySelector(s),qa=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
let SERVERS=[],TUNNELS=[];
function out(s){q('#out').textContent=s}
async function api(p,m,b){let r=await fetch(p,{method:m||'GET',headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});if(!r.ok)throw Error(await r.text());return r.json()}
function view(n){qa('nav a').forEach(a=>a.classList.toggle('active',a.dataset.view===n));qa('.view').forEach(v=>v.style.display=v.id==='v-'+n?'block':'none');q('#page-title').textContent={dashboard:'داشبورد',servers:'سرورها',tunnels:'تونل‌ها'}[n]}
function serverCard(x){return `<div class=card>${esc(x.name)} <small class=muted>${esc(x.address||'')} ${esc(x.last_seen||'')}</small> <span class=del onclick="del('servers',${x.id})">✕</span><br><span class=token>token: ${esc(x.token)}</span></div>`}
function tunnelCard(x){return `<div class=card>${esc(x.name)} ${esc(x.entry)}→${esc(x.exit)} :${x.tunnel_port} ${esc(x.transport)} <span class=del onclick="del('tunnels',${x.id})">✕</span><br><span class=token>${esc(x.forwards||'[]')}</span></div>`}
async function load(){[SERVERS,TUNNELS]=await Promise.all([api('/api/servers'),api('/api/tunnels')]);
 q('#st-servers').textContent=SERVERS.length;q('#st-tunnels').textContent=TUNNELS.length;
 q('#st-fw').textContent=TUNNELS.reduce((n,t)=>n+((t.forwards&&JSON.parse(t.forwards))||[]).length,0);
 const sc=SERVERS.map(serverCard).join('')||'<div class=empty>هیچ سروری وجود ندارد</div>';
 const tc=TUNNELS.map(tunnelCard).join('')||'<div class=empty>هیچ تونلی وجود ندارد</div>';
 q('#servers').innerHTML=sc;q('#dash-servers').innerHTML=sc;
 q('#tunnels').innerHTML=tc;q('#dash-tunnels').innerHTML=tc;
 let opts=SERVERS.map(x=>`<option value=${x.id}>${esc(x.name)}</option>`).join('');
 q('#tentry').innerHTML=opts;q('#texit').innerHTML=opts}
async function addServer(){let b=await api('/api/servers','POST',{name:q('#sname').value||'server',address:q('#saddr').value});
 out('On target server, run this one line:\n\ncurl -fsSL https://cdn.jsdelivr.net/gh/Hosein21378/kariz-panel@main/install.sh | bash -s -- --join '+b.token+' --panel '+location.origin);load()}
async function addTunnel(){let fw=[...q('#fw').children].map(d=>({listen:+d.querySelector('.l').value,target:+d.querySelector('.t').value,protocol:'tcp'})).filter(x=>x.listen&&x.target);
 await api('/api/tunnels','POST',{name:q('#tname').value||'tun',entry:+q('#tentry').value,exit:+q('#texit').value,tunnel_port:+q('#tport').value,transport:q('#ttrans').value,forwards:fw});load()}
function addFw(){let d=document.createElement('div');d.innerHTML='<input class=l type=number placeholder=listen><input class=t type=number placeholder=target>';q('#fw').appendChild(d)}
async function del(k,id){await api('/api/'+k+'/'+id,'DELETE');load()}
async function updatePanel(){out('Updating from remote...');try{let r=await api('/api/update','POST');out('Updated: '+r.files.join(', ')+'. Service restarting...')}catch(e){out('Update failed: '+e.message)}}
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
        if u.path == "/api/update":
            try:
                files = update_files()
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            # Restart service after response is flushed.
            subprocess.Popen(
                ["sh", "-c", "sleep 1; systemctl restart kariz-panel"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            return self._json({"ok": True, "files": files})
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
