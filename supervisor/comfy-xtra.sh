#!/bin/bash
# Only for instances set up before the Comfy-Xtra → Comfortable rename. Their
# updater installs this repo into /opt/comfy-xtra and restarts the "comfy-xtra"
# program, which runs this file. Start the dashboard as usual, and once, run the
# new updater in its own session: it moves the instance to /opt/comfortable and
# the "comfortable" program (see lib/update.sh), then removes this old copy.
# Delete this file and comfy-xtra.conf once no such instances are left.
dir="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -e /etc/supervisor/conf.d/comfortable.conf ]] && mkdir /tmp/.comfortable-migrate 2>/dev/null; then
  setsid bash -c 'sleep 30; exec bash "$0"' "$dir/lib/update.sh" </dev/null >/dev/null 2>&1 &
fi
exec "$dir/supervisor/comfortable.sh"
