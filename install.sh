#!/usr/bin/env bash
# Kariz panel — one-line installer. Default: panel. With --join: agent.
set -euo pipefail

BASE="${KARIZ_BASE:-https://cdn.jsdelivr.net/gh/Hosein21378/kariz-panel@main}"
PREFIX="${KARIZ_PREFIX:-/opt/kariz-panel}"
STATE="${KARIZ_STATE:-/var/lib/kariz-panel}"
SYSTEMD="${KARIZ_SYSTEMD:-/etc/systemd/system}"
PORT="${KARIZ_PORT:-28443}"
ADMIN_USER="${KARIZ_USER:-admin}"
PY="${KARIZ_PY:-python3}"
SRCDIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --from-dir) SRCDIR="$2"; shift 2 ;;
    --join) JOIN="$2"; shift 2 ;;
    --panel) PANEL_URL="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --no-service) NO_SERVICE=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

get_file() { # remote-name dest
  if [ -n "$SRCDIR" ] && [ -f "$SRCDIR/$1" ]; then cp "$SRCDIR/$1" "$2"; return; fi
  if command -v curl >/dev/null; then curl -fsSL "$BASE/$1" -o "$2"
  elif command -v wget >/dev/null; then wget -qO "$2" "$BASE/$1"
  else echo "curl or wget required" >&2; exit 1; fi
}

start_unit() {
  [ -n "${NO_SERVICE:-}" ] && return 0
  command -v systemctl >/dev/null || return 0
  systemctl daemon-reload
  systemctl enable --now "$1"
  systemctl restart "$1"   # re-install must reload replaced files into the live process
}

mkdir -p "$PREFIX" "$STATE" "$SYSTEMD"

if [ -n "${JOIN:-}" ]; then
  [ -n "${PANEL_URL:-}" ] || { echo "--panel required with --join" >&2; exit 1; }
  get_file agent.py "$PREFIX/agent.py"
  cat > "$STATE/agent.env" <<EOF
KARIZ_JOIN=$JOIN
KARIZ_PANEL=$PANEL_URL
KARIZ_DIR=${KARIZ_DIR:-/etc/kariz}
KARIZ_INTERVAL=${KARIZ_INTERVAL:-30}
EOF
  chmod 600 "$STATE/agent.env"
  cat > "$SYSTEMD/kariz-agent.service" <<EOF
[Unit]
Description=Kariz panel agent
After=network-online.target
Wants=network-online.target
[Service]
EnvironmentFile=$STATE/agent.env
ExecStart=$PY $PREFIX/agent.py
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
  start_unit kariz-agent
  echo "agent installed: join=$JOIN panel=$PANEL_URL"
  exit 0
fi

command -v "$PY" >/dev/null || { echo "$PY not found" >&2; exit 1; }
get_file panel.py "$PREFIX/panel.py"
if [ -f "$STATE/panel.env" ]; then
  . "$STATE/panel.env"          # re-install: keep existing credentials
  PASS="$KARIZ_PANEL_PASS"
else
  PASS="${KARIZ_PASS:-$($PY -c 'import secrets;print(secrets.token_hex(8))')}"
  cat > "$STATE/panel.env" <<EOF
KARIZ_PANEL_DB=$STATE/panel.db
KARIZ_PANEL_PORT=$PORT
KARIZ_PANEL_USER=$ADMIN_USER
KARIZ_PANEL_PASS=$PASS
EOF
  chmod 600 "$STATE/panel.env"
fi
cat > "$SYSTEMD/kariz-panel.service" <<EOF
[Unit]
Description=Kariz control panel
After=network-online.target
Wants=network-online.target
[Service]
EnvironmentFile=$STATE/panel.env
ExecStart=$PY $PREFIX/panel.py
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
start_unit kariz-panel
echo "panel installed"
echo "  URL:  http://<this-host>:$PORT"
echo "  user: $ADMIN_USER"
echo "  pass: $PASS"
echo "  db:   $STATE/panel.db"
