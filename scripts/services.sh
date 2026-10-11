#!/usr/bin/env bash
# Starting and stopping the services on demand only.
#
# THE DEFAULT IS OFF, AND THERE IS NOTHING TO TURN OFF. scripts/launchd.sh
# installs units with RunAtLoad and KeepAlive, which is right for a machine
# whose job is to serve. This one has a day job and runs this sometimes, so
# nothing here is registered with the operating system at all: no
# scheduled task, no Run key, no startup shortcut, AND NO SYSTEMD UNIT. A
# reboot leaves the card empty, and `stop` leaves nothing behind that could
# start again on its own.
#
# WINDOWS AND LINUX BOTH RUN THIS FILE. Neither registers anything, so a
# machine that boots both gets the same on-demand treatment from each rather
# than one supervision system per operating system, and no third supervision
# system. The only differences are how a process is launched detached, how it
# is asked whether it is alive, and how its whole tree is ended.
#
#   ./scripts/services.sh start          # gateway, text, audio
#   ./scripts/services.sh start llamacpp # just one
#   ./scripts/services.sh stop           # all of them, and the card is free
#   ./scripts/services.sh status         # what is up, and what the card holds
#
# The text server also gives the card back by itself after
# $LLAMACPP_SLEEP_IDLE seconds, so a session left running overnight is not
# holding 8 GB by morning. `stop` is the immediate version of the same thing.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

LH_HOME="${LOCALHARNESS_HOME:-$HOME/localharness}"
RUN="$LH_HOME/run"
LOGS="$LH_HOME/logs"
mkdir -p "$RUN" "$LOGS"

# name -> the launcher that serves it. A case rather than an associative
# array: `declare -A` is bash 4, macOS ships bash 3.2 as /bin/bash, and there
# it does not fail -- it reads [gateway]="..." as an arithmetic subscript and
# dies with "gateway: unbound variable" under set -u. This machine's own
# launchers are launchd's, so nobody would have run into it in anger; the
# tests would have had to skip on a whole runner instead.
launcher_for() {
  case "$1" in
    gateway)  printf '%s\n' "scripts/serve-gateway.sh" ;;
    llamacpp) printf '%s\n' "scripts/serve-llamacpp.sh" ;;
    audio)    printf '%s\n' "scripts/serve-audio-cuda.sh" ;;
    ds4)      printf '%s\n' "scripts/serve-ds4.sh" ;;
    *)        return 1 ;;
  esac
}
ALL=(gateway llamacpp audio)
# Named, never started by default: one ds4 launch holds tens of GiB. #611.
OPTIONAL=(ds4)

usage() {
  echo "usage: $0 {start|stop|restart|status} [${ALL[*]} ${OPTIONAL[*]}]" >&2
  # Named apart from the verbs above because it is the only one that outlives
  # the session it was run in. #684.
  echo "       $0 {install-node|uninstall-node|check-node}  serve at logon, Windows only" >&2
  exit 2
}

pidfile() { printf '%s\n' "$RUN/$1.pid"; }

# The port each service answers on. Read from the same variables the launchers
# read, so the two cannot disagree about where a service lives.
port_for() {
  case "$1" in
    gateway)  printf '%s\n' "${GATEWAY_PORT:-4000}" ;;
    llamacpp) printf '%s\n' "${LLAMACPP_PORT:-8081}" ;;
    audio)    printf '%s\n' "${AUDIO_PORT:-8890}" ;;
    ds4)      printf '%s\n' "${DS4_PORT:-8087}" ;;
    *)        return 1 ;;
  esac
}

# Is anything listening there? THE QUESTION EVERY CALLER IS ACTUALLY ASKING.
# A pidfile answers "did this script start it", which differs from "is it up"
# exactly when another supervisor is in play -- and on the machine whose whole
# job is to serve, launchd IS the supervisor, so `status` reported every
# service down while the gateway was answering requests. Issue #173.
listening() {
  local port="$1"
  if command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "$port" >/dev/null 2>&1 && return 0
    return 1
  fi
  # No nc on a minimal image or on Git Bash. /dev/tcp is a bash builtin and
  # needs no package, but it is bash-only, which is why nc is tried first.
  (exec 3<>"/dev/tcp/127.0.0.1/$port") >/dev/null 2>&1 && return 0
  return 1
}

