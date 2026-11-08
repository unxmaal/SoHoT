#!/usr/bin/env bash
# launchd units for the three services, so the machine comes back up serving
# after a reboot or a crash without anyone remembering three script names.
#
#   ./scripts/launchd.sh generate [DIR]   write the plists (default: $LH_HOME/launchd)
#   ./scripts/launchd.sh install          write them to ~/Library/LaunchAgents and load
#   ./scripts/launchd.sh uninstall        unload and remove them
#   ./scripts/launchd.sh status           what launchd thinks is running
#
# Generated from one loop rather than three hand-written files. The last time
# this repo had three near-identical things the copies disagreed about which
# port they used, and that took a while to find.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
# What this run parsed; deploy can rewrite the file under it. #821.
SELF_SUM="$(cksum < "$0")"
AGENTS="$HOME/Library/LaunchAgents"
# One place for everything this project produces; see harness/paths.py.
LH_HOME="${LOCALHARNESS_HOME:-$HOME/localharness}"
LH_LOGS="$LH_HOME/logs"
PREFIX="com.unxmaal.localharness"
# What a manual install read from the owner's shell, so a launchd reinstall renders the same units. #1518.
INSTALL_ENV="$LH_HOME/install.env"
RECORDED="HF_HOME HF_MIN_FREE_GB PATH LH_WATCHDOG_ACT LH_WATCHDOG_FILE LH_DAY_FETCH LH_REVIEW_FILE DISCOVER_HOURS AUDIT_HOURS WATCHDOG_EVERY_MIN ENERGY_EVERY_MIN DELEGATIONS_EVERY_MIN DEPLOY_EVERY_MIN LEDGER_HOURS MORNING_HOURS MORNING_MINUTE CLAUDE_NEWS_WEEKDAY CLAUDE_NEWS_HOUR CANARY_WEEKDAY CANARY_HOUR REVIEW_WEEKDAY REVIEW_HOUR SWEEP_CHECK_HOURS FETCH_HOURS"

# One variable's recorded value; rc 1 when the record does not hold it.
_recorded() {
  local line
  [ -f "$INSTALL_ENV" ] || return 1
  line="$(grep -m1 "^$1=" "$INSTALL_ENV")" || return 1
  printf '%s' "${line#*=}"
}

# reinstall takes the record and nothing from its caller; install takes its caller, else the last record.
_install_env() {
  local var val
  case "$1" in
    reinstall)
      if [ ! -f "$INSTALL_ENV" ]; then
        echo "FATAL: no recorded install environment at $INSTALL_ENV, so reinstall would render units from" >&2
        echo "       launchd's empty environment. Run ./scripts/launchd.sh install once from the owner's shell." >&2
        exit 1
      fi
      for var in $RECORDED; do
        if val="$(_recorded "$var")" && [ -n "$val" ]; then
          export "$var=$val"
        elif [ "$var" = PATH ]; then
          export PATH="/usr/bin:/bin:/usr/sbin:/sbin"
        else
          unset "$var"
        fi
      done
      unset HF_ROOT
      if [ -z "${HF_HOME:-}" ] || ! ls "$HF_HOME" >/dev/null 2>&1; then
        echo "FATAL: the weights location recorded in $INSTALL_ENV (HF_HOME=${HF_HOME:-nothing}) cannot be read." >&2
        echo "       reinstall will not fall back to another location; attach the volume, or run install again." >&2
        exit 1
      fi ;;
    install)
      for var in $RECORDED; do
        [ -n "${!var:-}" ] && continue
        [ "$var" = HF_HOME ] && [ -n "${HF_ROOT:-}" ] && continue
        val="$(_recorded "$var")" || val=""
        if [ -z "$val" ] && [ -f "$LH_HOME/$var" ]; then val="$(tr -d '[:space:]' < "$LH_HOME/$var")"; fi
        if [ -n "$val" ]; then export "$var=$val"; fi
      done
      for var in $RECORDED; do
        if [ -n "${!var:-}" ]; then GIVEN="$GIVEN $var"; fi
      done ;;
    # The probe asks about the weights reinstall will render, once an install recorded them. #1516.
    probe) if [ -f "$INSTALL_ENV" ]; then _install_env reinstall; fi ;;
  esac
  return 0
}
# What install was given, before the defaults below fill the rest: only these are recorded.
GIVEN=""
_install_env "${1:-}"

