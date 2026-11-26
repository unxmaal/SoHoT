#!/usr/bin/env bash
# The soh and lh commands on PATH: ~/.local/bin shims that exec the live release's own venv through the deploy link, so a switch or rollback needs no rewrite. #2126.
#   path-shim.sh install   write the shims; an existing file without our marker is left alone and reported (rc 1)
#   path-shim.sh check     each shim runs `--help`: soh failing is rc 1, lh failing a WARN
set -uo pipefail
LH_HOME="${LOCALHARNESS_HOME:-$HOME/localharness}"
BIN="${LH_SHIM_BIN:-$HOME/.local/bin}"
MARK="# localharness-path-shim: written by scripts/path-shim.sh"
NAMES="soh lh"

body() {
  printf '#!/bin/sh\n%s\n' "$MARK"
  printf 't=%s\n' "'$LH_HOME/deploy/.venv/bin/soh'"
  printf '[ -x "$t" ] || { echo "%s: $t is missing; run scripts/launchd.sh install" >&2; exit 127; }\n' "$1"
  printf 'exec "$t" "$@"\n'
}

# Ours only when it is a regular file carrying the marker; anything else (a uv tool symlink, a user's script) is foreign.
ours() { [ -f "$1" ] && [ ! -L "$1" ] && grep -qxF "$MARK" "$1" 2>/dev/null; }

install_one() {
  local name="$1" dest="$BIN/$1" want tmp
  want="$(body "$name")"
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    if ! ours "$dest"; then
      echo "REFUSED  $dest exists and is not ours (no '$MARK' line); left alone. Remove it, then re-run scripts/launchd.sh install." >&2
      return 1
    fi
    if [ "$(cat "$dest")" = "$want" ] && [ -x "$dest" ]; then echo "unchanged  $dest"; return 0; fi
  fi
  mkdir -p "$BIN" || return 1
  tmp="$dest.$$"
  printf '%s\n' "$want" > "$tmp" && chmod 755 "$tmp" && mv -f "$tmp" "$dest" || { rm -f "$tmp"; return 1; }
  echo "wrote  $dest -> $LH_HOME/deploy/.venv/bin/soh"
}

check_one() {
  local name="$1" out
  if out="$("$BIN/$name" --help 2>&1)"; then echo "PASS  $name --help from $BIN"; return 0; fi
  printf 'FAIL  %s --help from %s exited non-zero: %s\n' "$name" "$BIN" "$(printf '%s' "$out" | tail -n 1)"
  return 1
}

case "${1:-}" in
  install)
    rc=0
    for n in $NAMES; do install_one "$n" || rc=1; done
    exit "$rc" ;;
  check)
    rc=0
    check_one soh || rc=1
    check_one lh || echo "WARN  lh is not a working command; soh is the one deploys depend on"
    first="$(command -v soh)"
    [ "$first" = "$BIN/soh" ] || echo "WARN  soh on PATH resolves to ${first:-nothing}, not $BIN/soh"
    exit "$rc" ;;
  *) echo "usage: $0 install|check" >&2; exit 2 ;;
esac