# A BOUND PORT IS NOT A WORKING SERVICE. `listening` answers whether something
# holds the port, which is what `stop` needs to know. It is not what a reader
# asking "is this working" needs: mlx_lm.server held :8081 for hours with an
# empty model list and every request hanging, and status reported it `up` the
# whole time. Four text lanes were unrunnable and the only visible symptom was
# models timing out, which reads as the model failing. #255.
#
# One cheap GET with a short timeout. A service that cannot answer its own
# listing in three seconds is not serving, whatever the port says.
answering() {
  local port="$1" path="$2"
  [ -n "$path" ] || return 0          # no probe defined: the port is all we have
  command -v curl >/dev/null 2>&1 || return 0
  curl -fsS -m 3 -o /dev/null "http://127.0.0.1:$port$path" >/dev/null 2>&1
}

# service -> the cheapest endpoint that proves it can do its job. A service
# absent here is judged by its port alone, which is the old behaviour.
# NAMED AS THIS SCRIPT NAMES THEM, not as the launchd agents do. The two
# disagree: :8081 is `llamacpp` here and `com.unxmaal.localharness.mlx` there,
# which is why `stop` would not touch the wedged server this morning and why a
# probe keyed on `mlx` silently covered nothing. #255.
probe_for() {
  case "$1" in
    gateway)  printf '/health/liveliness' ;;
    llamacpp) printf '/v1/models' ;;
    audio)    printf '/v1/models' ;;
    ds4)      printf '/v1/models' ;;
    *)        printf '' ;;
  esac
}

# PowerShell cannot take a POSIX path for a working directory or a redirect,
# and Git Bash reports every path that way. Passing $PWD straight through made
# Start-Process fail before it launched anything, which arrived as an empty
# error log rather than as a message.
winpath() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$1"
  else
    printf '%s\n' "$1"
  fi
}

# True on the Windows half of the desktop. $OS is set by Windows itself and
# survives into Git Bash, which is the same test serve-audio-cuda.sh uses.
is_windows() { [ "${OS:-}" = "Windows_NT" ]; }

alive() {
  local pid="$1"
  [ -n "$pid" ] || return 1
  if is_windows; then
    # tasklist rather than kill -0: a Windows pid is not in bash's process
    # table, so kill -0 reports every one of them as gone.
    tasklist //FI "PID eq $pid" //NH 2>/dev/null | grep -q "$pid"
  else
    kill -0 "$pid" 2>/dev/null
  fi
}

