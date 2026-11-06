#!/bin/bash
# Record which commit of XTRA_REPO@XTRA_REF is installed (used by in-place updates).
XTRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sha="$(curl -fsS --max-time 15 -H 'Accept: application/vnd.github.sha' \
  "https://api.github.com/repos/${XTRA_REPO:-kanokpan-m/comfortable-vastai}/commits/${XTRA_REF:-main}" 2>/dev/null || true)"
printf '{"sha": "%s", "ref": "%s", "repo": "%s", "installed_at": %s}\n' \
  "${sha}" "${XTRA_REF:-main}" "${XTRA_REPO:-kanokpan-m/comfortable-vastai}" "$(date +%s)" > "$XTRA_DIR/VERSION"