# Write the record from what this install resolved; HF_HOME is env.sh's answer, as the units get it.
_record_install_env() {
  local var val tmp="$INSTALL_ENV.$$"
  mkdir -p "$LH_HOME"
  {
    echo "# Written by scripts/launchd.sh install; reinstall and the deploy switch read it (#1518)."
    printf 'HF_HOME=%s\n' "$(_hf_root)"
    for var in $GIVEN; do
      [ "$var" = HF_HOME ] && continue
      val="${!var:-}"
      if [ -n "$val" ]; then printf '%s=%s\n' "$var" "$val"; fi
    done
  } > "$tmp"
  mv "$tmp" "$INSTALL_ENV"
  echo "recorded the install environment in $INSTALL_ENV"
}
# The agents run DEPLOY, a worktree that only ever holds origin/main, so branch
# work in the checkout this script lives in never becomes production. #290.
SRC="${LH_REPO:-$REPO}"
DEPLOY="${LH_DEPLOY:-$LH_HOME/deploy}"
# `discover` is not a server. It is the scheduled sweep, and it is in this
# list because the thing that must survive a reboot is the SCHEDULE. #261.
SERVICES="interactive gateway mlx eval tts mcp discover worker audit ds4 watchdog energy ledger morning claude-news otel canary sweep-check fetch delegations review deploy"

#: Services that RUN AND EXIT rather than serve, at fixed local hours. KeepAlive
#: would rerun a finished sweep at once; StartInterval counts from load, so a day
#: of installs never lets it fire (#625). harness/heartbeat reads the installed hours (#705).
declare -a PERIODIC=(discover audit watchdog energy ledger morning claude-news canary sweep-check fetch delegations review deploy)
DISCOVER_HOURS="${DISCOVER_HOURS:-21}"
AUDIT_HOURS="${AUDIT_HOURS:-3}"                   # nightly, #492
# The watchdog watches this machine's own jobs, so every role runs it. #814.
WATCHDOG_EVERY_MIN="${WATCHDOG_EVERY_MIN:-5}"
# This machine's power through macmon, one reading a minute; every role samples its own. #826.
ENERGY_EVERY_MIN="${ENERGY_EVERY_MIN:-1}"
# Delegation outcomes inferred from the callers' transcripts, or expired to unknown, every N minutes. #1158.
DELEGATIONS_EVERY_MIN="${DELEGATIONS_EVERY_MIN:-60}"
# A green origin/main commit becomes a deploy job within N minutes; the job itself waits for the contention gate. #1506, #1509.
DEPLOY_EVERY_MIN="${DEPLOY_EVERY_MIN:-10}"
# How long install waits for a deferred periodic run to end before leaving it on the old unit. #1058.
DEFER_WAIT_S="${LH_DEFER_WAIT_S:-120}"
# The day's ledger row, written late each evening and rewritten the next. #826.
LEDGER_HOURS="${LEDGER_HOURS:-23}"
# The morning report, before the owner's day starts; it notifies only when something needs a person. #867.
MORNING_HOURS="${MORNING_HOURS:-6}"
MORNING_MINUTE="${MORNING_MINUTE:-30}"
# Claude Code changelog digest, weekly: launchd Weekday 1 is Monday. #866.
CLAUDE_NEWS_WEEKDAY="${CLAUDE_NEWS_WEEKDAY:-1}"
CLAUDE_NEWS_HOUR="${CLAUDE_NEWS_HOUR:-9}"
# The planted-candidate canary, weekly after the night's sweep; it waits for a sweep still running. #919.
CANARY_WEEKDAY="${CANARY_WEEKDAY:-6}"
CANARY_HOUR="${CANARY_HOUR:-4}"
# The adversarial review, weekly on Sunday after the night's sweep; plan tokens, no GPU; it waits for a sweep still running. #1149.
REVIEW_WEEKDAY="${REVIEW_WEEKDAY:-0}"
REVIEW_HOUR="${REVIEW_HOUR:-4}"
# Tonight's sweep checked from launchd state and its heartbeat, an hour after it starts and hourly to 06:00. #1062.
SWEEP_CHECK_HOURS="${SWEEP_CHECK_HOURS:-22 23 0 1 2 3 4 5 6}"
# Downloads for the next night's screen, by day; it starts nothing 20:00-08:00 or beside a sweep, and is off until LH_DAY_FETCH=1. #1084.
FETCH_HOURS="${FETCH_HOURS:-8 11 14 17}"
# Periodic jobs that read or write the shared store: only the scheduler runs them. #703.
declare -a SCHEDULER_ONLY=(discover audit ledger morning claude-news canary sweep-check fetch delegations review)
# Machines sharing one store run the periodic jobs on one of them: scheduler, or node for the rest. #703.
# An interactive node runs only the interactive server, for lanes the scheduler's gateway sends it first. #1562.
# A role given once is kept in $LH_HOME/role, so a later plain `make install` keeps it.
ROLE_FILE="$LH_HOME/role"
ROLE_GIVEN="${LH_ROLE:-}"
if [ -z "$ROLE_GIVEN" ] && [ -f "$ROLE_FILE" ]; then
  LH_ROLE="$(tr -d '[:space:]' < "$ROLE_FILE")"
