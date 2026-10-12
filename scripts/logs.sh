# shellcheck shell=bash
# Keeping the log of the session before this one. Sourced; never run directly.
#
# WHY ROTATION AND NOT APPEND. PowerShell's Start-Process cannot append:
# -RedirectStandardOutput truncates and has no append mode. So on the Windows
# half the only way to keep the previous session's lines is to move the file
# aside before starting. Both halves do the same thing rather than appending on
# one and rotating on the other, because a machine that boots both should not
# need two explanations of where its logs went. #786.
#
# WHAT THIS COSTS AND WHAT IT BUYS. A 32B load failed intermittently on the
# 4070, and the useful comparison was between the run that failed and an
# earlier run that had succeeded on identical flags. The earlier run's lines
# were gone, because the router had been restarted in between, and the failure
# had to be reasoned out from half the evidence. Discarding the log at exactly
# the moment someone restarts to clear a problem is the wrong default.

#: Generations kept, newest first: x.log, x.log.1 ... x.log.$LOG_KEEP.
LOG_KEEP="${LOG_KEEP:-3}"

#: A log over this is dropped rather than given a generation slot, so one
#: runaway session cannot hold history hostage.
#:
#: THIS DOES NOT BOUND THE LIVE FILE, and no value here could. The server
#: writes to the redirected handle directly, so nothing in bash sees the
#: current log grow. What is bounded is RETAINED history: at most LOG_KEEP
#: generations, none of them over this size.
LOG_MAX_BYTES="${LOG_MAX_BYTES:-67108864}"

# Move FILE aside so the next session writes a fresh one.
rotate_log() {
  local file="$1" keep="${2:-$LOG_KEEP}" i size
  [ -n "$file" ] || return 0
  [ -e "$file" ] || return 0
  # The oldest generation goes first, then each one shifts up a slot.
  rm -f "$file.$keep"
  i=$((keep - 1))
  while [ "$i" -ge 1 ]; do
    if [ -e "$file.$i" ]; then
      mv -f "$file.$i" "$file.$((i + 1))"
    fi
    i=$((i - 1))
  done
  size="$(wc -c < "$file" 2>/dev/null)" || size=0
  size="${size//[^0-9]/}"
  if [ -n "$size" ] && [ "$size" -gt "$LOG_MAX_BYTES" ]; then
    # Kept history is for reading. A file this size is not read, it is grepped
    # once and regretted, and it would evict two useful generations to sit there.
    rm -f "$file"
  else
    mv -f "$file" "$file.1"
  fi
  return 0
}
