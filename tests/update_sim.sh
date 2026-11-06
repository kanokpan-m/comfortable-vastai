#!/bin/bash
# Simulates the on-instance in-place update, including the move of an instance set
# up before the Comfy-Xtra -> Comfortable rename (/opt/comfy-xtra, program
# "comfy-xtra") to /opt/comfortable and program "comfortable".
#
# It writes to /opt, /workspace, /etc/supervisor and /usr/local/bin, so it runs as
# root and only on a throwaway machine (CI, or a sandbox with the override flag):
#   sudo -E bash tests/update_sim.sh                              # with CI=true
#   sudo bash tests/update_sim.sh --i-understand-this-writes-to-/opt
# Network is faked: codeload.github.com serves tarballs of this checkout (ref "old"
# = commit 0b37f67, the last pre-rename version; any other ref = the working tree,
# uncommitted edits included), api.github.com returns a fixed sha, supervisorctl
# only logs. Everything it creates is removed on exit.
set -uo pipefail

OLD_COMMIT=0b37f67
FAKE_SHA=0123456789abcdef0123456789abcdef01234567
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Root reading a checkout owned by the CI user: tell git that is fine.
repo_git(){ git -c safe.directory="$REPO_ROOT" -C "$REPO_ROOT" "$@"; }

if [[ "${CI:-}" != true && "${1:-}" != "--i-understand-this-writes-to-/opt" ]]; then
  echo "Refusing to run: this writes to /opt, /workspace, /etc/supervisor and /usr/local/bin." >&2
  echo "Run it in CI (CI=true) or pass --i-understand-this-writes-to-/opt on a throwaway machine." >&2
  exit 2
fi
[[ $EUID -eq 0 ]] || { echo "Must run as root (sudo -E bash $0)." >&2; exit 2; }
for p in /opt/comfortable /opt/comfy-xtra /opt/comfortable.old /opt/comfy-xtra.old /workspace \
         /etc/supervisor/conf.d/comfortable.conf /etc/supervisor/conf.d/comfy-xtra.conf; do
  if [[ -e "$p" || -L "$p" ]]; then
    echo "Refusing to run: $p exists (looks like a real install; never clobbering it)." >&2
    exit 2
  fi
done
repo_git cat-file -e "${OLD_COMMIT}^{commit}" 2>/dev/null || {
  echo "Commit $OLD_COMMIT is not in this clone (CI: actions/checkout needs fetch-depth: 0)." >&2; exit 2; }

# Keep the scripts under test from seeing settings of the machine running the sim.
for v in $(compgen -e | grep -E '^(COMFORTABLE|XTRA)_' || true); do unset "$v"; done
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PYTHONDONTWRITEBYTECODE=1

SIM="$(mktemp -d /tmp/comfortable-update-sim.XXXXXX)"
SCTL_LOG="$SIM/supervisorctl.log"
REAL_CURL="$(command -v curl)"
had_etc_supervisor=0; [[ -d /etc/supervisor ]] && had_etc_supervisor=1
had_conf_d=0; [[ -d /etc/supervisor/conf.d ]] && had_conf_d=1
preexisting_logs="$(ls -d /var/log/comfortable* /var/log/comfy-xtra* 2>/dev/null || true)"
backed_up=()