fi
LH_ROLE="${LH_ROLE:-scheduler}"
case "$LH_ROLE" in
  scheduler|node|interactive) ;;
  *) echo "LH_ROLE must be scheduler, node or interactive, not '$LH_ROLE' (from ${ROLE_GIVEN:+the environment}${ROLE_GIVEN:-$ROLE_FILE})" >&2; exit 2 ;;
esac
if [ -n "$ROLE_GIVEN" ]; then
  mkdir -p "$LH_HOME"
  printf '%s\n' "$LH_ROLE" > "$ROLE_FILE"
fi

# The services this machine runs: a node leaves the periodic ones to the scheduler.
units() {
  local service p skip
  for service in $SERVICES; do
    skip=""
    if [ "$LH_ROLE" = node ]; then
      for p in "${SCHEDULER_ONLY[@]}"; do [ "$p" = "$service" ] && skip=1; done
    fi
    [ "$LH_ROLE" = interactive ] && [ "$service" != interactive ] && skip=1
    [ -z "$skip" ] && printf '%s\n' "$service"
  done
  return 0
}

# launchd starts jobs with PATH=/usr/bin:/bin:/usr/sbin:/sbin and NOTHING else.
# uv, ffmpeg, rsvg-convert and rec all live in /opt/homebrew/bin, so without
# this every service dies on "command not found" -- the same trap a GUI-spawned
# wezterm set for the voice scripts, and it is just as invisible here.
# $HOME/.local/bin is where uv puts `soh`, and serve-mcp.sh shells out to it for
# every tool call. Without it that unit loads, listens, and fails each call with
# "soh: command not found".
JOB_PATH="$HOME/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# AND PATH IS NOT THE ONLY THING launchd DROPS. env.sh resolves the weights
# cache from HF_ROOT, then an inherited HF_HOME, then ./hf_root in the checkout
# (RULE #222: a default naming one person's volume is not a default). A launchd
# job inherits neither variable, so it took the in-tree default, and mlx_lm's
# /v1/models raised
#
#   CacheNotFound: .../localharness/hf_root/hub
#
# The port stayed bound, the model list came back empty, and every generate
# request hung until the caller gave up. Four text lanes were unrunnable for
# hours and the only symptom anywhere else was models timing out, which reads
# as the model failing. #255.
#
# Resolved HERE rather than written into the plist by hand, so the value is
# this machine's own answer and a second machine gets its own.
_hf_env() {
  local pair
  while IFS= read -r pair; do
    printf '    <key>%s</key><string>%s</string>\n' "${pair%%=*}" "${pair#*=}"
  done < <(_hf_pairs)
}

# HF_ROOT and HF_HOME as the units get them, one NAME=value a line; the fit check runs under the same. #1616.
_hf_pairs() {
  local var val
  for var in HF_ROOT HF_HOME; do
    val="$(_hf_var "$var")"
    if [ -n "$val" ]; then printf '%s=%s\n' "$var" "$val"; fi
  done
  return 0
}

# Run a command with the unit's weights root, not the caller's: the fit check must read the server's gguf dir. #1616.
_as_unit() {
  local pair
  local -a pairs=()
  while IFS= read -r pair; do pairs+=("$pair"); done < <(_hf_pairs)
  env -u HF_ROOT -u HF_HOME -u LLAMACPP_MODELS_DIR ${pairs[@]+"${pairs[@]}"} "$@"
}

# uv for install's own calls: the caller's PATH, then the units' (an ssh shell has no Homebrew on PATH). #1616.
_find_uv() {
  (PATH="$PATH:$JOB_PATH"; command -v uv) && return 0
  echo "FATAL: uv not found on PATH ($PATH) or the units' PATH ($JOB_PATH); no unit was touched." >&2
  return 1
}

# One variable from env.sh run in the checkout; empty when env.sh refuses. #705.
_hf_var() {
  (cd "$REPO" && . scripts/env.sh >/dev/null 2>&1 && printf '%s' "${!1:-}")
}

# The weights root the agents get, exactly as _hf_env writes it; empty when env.sh refuses. #705.
_hf_root() {
  _hf_var HF_HOME
}

