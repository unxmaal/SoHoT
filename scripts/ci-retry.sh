#!/usr/bin/env bash
# Run a CI command again after a transient failure (a runner DNS blip, #1440); the last failure's status stands.
set -u
attempts="${CI_RETRY_ATTEMPTS:-4}"
delay="${CI_RETRY_DELAY:-15}"
n=1
while :; do
  "$@"
  rc=$?
  [ "$rc" -eq 0 ] && exit 0
  if [ "$n" -ge "$attempts" ]; then
    echo "ci-retry: '$*' failed $n times; last exit $rc" >&2
    exit "$rc"
  fi
  echo "ci-retry: '$*' exited $rc (attempt $n of $attempts); retrying in ${delay}s" >&2
  sleep "$delay"
  n=$((n + 1))
  delay=$((delay * 2))
done
