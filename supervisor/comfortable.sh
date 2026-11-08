#!/bin/bash
# Supervisor launcher for the Comfortable dashboard (see comfortable.conf).
COMFORTABLE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
utils=/opt/supervisor-scripts/utils
[[ -f "${utils}/environment.sh" ]] && . "${utils}/environment.sh"
[[ -f /workspace/.comfortable.env ]] && . /workspace/.comfortable.env
if [[ -x /venv/main/bin/python ]]; then PY=/venv/main/bin/python
elif [[ -x /opt/conda/bin/python ]]; then PY=/opt/conda/bin/python
else PY="$(command -v python3)"
fi
# Free the port if a copy launched outside supervisord still holds it.
fuser -k 17890/tcp >/dev/null 2>&1 || true
exec > >(tee -a /var/log/comfortable.log) 2>&1
exec "$PY" -u "$COMFORTABLE_DIR/dashboard/server.py"
