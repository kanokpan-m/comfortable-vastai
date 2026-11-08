#!/bin/bash
# In-place update, started by the dashboard (Settings → Update). Fetches
# COMFORTABLE_REPO@COMFORTABLE_REF, swaps it into /opt/comfortable, reinstalls the
# ComfyUI extension and restarts only the dashboard. ComfyUI keeps running; if the
# extension's Python changed, the dashboard asks you to restart ComfyUI.
set -Eeuo pipefail
COMFORTABLE_REPO="${COMFORTABLE_REPO:-kanokpan-m/comfortable-vastai}"
COMFORTABLE_REF="${COMFORTABLE_REF:-main}"
COMFORTABLE_DIR=/opt/comfortable
LOG=/var/log/comfortable-update.log
export COMFORTABLE_REPO COMFORTABLE_REF COMFORTABLE_DIR
exec >>"$LOG" 2>&1
echo "$(date -Is) updating to ${COMFORTABLE_REPO}@${COMFORTABLE_REF}"

tmp="$(mktemp -d /opt/.comfortable.XXXXXX)"
curl -fsSL --retry 5 --retry-delay 3 --connect-timeout 15 \
  "https://codeload.github.com/${COMFORTABLE_REPO}/tar.gz/${COMFORTABLE_REF}" | tar -xz -C "$tmp" --strip-components=1
[[ -f "$tmp/lib/main.sh" ]] || { echo "download incomplete"; rm -rf "$tmp"; exit 1; }
chmod 755 "$tmp"

old_ext_hash="$(cat "$COMFORTABLE_DIR"/comfyui_ext/*.py 2>/dev/null | sha256sum | cut -c1-16)"
restart_flag="$(cat "$COMFORTABLE_DIR/.restart_comfy" 2>/dev/null || true)"
rm -rf "${COMFORTABLE_DIR}.old"
[[ -d "$COMFORTABLE_DIR" ]] && mv "$COMFORTABLE_DIR" "${COMFORTABLE_DIR}.old"
mv "$tmp" "$COMFORTABLE_DIR"
[[ -n "$restart_flag" ]] && echo "$restart_flag" > "$COMFORTABLE_DIR/.restart_comfy"
bash "$COMFORTABLE_DIR/lib/version.sh" || true

. "$COMFORTABLE_DIR/lib/common.sh"
. "$COMFORTABLE_DIR/lib/extension.sh"
new_ext_hash="$(cat "$COMFORTABLE_DIR"/comfyui_ext/*.py 2>/dev/null | sha256sum | cut -c1-16)"
if [[ "$old_ext_hash" != "$new_ext_hash" && ! -f "$COMFORTABLE_DIR/.restart_comfy" ]]; then
  echo "comfyui extension python changed; ComfyUI restart needed" > "$COMFORTABLE_DIR/.restart_comfy"
fi
chmod 755 "$COMFORTABLE_DIR/supervisor/comfortable.sh"
install -m 644 "$COMFORTABLE_DIR/supervisor/comfortable.conf" /etc/supervisor/conf.d/comfortable.conf
supervisorctl reread >/dev/null || true
supervisorctl update >/dev/null || true
supervisorctl restart comfortable
rm -rf "${COMFORTABLE_DIR}.old"
echo "$(date -Is) update done"