start_one() {
  local name="$1" script pid bash_exe work out err pidpath
  script="$(launcher_for "$1" || true)"
  [ -n "$script" ] || { echo "unknown service $name" >&2; return 1; }
  pid="$(cat "$(pidfile "$name")" 2>/dev/null || true)"
  if alive "$pid"; then
    echo "$name already up (pid $pid)"
    return 0
  fi

  if is_windows; then
    bash_exe="$(winpath "$(command -v bash)")"
    work="$(winpath "$PWD")"
    out="$(winpath "$LOGS/$name.log")"
    err="$(winpath "$LOGS/$name.err.log")"
    pidpath="$(winpath "$(pidfile "$name")")"

    # Start-Process rather than `&`: a background job in this shell dies with
    # the terminal, and the point is to close the terminal and go and play
    # something.
    #
    # THE PID GOES TO A FILE RATHER THAN TO STDOUT. Capturing it with $( )
    # hangs forever: the process being launched inherits the pipe, so the
    # substitution waits for an end-of-file that arrives only when the server
    # it just started exits, which is the opposite of starting something in the
    # background.
    rm -f "$(pidfile "$name")"
    powershell -NoProfile -Command \
      "(Start-Process -FilePath '$bash_exe' -ArgumentList '$script'\
       -WorkingDirectory '$work' -WindowStyle Hidden -PassThru\
       -RedirectStandardOutput '$out' -RedirectStandardError '$err').Id\
       | Set-Content -Path '$pidpath'" >/dev/null 2>&1
  else
    # setsid, so the server leads its own process group and closing this
    # terminal does not take it with it -- the same requirement Start-Process
    # meets on the other half of this machine. nohup where there is no setsid,
    # which is any BSD including macOS.
    rm -f "$(pidfile "$name")"
    if command -v setsid >/dev/null 2>&1; then
      setsid bash "$script" >"$LOGS/$name.log" 2>"$LOGS/$name.err.log" &
    else
      nohup bash "$script" >"$LOGS/$name.log" 2>"$LOGS/$name.err.log" &
    fi
    printf '%s\n' "$!" > "$(pidfile "$name")"
  fi

  pid="$(tr -d ' \r\n' < "$(pidfile "$name")" 2>/dev/null || true)"
  case "$pid" in
    "" | *[!0-9]*)
      echo "$name failed to start; see $LOGS/$name.err.log" >&2
      rm -f "$(pidfile "$name")"
      return 1 ;;
  esac
  # LOOK AGAIN BEFORE SAYING IT STARTED. Start-Process returns a pid for a
  # process that has already exited, so a launcher that dies on its first line
  # is reported as running and the pid file backs the claim up. That is the
  # failure this whole file exists to avoid: a service nobody knows is down.
  sleep 2
  if ! alive "$pid"; then
    echo "$name exited immediately:" >&2
    tail -3 "$LOGS/$name.err.log" 2>/dev/null | sed 's/^/  /' >&2
    rm -f "$(pidfile "$name")"
    return 1
  fi
  echo "$name started (pid $pid)"
}

stop_one() {
  local name="$1" pid
  pid="$(cat "$(pidfile "$name")" 2>/dev/null || true)"
  if ! alive "$pid"; then
    rm -f "$(pidfile "$name")"
    echo "$name not running"
    return 0
  fi
  # THE WHOLE TREE, not the pid recorded. That pid is bash; the server holding
  # the card is its child, and ending the parent alone leaves the model
  # resident.
  if is_windows; then
    taskkill //F //T //PID "$pid" >/dev/null 2>&1
  else
    # Negative pid is the process group, which setsid made this process lead.
    # TERM first so the server can put the card down, then KILL what is left.
    kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    for _ in 1 2 3 4 5; do
      alive "$pid" || break
      sleep 1
    done
    alive "$pid" && { kill -KILL "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null; }
  fi
  rm -f "$(pidfile "$name")"
  echo "$name stopped"
}

# BEGIN node registration
# THE ONE THING IN THIS FILE THAT REGISTERS ANYTHING, AND IT IS ASKED FOR BY NAME.
#
# Everything above registers nothing, for the reason at the top of this file:
# a box with a day job that starts a model server at logon has lost 8 GB of
# VRAM to a machine that was supposed to be idle. #684 adds the one case that
# has to come back after a reboot with nobody present, a serving node behind
# another machine's gateway, so the reversal lives in this fenced region and
# test_nothing_registers_itself_to_start_on_its_own holds it here.
#
# It stays tolerable only because the launcher keeps --sleep-idle-seconds: the
# node gives the card back between requests, so a registered node idles at a
# few hundred MiB rather than at the size of the model.
NODE_TASK="${NODE_TASK_NAME:-sohot-llamacpp-node}"

# C:/x rather than C:\x. The task hands this to bash, where a backslash is an
# escape, and cygpath -w produces exactly the spelling bash cannot read.
mixedpath() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -m "$1"
  else
    printf '%s\n' "$1"
  fi
}

