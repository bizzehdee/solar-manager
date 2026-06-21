#!/usr/bin/env bash
#
# SolarVolt native installer (plan.md §13, task T019).
# Fresh Ubuntu / Raspberry Pi → a running, boot-persistent service in one go.
#
#   sudo ./install.sh                 # install / upgrade in place
#   sudo ./install.sh --enable-control   # also turn write-back on (default: off)
#   ./install.sh --check              # validate prerequisites, change nothing (no root)
#   ./install.sh --help
#
# It installs *in place*: the venv and frontend build live in this working copy and the
# systemd unit points back at it, so updating is just `git pull && sudo ./install.sh`.
set -euo pipefail

SERVICE_NAME="solarvolt"
DB_DIR="/var/lib/solarvolt"
ENV_DIR="/etc/solarvolt"
ENV_FILE="${ENV_DIR}/solarvolt.env"
UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"
UDEV_DST="/etc/udev/rules.d/99-solarvolt-rs485.rules"
DEFAULT_PORT=8000

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="${REPO_ROOT}/packaging"
VENV="${REPO_ROOT}/.venv"
WORKDIR="${REPO_ROOT}/backend"
FRONTEND_DIST="${REPO_ROOT}/frontend/dist/solarvolt/browser"

# Flags / defaults
SERVICE_USER="${SUDO_USER:-}"
PORT="${DEFAULT_PORT}"
DO_BUILD=1
ENABLE_CONTROL=0
CHECK_ONLY=0

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<EOF
SolarVolt native installer

Usage: sudo ./install.sh [options]

Options:
  --user NAME         Run the service as this user (default: the sudo invoker)
  --port N            HTTP port to serve on (default: ${DEFAULT_PORT})
  --enable-control    Enable inverter write-back (default: off / monitoring only)
  --no-build          Skip the frontend build (use an existing dist/ or release bundle)
  --check             Validate prerequisites and print the plan; make no changes
  -h, --help          Show this help

Updating: git pull && sudo ./install.sh
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --user) SERVICE_USER="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --enable-control) ENABLE_CONTROL=1; shift ;;
    --no-build) DO_BUILD=0; shift ;;
    --check) CHECK_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

# ── Read-only validation (always runs; --check stops after this) ──────────────
log "Validating environment"

[ -f "${REPO_ROOT}/backend/requirements.txt" ] || die "backend/requirements.txt not found — run from the repo"
[ -f "${PKG}/systemd/solarvolt.service.tmpl" ] || die "packaging templates missing"

command -v python3 >/dev/null 2>&1 || die "python3 is required (apt install python3 python3-venv)"
python3 -m venv --help >/dev/null 2>&1 || die "the python3 venv module is missing (apt install python3-venv)"
ok "python3 + venv present"

case "$PORT" in
  ''|*[!0-9]*) die "--port must be a number (got '${PORT}')" ;;
esac

if [ -z "$SERVICE_USER" ]; then
  die "could not determine the service user — pass --user NAME (running as root with no SUDO_USER)"
fi
id "$SERVICE_USER" >/dev/null 2>&1 || die "user '${SERVICE_USER}' does not exist"
[ "$SERVICE_USER" = "root" ] && warn "running the service as root is not recommended; consider --user NAME"
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
ok "service user: ${SERVICE_USER} (group ${SERVICE_GROUP})"

if [ "$DO_BUILD" -eq 1 ]; then
  if command -v npm >/dev/null 2>&1; then
    ok "npm present — frontend will be built"
  elif [ -d "$FRONTEND_DIST" ]; then
    warn "npm not found but a build exists — will reuse it (pass --no-build to silence)"
    DO_BUILD=0
  else
    die "npm is required to build the frontend (apt install nodejs npm), or pass --no-build with a prebuilt dist/"
  fi
elif [ ! -d "$FRONTEND_DIST" ]; then
  warn "--no-build set but no frontend build at ${FRONTEND_DIST} — the UI will not be served until you build it"
fi

log "Plan:"
printf '    service     %s.service (port %s, user %s)\n' "$SERVICE_NAME" "$PORT" "$SERVICE_USER"
printf '    workdir     %s\n' "$WORKDIR"
printf '    venv        %s\n' "$VENV"
printf '    database    %s\n' "${DB_DIR}/solarvolt.db"
printf '    env file    %s\n' "$ENV_FILE"
printf '    control     %s\n' "$([ "$ENABLE_CONTROL" -eq 1 ] && echo enabled || echo 'disabled (monitoring only)')"

if [ "$CHECK_ONLY" -eq 1 ]; then
  log "Dry run (--check) complete — no changes made."
  exit 0
fi

[ "$(id -u)" -eq 0 ] || die "this installer needs root — run: sudo ./install.sh"

run_as_user() { sudo -u "$SERVICE_USER" -H "$@"; }

# ── Python venv + backend deps ───────────────────────────────────────────────
log "Setting up the Python virtualenv"
if [ ! -d "$VENV" ]; then
  run_as_user python3 -m venv "$VENV"
