#!/usr/bin/env bash
#
# SolarVolt uninstaller (plan.md §13, task T019). Removes the systemd service and udev
# rule. By default it KEEPS your data (database) and config so a re-install resumes where
# you left off; pass --purge to delete those too.
#
#   sudo ./uninstall.sh            # stop + remove the service, keep data/config
#   sudo ./uninstall.sh --purge    # also delete the database, config and udev rule
#   ./uninstall.sh --help
#
# It does not touch this working copy (the venv / frontend build) — just `rm -rf` the repo
# afterwards if you want it gone.
set -euo pipefail

SERVICE_NAME="solarvolt"
DB_DIR="/var/lib/solarvolt"
ENV_DIR="/etc/solarvolt"
UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"
UDEV_DST="/etc/udev/rules.d/99-solarvolt-rs485.rules"

PURGE=0

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

case "${1:-}" in
  --purge) PURGE=1 ;;
  -h|--help)
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
    exit 0 ;;
  '') ;;
  *) die "unknown option: $1 (try --help)" ;;
esac

[ "$(id -u)" -eq 0 ] || die "this uninstaller needs root — run: sudo ./uninstall.sh"

log "Stopping and disabling the service"
systemctl stop "${SERVICE_NAME}.service" 2>/dev/null || true
systemctl disable "${SERVICE_NAME}.service" 2>/dev/null || true
rm -f "$UNIT_DST"
systemctl daemon-reload
ok "service removed"

if [ "$PURGE" -eq 1 ]; then
  log "Purging data, config and udev rule"
  rm -rf "$DB_DIR" "$ENV_DIR"
  rm -f "$UDEV_DST"
  udevadm control --reload 2>/dev/null || true
  ok "removed ${DB_DIR}, ${ENV_DIR} and the udev rule"
else
  log "Kept your data and config:"
  printf '    %s   (database)\n' "$DB_DIR"
  printf '    %s   (config)\n' "$ENV_DIR"
  printf '    %s   (udev rule)\n' "$UDEV_DST"
  printf '  Re-run with --purge to delete these too.\n'
fi

log "Done."
