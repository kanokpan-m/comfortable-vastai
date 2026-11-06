#!/bin/bash
# Supervisor launcher for the Comfortable dashboard (see comfortable.conf).
COMFORTABLE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
utils=/opt/supervisor-scripts/utils
[[ -f "${utils}/environment.sh" ]] && . "${utils}/environment.sh"
# .comfy_xtra.env: written before the rename (the dashboard renames it on start).
for ENV_FILE in /workspace/.comfortable.env /workspace/.comfy_xtra.env; do
  [[ -f "$ENV_FILE" ]] && { . "$ENV_FILE"; break; }
done
if [[ -x /venv/main/bin/python ]]; then PY=/venv/main/bin/python
elif [[ -x /opt/conda/bin/python ]]; then PY=/opt/conda/bin/python
else PY="$(command -v python3)"
fi
# Free the port if a copy launched outside supervisord still holds it.
fuser -k 17890/tcp >/dev/null 2>&1 || true
exec > >(tee -a /var/log/comfortable.log) 2>&1
exec "$PY" -u "$COMFORTABLE_DIR/dashboard/server.py"