# The watchdog acts and files issues, the day fetch runs and the review files, only once the owner sets these; a value given once is kept. #814, #1084, #1149.
# An interactive node's server listens on the LAN with a key and pins only its lanes. #1562.
_watchdog_env() {
  local var val vars
  case "$1" in
    watchdog) vars="LH_WATCHDOG_ACT LH_WATCHDOG_FILE" ;;
    interactive) vars="LLAMACPP_HOST LLAMACPP_API_KEY_FILE INTERACTIVE_LANES LLAMACPP_BIN" ;;
    fetch) vars="LH_DAY_FETCH" ;;
    review) vars="LH_REVIEW_FILE" ;;
    *) return 0 ;;
  esac
  for var in $vars; do
    val="${!var:-}"
    if [ -n "$val" ]; then
      mkdir -p "$LH_HOME"
      printf '%s\n' "$val" > "$LH_HOME/$var"
    elif [ -f "$LH_HOME/$var" ]; then
      val="$(tr -d '[:space:]' < "$LH_HOME/$var")"
    fi
    if [ -n "$val" ]; then
      printf '    <key>%s</key><string>%s</string>\n' "$var" "$val"
    fi
  done
  return 0
}

usage() {
  echo "usage: $0 {deploy|deploy-path|generate [DIR]|install|reinstall|uninstall|status|probe}" >&2
  exit 2
}

# A server is kept alive; a periodic job is run on an interval and allowed to
# finish. Getting this backwards means either a sweep that never repeats or one
# that never stops.
_schedule() {
  local service="$1" p
  for p in "${PERIODIC[@]}"; do
    if [ "$p" = "$service" ] && { [ "$service" = watchdog ] || [ "$service" = energy ] || [ "$service" = delegations ] || [ "$service" = deploy ]; }; then
      # Every N minutes of every hour: a calendar, since an interval restarts at each load (#625).
      local m every="$WATCHDOG_EVERY_MIN"
      [ "$service" = energy ] && every="$ENERGY_EVERY_MIN"
      [ "$service" = delegations ] && every="$DELEGATIONS_EVERY_MIN"
      [ "$service" = deploy ] && every="$DEPLOY_EVERY_MIN"
      printf '  <key>StartCalendarInterval</key>\n  <array>\n'
      for m in $(seq 0 "$every" 59); do
        printf '    <dict><key>Minute</key><integer>%s</integer></dict>\n' "$m"
      done
      printf '  </array>\n'
      return
    fi
    if [ "$p" = "$service" ] && { [ "$service" = claude-news ] || [ "$service" = canary ] || [ "$service" = review ]; }; then
      local day="$CLAUDE_NEWS_WEEKDAY" hour="$CLAUDE_NEWS_HOUR"
      [ "$service" = canary ] && day="$CANARY_WEEKDAY" && hour="$CANARY_HOUR"
      [ "$service" = review ] && day="$REVIEW_WEEKDAY" && hour="$REVIEW_HOUR"
      printf '  <key>StartCalendarInterval</key>\n  <array>\n'
      printf '    <dict><key>Weekday</key><integer>%s</integer><key>Hour</key><integer>%s</integer><key>Minute</key><integer>0</integer></dict>\n' \
        "$day" "$hour"
      printf '  </array>\n'
      return
    fi
    if [ "$p" = "$service" ]; then
      # No RunAtLoad: an install is not a schedule tick (#328).
      local hours="$DISCOVER_HOURS" minute=0 h
      [ "$service" = audit ] && hours="$AUDIT_HOURS"
      [ "$service" = ledger ] && hours="$LEDGER_HOURS"
      [ "$service" = morning ] && hours="$MORNING_HOURS" && minute="$MORNING_MINUTE"
      [ "$service" = sweep-check ] && hours="$SWEEP_CHECK_HOURS"
      [ "$service" = fetch ] && hours="$FETCH_HOURS"
      printf '  <key>StartCalendarInterval</key>\n  <array>\n'
      for h in $hours; do
        printf '    <dict><key>Hour</key><integer>%s</integer><key>Minute</key><integer>%s</integer></dict>\n' "$h" "$minute"
      done
      printf '  </array>\n'
      return
    fi
  done
  if [ "$service" = ds4 ] || [ "$service" = interactive ]; then
    # Restart on a crash, not after a clean "nothing to serve" exit. #611, #1561.
    printf '  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key>\n  <dict><key>SuccessfulExit</key><false/></dict>\n'
    return
  fi
  printf '  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key><true/>\n'
}

write_plist() {
  local service="$1" dest="$2"
  cat > "$dest/$PREFIX.$service.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PREFIX.$service</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$DEPLOY/scripts/serve-$service.sh</string>
  </array>
$(_schedule "$service")
  <key>WorkingDirectory</key><string>$DEPLOY</string>
  <key>StandardOutPath</key><string>$LH_LOGS/$service.log</string>
  <key>StandardErrorPath</key><string>$LH_LOGS/$service.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$JOB_PATH</string>
    <key>HOME</key><string>$HOME</string>
    <!-- stdout is a file here, so an unbuffered log is the only progress. -->
    <key>PYTHONUNBUFFERED</key><string>1</string>
$(_hf_env)$(_watchdog_env "$service")  </dict>
  <key>ProcessType</key><string>Interactive</string>
</dict>
</plist>
PLIST
}