install_node() {
  is_windows || { echo "install-node is Windows only; use launchd.sh elsewhere" >&2; return 1; }

  local key_file="${LLAMACPP_API_KEY_FILE:-}"
  if [ -z "$key_file" ]; then
    echo "FATAL: set LLAMACPP_API_KEY_FILE first." >&2
    echo "       A node on a LAN address with no key answers the whole subnet." >&2
    return 1
  fi
  [ -r "$key_file" ] || { echo "FATAL: cannot read $key_file" >&2; return 1; }

  local host port launcher bash_exe
  host="${LLAMACPP_HOST:-0.0.0.0}"
  port="${LLAMACPP_PORT:-8081}"

  # A GENERATED LAUNCHER RATHER THAN A COMMAND LINE. The environment and the
  # start verb go in a file, and the task runs that one file, so no quoting
  # survives the trip through Task Scheduler. The first attempt at this went
  # through cmd, whose /c strips the outer quotes of a command that begins with
  # one: the task exited 1, started nothing, and wrote nothing to the log, and
  # the task's own history said only "the operator declined the request".
  launcher="$RUN/node-launch.sh"
  cat > "$launcher" <<LAUNCH
#!/usr/bin/env bash
# GENERATED by services.sh install-node. Rewritten on every install; edits here
# are lost. Change the environment and run install-node again.
cd "$PWD" || exit 1
export LLAMACPP_HOST="$host"
export LLAMACPP_PORT="$port"
export LLAMACPP_API_KEY_FILE="$key_file"
exec ./scripts/services.sh start llamacpp
LAUNCH
  chmod +x "$launcher"

  bash_exe="$(winpath "$(command -v bash)")"
  powershell -NoProfile -Command \
    "\$a = New-ScheduledTaskAction -Execute '$bash_exe'\
       -Argument '\"$(mixedpath "$launcher")\"'\
       -WorkingDirectory '$(winpath "$PWD")';\
     \$t = New-ScheduledTaskTrigger -AtLogOn;\
     \$p = New-ScheduledTaskPrincipal -UserId \$env:USERNAME\
       -LogonType Interactive -RunLevel Limited;\
     \$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero)\
       -MultipleInstances IgnoreNew -StartWhenAvailable;\
     Register-ScheduledTask -TaskName '$NODE_TASK' -Action \$a -Trigger \$t\
       -Principal \$p -Settings \$s -Force | Out-Null" || {
    echo "FATAL: could not register $NODE_TASK" >&2
    return 1
  }
  echo "$NODE_TASK registered; it starts llamacpp at logon"
  echo
  # THE EXIT STATUS IS check_node'S, DELIBERATELY. Registering the task is not
  # the same as the node being ready: the firewall rule and the sleep setting
  # need admin and are not applied here, so install-node reports non-zero while
  # either is outstanding rather than returning success beside a warning.
  check_node
}

# Whether anything already allows inbound TCP on the node's port.
#
# BY PORT, NOT BY RULE NAME. A rule that does the job under some other name is
# not missing, and the first one on this node was created by the Windows
# "allow this app" prompt rather than by the command below, so a name match
# would have reported it absent while the node was answering the subnet. The
# cost of asking this way is that an unrelated rule on the same port reads as
# ok, which is why the wording below says something rather than the rule.
node_firewall_ok() {
  powershell -NoProfile -Command \
    "\$p = '$1';\
     \$r = Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow\
       -ErrorAction SilentlyContinue |\
       Where-Object { (\$_ | Get-NetFirewallPortFilter).LocalPort -contains \$p };\
     if (\$r) { exit 0 } else { exit 1 }" >/dev/null 2>&1
}

# Whether this machine stays awake on AC. Read through PowerShell rather than
# by running powercfg from here: MSYS rewrites /query into a path before
# powercfg sees it, and the call then fails in a way that reads as "not set".
node_sleep_ok() {
  powershell -NoProfile -Command \
    "\$v = powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE |\
       Select-String 'Current AC Power Setting Index';\
     if (\"\$v\" -match '0x00000000') { exit 0 } else { exit 1 }" >/dev/null 2>&1
}