fi
run_as_user "${VENV}/bin/pip" install --quiet --upgrade pip
run_as_user "${VENV}/bin/pip" install --quiet -r "${REPO_ROOT}/backend/requirements.txt"
ok "backend dependencies installed"

# ── Frontend build ───────────────────────────────────────────────────────────
if [ "$DO_BUILD" -eq 1 ]; then
  log "Building the frontend (this can take a few minutes on a Pi)"
  run_as_user bash -c "cd '${REPO_ROOT}/frontend' && npm ci && npm run build"
  ok "frontend built → ${FRONTEND_DIST}"
fi

# ── Data directory + config ──────────────────────────────────────────────────
log "Creating ${DB_DIR}"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0750 "$DB_DIR"

log "Installing config"
install -d -m 0755 "$ENV_DIR"
if [ -f "$ENV_FILE" ]; then
  ok "kept existing ${ENV_FILE}"
else
  install -m 0640 -g "$SERVICE_GROUP" "${PKG}/env/solarvolt.env.example" "$ENV_FILE"
  if [ "$ENABLE_CONTROL" -eq 1 ]; then
    sed -i 's/^SOLARVOLT_ENABLE_CONTROL=.*/SOLARVOLT_ENABLE_CONTROL=true/' "$ENV_FILE"
  fi
  ok "wrote ${ENV_FILE}"
fi

# ── Serial access: dialout group + udev pin ──────────────────────────────────
log "Granting serial access (dialout group)"
if id -nG "$SERVICE_USER" | tr ' ' '\n' | grep -qx dialout; then
  ok "${SERVICE_USER} already in dialout"
else
  usermod -aG dialout "$SERVICE_USER"
  ok "added ${SERVICE_USER} to dialout (re-login or reboot for shells to pick it up)"
fi

log "Pinning the USB-RS485 adapter (udev)"
if [ -e "$UDEV_DST" ]; then
  ok "kept existing ${UDEV_DST}"
else
  _ttys=()
  for _d in /dev/ttyUSB*; do [ -e "$_d" ] && _ttys+=("$_d"); done
  if [ "${#_ttys[@]}" -eq 1 ]; then
    dev="${_ttys[0]}"
    vid="$(udevadm info -a -n "$dev" 2>/dev/null | sed -n 's/.*ATTRS{idVendor}=="\([0-9a-fA-F]*\)".*/\1/p' | head -1)"
    pid="$(udevadm info -a -n "$dev" 2>/dev/null | sed -n 's/.*ATTRS{idProduct}=="\([0-9a-fA-F]*\)".*/\1/p' | head -1)"
    if [ -n "$vid" ] && [ -n "$pid" ]; then
      sed -e "s/@IDVENDOR@/${vid}/" -e "s/@IDPRODUCT@/${pid}/" \
        "${PKG}/udev/99-solarvolt-rs485.rules.example" >"$UDEV_DST"
      udevadm control --reload && udevadm trigger || true
      ok "pinned ${dev} (${vid}:${pid}) → /dev/solarvolt-rs485"
    else
      warn "couldn't read adapter IDs; see ${PKG}/udev/99-solarvolt-rs485.rules.example to pin it by hand"
    fi
  elif [ "${#_ttys[@]}" -eq 0 ]; then
    warn "no /dev/ttyUSB* adapter plugged in — pin it later (see packaging/udev/…) or use the dummy"
  else
    warn "multiple USB-serial adapters found — pin the right one by hand (see packaging/udev/…)"
  fi
fi

# ── systemd unit ─────────────────────────────────────────────────────────────
log "Installing the systemd service"
sed \
  -e "s|@USER@|${SERVICE_USER}|g" \
  -e "s|@GROUP@|${SERVICE_GROUP}|g" \
  -e "s|@WORKDIR@|${WORKDIR}|g" \
  -e "s|@PYTHON@|${VENV}/bin/python|g" \
  -e "s|@ENVFILE@|${ENV_FILE}|g" \
  -e "s|@DBDIR@|${DB_DIR}|g" \
  -e "s|@PORT@|${PORT}|g" \
  "${PKG}/systemd/solarvolt.service.tmpl" >"$UNIT_DST"
chmod 0644 "$UNIT_DST"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
systemctl restart "${SERVICE_NAME}.service"
ok "service enabled and started"

# ── Done ─────────────────────────────────────────────────────────────────────
ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
log "SolarVolt is installed and running."
printf '    UI:       http://%s:%s/\n' "${ip:-<this-host>}" "$PORT"
printf '    Config:   %s   (edit, then: sudo systemctl restart %s)\n' "$ENV_FILE" "$SERVICE_NAME"
printf '    Logs:     journalctl -u %s -f\n' "$SERVICE_NAME"
printf '    Status:   systemctl status %s\n' "$SERVICE_NAME"
[ "$ENABLE_CONTROL" -eq 1 ] || printf '    Control:  off (monitoring only) — set SOLARVOLT_ENABLE_CONTROL=true to enable write-back\n'