# A running loop keeps the code it imported, so a deploy under it leaves it on the old code. #1000.
sweep_guard() {
  python3 -I "$REPO/harness/sweep_guard.py" "$LH_HOME" || exit 1
}

deploy() {
  sweep_guard
  git -C "$SRC" fetch -q origin main
  local want; want="$(git -C "$SRC" rev-parse origin/main)"
  # Two green PRs can merge into a red main; deploy only a commit whose own push run passed. #870.
  python3 -I "$REPO/harness/deploy_guard.py" "$want" "$SRC" || exit 1
  if [ ! -e "$DEPLOY/.git" ]; then
    git -C "$SRC" worktree add -q --detach "$DEPLOY" "$want"
  elif [ -n "$(git -C "$DEPLOY" status --porcelain --untracked-files=no)" ]; then
    echo "FATAL: $DEPLOY has local edits. It only ever runs origin/main;" >&2
    echo "       move the edits to a branch elsewhere, then re-run." >&2
    exit 1
  else
    git -C "$DEPLOY" checkout -q --detach "$want"
  fi
  echo "deployed $(git -C "$DEPLOY" rev-parse --short HEAD) (origin/main) to $DEPLOY"
}

generate() {
  local dest="${1:-$LH_HOME/launchd}"
  mkdir -p "$dest" "$LH_LOGS"
  for service in $(units); do
    write_plist "$service" "$dest"
    echo "wrote $dest/$PREFIX.$service.plist"
  done
}