# What is in place and what is not. BOTH REMAINING STEPS NEED ADMIN AND NOTHING
# HERE OWNS THEM, so the alternative was printing two commands every time and
# letting the reader guess whether they had already been run. Each can be read
# without admin, so each is reported, and a command is printed only for what is
# actually missing.
check_node() {
  is_windows || { echo "check-node is Windows only" >&2; return 1; }
  local port rc=0
  port="${LLAMACPP_PORT:-8081}"

  if powershell -NoProfile -Command \
      "if (Get-ScheduledTask -TaskName '$NODE_TASK' -ErrorAction SilentlyContinue)\
       { exit 0 } else { exit 1 }" >/dev/null 2>&1; then
    printf 'task      ok       %s is registered\n' "$NODE_TASK"
  else
    printf 'task      MISSING  run: %s install-node\n' "$0"
    rc=1
  fi

  if node_firewall_ok "$port"; then
    printf 'firewall  ok       something allows inbound TCP %s\n' "$port"
  else
    printf 'firewall  MISSING  run this in an elevated shell:\n'
    echo "    New-NetFirewallRule -DisplayName '$NODE_TASK' -Direction Inbound \\"
    echo "      -Action Allow -Protocol TCP -LocalPort $port -Profile Private \\"
    echo "      -Program '<the server binary, as serve-llamacpp.sh resolves it>'"
    rc=1
  fi

  if node_sleep_ok; then
    printf 'sleep     ok       does not sleep on AC\n'
  else
    printf 'sleep     MISSING  run this in an elevated shell:\n'
    echo "    powercfg /change standby-timeout-ac 0"
    rc=1
  fi

  return "$rc"
}

uninstall_node() {
  is_windows || { echo "uninstall-node is Windows only" >&2; return 1; }
  # SAY WHICH OF THE TWO HAPPENED. The usual reason this fails is that there
  # was no task to remove, which is not an error and is not the same as having
  # removed one either.
  if powershell -NoProfile -Command \
      "Unregister-ScheduledTask -TaskName '$NODE_TASK' -Confirm:\$false" \
      >/dev/null 2>&1; then
    echo "$NODE_TASK removed; a running server is left alone, stop it if you meant to"
  else
    echo "no $NODE_TASK was registered; nothing to remove"
  fi
  rm -f "$RUN/node-launch.sh"
  echo "the firewall rule and the never-sleep setting are still in place"
}
# END node registration

status() {
  local name pid port
  for name in "${ALL[@]}"; do
    pid="$(cat "$(pidfile "$name")" 2>/dev/null || true)"
    port="$(port_for "$name")"
    if listening "$port"; then
      if ! answering "$port" "$(probe_for "$name")"; then
        # Bound and not serving. The state that cost hours: `up` here sends a
        # reader looking at the models instead of at the service.
        printf '%-9s WEDGED:%-5s holds the port and does not answer%s\n' \
          "$name" "$port" "$(alive "$pid" && printf ', pid %s' "$pid" || true)"
      elif alive "$pid"; then
        printf '%-9s up    :%-5s pid %s\n' "$name" "$port" "$pid"
      else
        # Up, and not by this script. Say so rather than claiming it: `stop`
        # can only stop what it started, and a reader about to run it should
        # know that before being surprised.
        printf '%-9s up    :%-5s (not started by this script)\n' "$name" "$port"
      fi
    elif alive "$pid"; then
      # A live process that answers on no port is starting, wedged, or dying.
      # Three states, and none of them is "up".
      printf '%-9s ?     :%-5s pid %s, not answering yet\n' "$name" "$port" "$pid"
    else
      printf '%-9s down  :%s\n' "$name" "$port"
    fi
  done
  # The question before starting a game is what the card is holding, which is
  # a different question from which of these is running: a sleeping text server
  # is up and holding nothing.
  if command -v nvidia-smi >/dev/null 2>&1; then
    printf 'vram      %s\n' "$(nvidia-smi --query-gpu=memory.used,memory.total \
      --format=csv,noheader 2>/dev/null | head -1)"
  fi
}

[ $# -ge 1 ] || usage
verb="$1"; shift
targets=("$@")
[ ${#targets[@]} -gt 0 ] || targets=("${ALL[@]}")

case "$verb" in
  start)  for s in "${targets[@]}"; do start_one "$s"; done ;;
  stop)   for s in "${targets[@]}"; do stop_one "$s"; done ;;
  # The router reads its models dir at startup only, so a fetched GGUF needs one (#327).
  restart) for s in "${targets[@]}"; do stop_one "$s"; start_one "$s"; done ;;
  status) status ;;
  install-node)   install_node ;;
  uninstall-node) uninstall_node ;;
  check-node)     check_node ;;
  *)      usage ;;
esac
