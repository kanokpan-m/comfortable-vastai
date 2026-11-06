#!/bin/bash
# Record which commit of COMFORTABLE_REPO@COMFORTABLE_REF is installed (used by in-place updates).
COMFORTABLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="${COMFORTABLE_REPO:-${XTRA_REPO:-kanokpan-m/comfortable-vastai}}"
ref="${COMFORTABLE_REF:-${XTRA_REF:-main}}"
sha="$(curl -fsS --max-time 15 -H 'Accept: application/vnd.github.sha' \
  "https://api.github.com/repos/${repo}/commits/${ref}" 2>/dev/null || true)"
printf '{"sha": "%s", "ref": "%s", "repo": "%s", "installed_at": %s}\n' \
  "${sha}" "${ref}" "${repo}" "$(date +%s)" > "$COMFORTABLE_DIR/VERSION"