# Every path a unit reads that may sit on a protected volume: the weights root, and $LH_HOME's links onto /Volumes. #1516.
_probe_roots() {
  local l
  printf '%s\n' "$1"
  for l in "$LH_HOME"/*; do
    [ -L "$l" ] || continue
    case "$(readlink "$l")" in /Volumes/*) printf '%s\n' "$l" ;; esac
  done
  return 0
}

# Can a launchd agent actually read the weights volume?
#
# Checking from THIS shell proves nothing: the terminal already has the Full
# Disk Access the agent lacks. macOS TCC protects /Volumes and a background job
# has no way to ask for consent, so the volume stats fine, reports free space,
# appears in /Volumes -- and every read returns "Operation not permitted".
# mlx_lm turns that into a permanent hang inside os.listdir, with the server
# accepting connections and answering none, which is a genuinely horrible way
# to find out about a permission. So probe from inside launchd first, as the units run: /bin/bash, then this checkout's python.
preflight() {
  local probe="/tmp/localharness-preflight.$$"
  local label="$PREFIX.preflight.$$"   # per run: parallel suites share gui/$UID
  local root; root="$(_hf_root)"
  local wait_s="${PREFLIGHT_WAIT_S:-60}"
  if [ -z "$root" ]; then
    echo "FATAL: scripts/env.sh gives the agents no weights root, so there is nothing to probe:" >&2
    (cd "$REPO" && . scripts/env.sh >/dev/null) 2>&1 | sed 's/^/  /' >&2
    exit 1
  fi
  local roots=() r
  while IFS= read -r r; do roots+=("$r"); done < <(_probe_roots "$root")
  local quoted py
  quoted="$(printf '%q ' "${roots[@]}")"
  py="$(printf '%q' "$REPO/.venv/bin/python")"
  cat > "$probe.sh" <<PROBE
#!/bin/bash
echo started > "$probe.started"
for r in $quoted; do
  ls "\$r/" >/dev/null 2>&1 || { echo "denied \$r" > "$probe.out"; exit 0; }
done
if [ -x $py ] && ! $py -I -c 'import os, sys; [os.listdir(r) for r in sys.argv[1:]]' $quoted >/dev/null 2>&1; then
  echo "denied to python" > "$probe.out"; exit 0
fi
echo ok > "$probe.out"
PROBE
  chmod +x "$probe.sh"
  cat > "$probe.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$label</string>
<key>ProgramArguments</key><array><string>/bin/bash</string><string>$probe.sh</string></array>
<key>WorkingDirectory</key><string>$REPO</string>
<key>RunAtLoad</key><true/>
</dict></plist>
PLIST
  launchctl bootout "gui/$UID/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID" "$probe.plist" 2>/dev/null || true
  for _ in $(seq 1 $((wait_s * 2))); do [ -f "$probe.out" ] && break; sleep 0.5; done
  local verdict; verdict="$(cat "$probe.out" 2>/dev/null || echo unknown)"
  # Started and never finished: blocked in the kernel on a privacy consent. #1516.
  if [ "$verdict" = unknown ] && [ -f "$probe.started" ]; then verdict=pending; fi
  launchctl bootout "gui/$UID/$label" 2>/dev/null || true
  rm -f "$probe.sh" "$probe.plist" "$probe.out" "$probe.started"

  if [ "$verdict" = pending ]; then
    cat >&2 <<MSG
FATAL: consent pending: the launchd probe started reading ${roots[*]} and was still blocked after $wait_s s.

  macOS holds a read of a protected volume while it waits for a privacy
  consent, and a dialog may be open on this machine's screen. Every unit
  started now would block the same way. A launchd agent gets the read only
  through Full Disk Access on /bin/bash, the program launchd runs for it:
    System Settings > Privacy & Security > Full Disk Access
    /bin/bash must be listed and switched on (+, Cmd+Shift+G, /bin/bash, Open)
  The dialog grants only the program that asked; do not rely on it.

  Then re-run: ./scripts/launchd.sh probe
MSG
    exit 1
  fi
  if [ "$verdict" = unknown ]; then
    cat >&2 <<MSG
FATAL: the launchd probe of $root did not finish in $wait_s s.

  This says nothing about permissions: launchd did not run the probe, or it
  is still waiting on a slow or sleeping volume. Re-run with a longer wait:
    PREFLIGHT_WAIT_S=180 ./scripts/launchd.sh install
MSG
    exit 1
  fi
  if [ "$verdict" != "ok" ]; then
    cat >&2 <<MSG
FATAL: a launchd agent cannot read $root ($verdict).

  macOS TCC protects /Volumes, and a background job has no way to ask for
  consent. The volume stats fine and shows up in /Volumes, so nothing looks
  wrong until mlx_lm hangs forever inside os.listdir -- serving no requests
  and logging no error.

  To fix, grant Full Disk Access to the program launchd runs:
    System Settings > Privacy & Security > Full Disk Access > +
    add /bin/bash   (this is broad; a narrower option is to point these
                     units at a dedicated interpreter and grant only that)

  Then re-run: ./scripts/launchd.sh install

  Or skip launchd and start the services from a terminal that already has
  the access, which is what ./scripts/serve-*.sh do today.
MSG
    exit 1
  fi
}

#: `bootout` RETURNS BEFORE THE JOB IS GONE. It signals the process and the
#: label lives on until the teardown completes, so the bootstrap that follows
#: hits an already-loaded label and fails with "Bootstrap failed: 5: Input/
#: output error", which names neither the service nor the cause.
_await_unload() {
  local label="$1" left=50
  while [ "$left" -gt 0 ]; do
    launchctl print "gui/$UID/$label" >/dev/null 2>&1 || return 0
    left=$((left - 1))
    sleep 0.2
  done
  return 1
}

# The pid of a label's live run; empty when it is idle or not loaded. #794.
_live_pid() {
  local out
  out="$(launchctl print "gui/$UID/$1" 2>/dev/null)" || return 0
  awk '/^\tpid = /{print $3; exit}' <<<"$out"
}

# A node unloads the units an earlier install of a wider role left behind.
drop_periodic() {
  local p dropped="${SCHEDULER_ONLY[*]}"
  [ "$LH_ROLE" = interactive ] && dropped="$(for p in $SERVICES; do [ "$p" = interactive ] || echo "$p"; done)"
  for p in $dropped; do
    if launchctl print "gui/$UID/$PREFIX.$p" >/dev/null 2>&1; then
      launchctl bootout "gui/$UID/$PREFIX.$p"
    fi
    rm -f "$AGENTS/$PREFIX.$p.plist"
    echo "removed $PREFIX.$p (LH_ROLE=$LH_ROLE)"
  done
}

# Run the copy deploy just checked out, or units added by the deployed commit are never installed. #821.
_run_deployed() {
  [ "${LH_REEXECED:-}" = 1 ] && return 0
  [ "$(cksum < "$DEPLOY/scripts/launchd.sh")" = "$SELF_SUM" ] && return 0
  echo "re-running as the deployed $DEPLOY/scripts/launchd.sh"
  LH_REEXECED=1 LH_REPO="$SRC" LH_DEPLOY="$DEPLOY" exec bash "$DEPLOY/scripts/launchd.sh" "$@"
}

install_units() {
  local UV
  UV="$(_find_uv)" || exit 1
  # reinstall: a queue deploy already switched DEPLOY to this release, so nothing is checked out. #1506.
  if [ "${1:-}" != reinstall ]; then
    deploy
    _run_deployed install
  fi
  preflight
  [ "${1:-}" = reinstall ] || _record_install_env
  mkdir -p "$AGENTS"
  local before
  before="$(_unit_sums)"
  generate "$AGENTS" >/dev/null
  local failed="" deferred="" refused=""
  local was="" pid
  for service in $(units); do
    # A bootout signals a periodic job mid-run, and the run is lost without a trace. #794.
    pid=""
    case " ${PERIODIC[*]} " in *" $service "*) pid="$(_live_pid "$PREFIX.$service")" ;; esac
    if [ -n "$pid" ]; then
      deferred="$deferred $service"
      echo "NOT reloading $PREFIX.$service: a run is live (pid $pid) and bootout would kill it" >&2
      continue
    fi
    if [ "$service" = interactive ] && ! (cd "$DEPLOY" && _as_unit "$UV" run python -m harness.interactive check); then
      # The pinned set must fit beside the largest eval pair, or it is not served at all. #1561.
      if launchctl print "gui/$UID/$PREFIX.$service" >/dev/null 2>&1; then
        launchctl bootout "gui/$UID/$PREFIX.$service"
      fi
      refused="$refused $service"
      continue
    fi
    if [ "$service" = worker ]; then
      # Reloading the worker kills its running job, so let that job finish first. #577.
      echo "waiting for any running queued job to finish before reloading the worker"
      if ! was=$(cd "$DEPLOY" && "$UV" run python -m harness.workqueue quiesce); then
        echo "could not quiesce the queue; reloading the worker anyway" >&2
        was=""
      fi
    fi
    # KEEP GOING AND REPORT. `set -e` here left the machine running a MIX of
    # old and new agents and said only that something failed, which is worse
    # than either all-old or all-new because nothing on it is a known state.
    if _reload "$service"; then
      if [ "$service" = worker ] && [ "$was" = was-running ]; then
        (cd "$DEPLOY" && "$UV" run soh jobs resume >/dev/null)
      fi
    else
      failed="$failed $service"
    fi
  done
  # An every-minute unit is nearly always mid-run when install reaches it, so wait out the run. #1058.
  if [ -n "$deferred" ]; then
    local end=$((SECONDS + DEFER_WAIT_S)) still
    echo "waiting up to ${DEFER_WAIT_S}s for the live run of:$deferred"
    while :; do
      still=""
      for service in $deferred; do
        if [ -n "$(_live_pid "$PREFIX.$service")" ]; then
          still="$still $service"
        elif ! _reload "$service"; then
          failed="$failed $service"
        fi
      done
      deferred="$still"
      [ -n "$deferred" ] && [ "$SECONDS" -lt "$end" ] || break
      sleep 1
    done
  fi
  [ "$LH_ROLE" = scheduler ] || drop_periodic
  # A deferral is not a failure: the unit runs the deploy path, so its next run starts the deployed code. #1521.
  if [ -n "$deferred" ]; then
    local now same="" stale=""
    now="$(_unit_sums)"
    for service in $deferred; do
      if [ "$(_sum_of "$service" "$before")" = "$(_sum_of "$service" "$now")" ]; then
        same="$same $service"
      else
        stale="$stale $service"
      fi
    done
    echo >&2
    [ -z "$same" ] || echo "deferred:$same -- mid-run; its unit is unchanged, so its next run starts the deployed code." >&2
    [ -z "$stale" ] || echo "deferred:$stale -- mid-run, and its unit changed: it keeps the old unit until the next install. Re-run install after it finishes." >&2
  fi
  # monit watches the machine through every deploy, so an install leaves it loaded or says it is not. #1521.
  if [ -f "$AGENTS/$PREFIX.monit.plist" ] && ! (cd "$DEPLOY" && "$UV" run --quiet soh monitor install); then
    failed="$failed monit"
  fi
  if [ -n "$failed" ]; then
    echo >&2
    echo "not loaded:$failed -- the rest are running, so this machine is" >&2
    echo "part old and part new. Re-run install." >&2
    return 1
  fi
  # A launchd job can be refused the LAN while Terminal is not: Local Network privacy. #739.
  local blocked=0
  if ! /bin/bash "$DEPLOY/scripts/lan-probe.sh"; then
    echo "the gateway is loaded but launchd cannot reach a serving node; see above" >&2
    blocked=1
  fi
  if [ -n "$refused" ]; then
    echo "refused:$refused -- harness.interactive check did not pass; see above" >&2
    blocked=1
  fi
  # A node with no machine fingerprint files every run it serves under no machine. #781.
  if ! (cd "$DEPLOY" && "$UV" run python -m harness.nodes check); then
    echo "a serving node has no machine fingerprint; set machine: in nodes.yaml, see above" >&2
    blocked=1
  fi
  # The deploy is not done until the store it now serves passes the audit; an interactive node serves none. #492, #1562.
  if [ "$LH_ROLE" != interactive ] && ! /bin/bash "$DEPLOY/scripts/serve-audit.sh"; then
    echo "the deployed units are loaded but the live store FAILS its audit; see above" >&2
    return 1
  fi
  [ "$blocked" -eq 0 ] || return 1
  echo
  echo "Give them a moment, then: ./scripts/smoke.sh"
}

# "service=cksum" per periodic unit file, so install can tell whether a deferred unit's definition changed.
_unit_sums() {
  local p
  for p in "${PERIODIC[@]}"; do
    [ -f "$AGENTS/$PREFIX.$p.plist" ] && printf '%s=%s\n' "$p" "$(cksum < "$AGENTS/$PREFIX.$p.plist" | tr ' ' _)"
  done
  return 0
}

_sum_of() {
  printf '%s\n' "$2" | awk -F= -v s="$1" '$1 == s {print $2; exit}'
}

# print-disabled says "label" => disabled (macOS 13+) or => true (older).
_disabled() {
  launchctl print-disabled "gui/$UID" 2>/dev/null |
    awk -v l="\"$1\"" '$1 == l && ($3 == "disabled" || $3 == "true") {f = 1} END {exit !f}'
}

# bootout first so `install` is re-runnable: bootstrap on an already-loaded label fails.
_reload() {
  launchctl bootout "gui/$UID/$PREFIX.$1" 2>/dev/null || true
  _await_unload "$PREFIX.$1" || true
  # `launchctl disable` is someone's deliberate choice, not a failed load. #1564.
  if _disabled "$PREFIX.$1"; then
    echo "NOT loading $PREFIX.$1: launchctl disable is in force. Re-enable with: launchctl enable gui/$UID/$PREFIX.$1 && scripts/launchd.sh install" >&2
    return 0
  fi
  if launchctl bootstrap "gui/$UID" "$AGENTS/$PREFIX.$1.plist"; then
    echo "loaded $PREFIX.$1"
    return 0
  fi
  echo "FAILED to load $PREFIX.$1" >&2
  return 1
}

uninstall_units() {
  for service in $SERVICES; do
    launchctl bootout "gui/$UID/$PREFIX.$service" 2>/dev/null || true
    rm -f "$AGENTS/$PREFIX.$service.plist"
    echo "removed $PREFIX.$service"
  done
}

status() {
  if [ -e "$DEPLOY/.git" ]; then
    echo "running $(git -C "$DEPLOY" rev-parse --short HEAD) from $DEPLOY;" \
         "origin/main is $(git -C "$SRC" rev-parse --short origin/main)"
  else
    echo "no deploy checkout at $DEPLOY: run install"
  fi
  for service in $SERVICES; do
    printf '%-12s ' "$service"
    # First match only: launchctl print reports the job state and then several
    # "active" lines for its endpoints, which read as three answers to one
    # question.
    launchctl print "gui/$UID/$PREFIX.$service" 2>/dev/null \
      | awk '/^\tstate = /{print $3; found=1; exit} END{if(!found) print "not loaded"}'
  done
}

case "${1:-}" in
  deploy)    deploy ;;
  # The one definition of DEPLOY; harness/paths.py asks here. #455.
  deploy-path) printf '%s\n' "$DEPLOY" ;;
  generate)  shift; generate "${1:-}" ;;
  probe)     preflight && echo "ok: a launchd agent can read $(_hf_root)" ;;
  install)
    # Restarting a model server mid-run killed 32 requests on 2026-10-04, so
    # wait for any model-loading run to finish first. #314.
    if [ "${LH_GPU_LOCK_HELD:-}" != 1 ]; then
      sweep_guard
      exec "$REPO/scripts/with-gpu-lock" --repair "$0" install
    fi
    install_units ;;
  reinstall)
    if [ "${LH_GPU_LOCK_HELD:-}" != 1 ]; then
      sweep_guard
      exec "$REPO/scripts/with-gpu-lock" --repair "$0" reinstall
    fi
    install_units reinstall ;;
  restart)
    # One loaded service, after any model-loading run. A no-op when the
    # service is not loaded (another machine, or not installed). #319.
    label="$PREFIX.${2:?usage: $0 restart SERVICE}"
    launchctl print "gui/$UID/$label" >/dev/null 2>&1 || exit 0
    "$REPO/scripts/with-gpu-lock" launchctl kickstart -k "gui/$UID/$label" ;;
  uninstall) uninstall_units ;;
  status)    status ;;
  *)         usage ;;
esac