cleanup() {
  rm -rf /opt/comfortable /opt/comfy-xtra /opt/comfortable.old /opt/comfy-xtra.old \
         /opt/.comfortable.* /opt/.comfy-xtra.* /workspace /tmp/.comfortable-migrate
  rm -f /etc/supervisor/conf.d/comfortable.conf /etc/supervisor/conf.d/comfy-xtra.conf
  (( had_conf_d )) || rmdir /etc/supervisor/conf.d 2>/dev/null
  (( had_etc_supervisor )) || rmdir /etc/supervisor 2>/dev/null
  rm -f /usr/local/bin/curl /usr/local/bin/supervisorctl
  local b; for b in "${backed_up[@]}"; do cp -p "$SIM/backup/$b" "/usr/local/bin/$b"; done
  local f; for f in /var/log/comfortable* /var/log/comfy-xtra*; do
    [[ -e "$f" ]] || continue
    grep -qxF "$f" <<<"$preexisting_logs" || rm -rf "$f"
  done
  rm -rf "$SIM"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

fails=0
pass(){ echo "PASS: $*"; }
fail(){ echo "FAIL: $*"; fails=$((fails+1)); }
check(){ local desc="$1"; shift; if "$@"; then pass "$desc"; else fail "$desc"; fi; }
show_logs(){
  echo "----- /var/log/comfy-xtra-update.log, /var/log/comfortable-update.log"
  cat /var/log/comfy-xtra-update.log /var/log/comfortable-update.log 2>/dev/null | tail -n 40
  echo "----- supervisorctl calls"; cat "$SCTL_LOG" 2>/dev/null; echo "-----"
}
# True when supervisorctl was called with exactly these arguments since the log was cleared.
sctl_saw(){ grep -qxF "supervisorctl $*" "$SCTL_LOG" 2>/dev/null; }
# conf.d contents logged at the first call with these arguments.
sctl_conf_at(){ awk -v c="supervisorctl $*" '$0==c{getline; sub(/^  conf.d: /,""); print; exit}' "$SCTL_LOG"; }
conf_d(){ (cd /etc/supervisor/conf.d && ls -1 | tr '\n' ' ' | sed 's/ $//'); }
link_is(){ [[ "$(readlink /workspace/ComfyUI/custom_nodes/ComfyUI-Comfortable)" == "$1" ]]; }
version_has(){ python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get(sys.argv[2])==sys.argv[3] else 1)' "$@" 2>/dev/null; }

# ---- 1. Fakes ---------------------------------------------------------------
mkdir -p "$SIM/backup" "$SIM/old" "$SIM/new"
repo_git archive --format=tar.gz --prefix=x/ "$OLD_COMMIT" > "$SIM/old.tar.gz"
# The working tree (tracked + untracked, minus ignored), so local edits are tested too.
(cd "$REPO_ROOT" && repo_git ls-files -z --cached --others --exclude-standard \
   | while IFS= read -r -d '' f; do [[ -e "$f" || -L "$f" ]] && printf '%s\0' "$f"; done \
   | tar --null -T - --transform 's,^,x/,' -czf "$SIM/new.tar.gz")

for b in curl supervisorctl; do
  if [[ -e /usr/local/bin/$b ]]; then cp -p "/usr/local/bin/$b" "$SIM/backup/$b"; backed_up+=("$b"); fi
done
[[ "$REAL_CURL" == /usr/local/bin/curl ]] && REAL_CURL="$SIM/backup/curl"

cat > /usr/local/bin/curl <<EOF
#!/bin/bash
# Fake curl installed by tests/update_sim.sh.
for a in "\$@"; do
  case "\$a" in
    https://codeload.github.com/*/tar.gz/old) exec cat "$SIM/old.tar.gz" ;;
    https://codeload.github.com/*/tar.gz/*) exec cat "$SIM/new.tar.gz" ;;
    https://api.github.com/*) echo -n "$FAKE_SHA"; exit 0 ;;
  esac
done
exec "$REAL_CURL" "\$@"
EOF
cat > /usr/local/bin/supervisorctl <<EOF
#!/bin/bash
# Fake supervisorctl installed by tests/update_sim.sh.
{ echo "supervisorctl \$*"; echo "  conf.d: \$(cd /etc/supervisor/conf.d 2>/dev/null && ls -1 | tr '\n' ' ' | sed 's/ \$//')"; } >> "$SCTL_LOG"
exit 0
EOF
chmod 755 /usr/local/bin/curl /usr/local/bin/supervisorctl
check "fake curl is first in PATH" [ "$(command -v curl)" = /usr/local/bin/curl ]
check "fake supervisorctl is first in PATH" [ "$(command -v supervisorctl)" = /usr/local/bin/supervisorctl ]

# ---- 2. Legacy instance (before the rename) ----------------------------------
mkdir -p /opt/comfy-xtra /etc/supervisor/conf.d /workspace/ComfyUI/custom_nodes
tar -xzf "$SIM/old.tar.gz" -C /opt/comfy-xtra --strip-components=1
chmod 755 /opt/comfy-xtra /opt/comfy-xtra/supervisor/comfy-xtra.sh
install -m 644 /opt/comfy-xtra/supervisor/comfy-xtra.conf /etc/supervisor/conf.d/comfy-xtra.conf
ln -sfn /opt/comfy-xtra/comfyui_ext /workspace/ComfyUI/custom_nodes/ComfyUI-Comfortable
echo "# written before the rename" > /workspace/.comfy_xtra.env
check "legacy layout set up (old update.sh has no /opt/comfortable)" \
  bash -c '! grep -q /opt/comfortable /opt/comfy-xtra/lib/update.sh'

# ---- 3. Old updater, as the pre-rename dashboard runs it ---------------------
echo "== step 3: pre-rename updater (/opt/comfy-xtra/lib/update.sh) installs the new code"
: > "$SCTL_LOG"
XTRA_REPO=x/y XTRA_REF=main bash /opt/comfy-xtra/lib/update.sh; rc=$?
check "old updater exits 0 (rc=$rc)" [ "$rc" -eq 0 ]
check "/opt/comfy-xtra holds the new code (lib/update.sh knows /opt/comfortable)" \
  grep -q 'COMFORTABLE_DIR=/opt/comfortable' /opt/comfy-xtra/lib/update.sh
check "/opt/comfy-xtra/supervisor/comfy-xtra.sh exists and is executable" [ -x /opt/comfy-xtra/supervisor/comfy-xtra.sh ]
check "/opt/comfy-xtra/supervisor/comfortable.sh exists (the shim execs it)" [ -f /opt/comfy-xtra/supervisor/comfortable.sh ]
check "conf.d/comfy-xtra.conf runs /opt/comfy-xtra/supervisor/comfy-xtra.sh" \
  grep -qx 'command=/opt/comfy-xtra/supervisor/comfy-xtra.sh' /etc/supervisor/conf.d/comfy-xtra.conf
check "supervisorctl was told 'restart comfy-xtra'" sctl_saw restart comfy-xtra
check "VERSION records x/y@main and the fetched sha" \
  bash -c "$(declare -f version_has); version_has /opt/comfy-xtra/VERSION repo x/y && version_has /opt/comfy-xtra/VERSION sha $FAKE_SHA"
check "extension still linked to /opt/comfy-xtra/comfyui_ext" link_is /opt/comfy-xtra/comfyui_ext
check "no temp dirs left in /opt" bash -c '! compgen -G "/opt/.comfy*" >/dev/null && [ ! -e /opt/comfy-xtra.old ]'
(( fails )) && show_logs

# ---- 4. Migration the shim starts ---------------------------------------------
echo "== step 4: the comfy-xtra shim's one-time migration to /opt/comfortable"
shim=/opt/comfy-xtra/supervisor/comfy-xtra.sh
check "shim syntax is valid" bash -n "$shim"
check "shim runs lib/update.sh when comfortable.conf is not installed" \
  bash -c "grep -q '/etc/supervisor/conf.d/comfortable.conf' '$shim' && grep -q 'lib/update.sh' '$shim'"
check "shim then starts the dashboard via comfortable.sh" grep -q 'supervisor/comfortable.sh' "$shim"
before=$fails
: > "$SCTL_LOG"
XTRA_REPO=x/y XTRA_REF=main bash /opt/comfy-xtra/lib/update.sh; rc=$?
check "migration exits 0 (rc=$rc)" [ "$rc" -eq 0 ]
check "/opt/comfortable/VERSION exists" [ -f /opt/comfortable/VERSION ]
check "VERSION records x/y (from XTRA_REPO)" \
  bash -c "$(declare -f version_has); version_has /opt/comfortable/VERSION repo x/y"
check "/opt/comfy-xtra is gone" [ ! -e /opt/comfy-xtra ]
check "conf.d holds only comfortable.conf (got: $(conf_d))" [ "$(conf_d)" = comfortable.conf ]
check "comfortable.conf runs an executable /opt/comfortable/supervisor/comfortable.sh" \
  bash -c 'grep -qx "command=/opt/comfortable/supervisor/comfortable.sh" /etc/supervisor/conf.d/comfortable.conf && [ -x /opt/comfortable/supervisor/comfortable.sh ]'
check "extension symlink -> /opt/comfortable/comfyui_ext" link_is /opt/comfortable/comfyui_ext
check "supervisorctl saw 'update'" sctl_saw update
check "at 'update' only comfortable.conf was in conf.d (got: $(sctl_conf_at update))" [ "$(sctl_conf_at update)" = comfortable.conf ]
check "supervisorctl saw 'restart comfortable'" sctl_saw restart comfortable
check "no temp or .old dirs left in /opt" bash -c '! compgen -G "/opt/.comfy*" >/dev/null && [ ! -e /opt/comfortable.old ]'
(( fails > before )) && show_logs

# ---- 5. Normal update on the migrated instance -------------------------------
echo "== step 5: a normal update from /opt/comfortable/lib/update.sh"
before=$fails
: > "$SCTL_LOG"
COMFORTABLE_REPO=x/y COMFORTABLE_REF=main bash /opt/comfortable/lib/update.sh; rc=$?
check "update exits 0 (rc=$rc)" [ "$rc" -eq 0 ]
check "/opt/comfortable/VERSION exists" [ -f /opt/comfortable/VERSION ]
check "/opt/comfy-xtra still absent" [ ! -e /opt/comfy-xtra ]
check "conf.d still holds only comfortable.conf (got: $(conf_d))" [ "$(conf_d)" = comfortable.conf ]
check "extension symlink still -> /opt/comfortable/comfyui_ext" link_is /opt/comfortable/comfyui_ext
check "supervisorctl saw 'restart comfortable'" sctl_saw restart comfortable
check "supervisorctl was not asked about comfy-xtra" bash -c "! grep -q comfy-xtra '$SCTL_LOG'"
check "no temp or .old dirs left in /opt" bash -c '! compgen -G "/opt/.comfy*" >/dev/null && [ ! -e /opt/comfortable.old ]'
(( fails > before )) && show_logs

# ---- 6. Dashboard data migration (.comfy_xtra -> .comfortable) ----------------
echo "== step 6: dashboard renames the pre-rename data files"
ws="$SIM/ws"
mkdir -p "$ws/.comfy_xtra"
echo db > "$ws/.comfy_xtra/xtra.db"
echo env > "$ws/.comfy_xtra.env"
if out="$(COMFORTABLE_WORKSPACE="$ws" python3 - "$REPO_ROOT/dashboard" 2>&1 <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from comfortable import config
config.ensure_dirs()
ws = config.WORKSPACE
problems = []
for p in (ws / ".comfortable" / "comfortable.db", ws / ".comfortable.env"):
    if not p.is_file():
        problems.append(f"missing {p}")
for p in (ws / ".comfy_xtra", ws / ".comfy_xtra.env", ws / ".comfortable" / "xtra.db"):
    if p.exists():
        problems.append(f"still present {p}")
if (ws / ".comfortable" / "comfortable.db").read_text() != "db\n":
    problems.append("comfortable.db content changed")
print("; ".join(problems) or "ok")
sys.exit(1 if problems else 0)
PY
)"; then pass "data files renamed (.comfortable/comfortable.db, .comfortable.env)"
else fail "data migration: $out"
fi

echo
if (( fails )); then echo "update simulation: $fails check(s) FAILED"; exit 1; fi
echo "update simulation: all checks passed"
