# shellcheck shell=bash
# Reading a server API key from a file. Sourced by the launchers; never run directly.
#
# THE KEY GOES IN A FILE AND ONLY ITS PATH GOES IN ARGV. argv is readable by
# every other process on the machine, it is recorded verbatim in a Windows
# scheduled task definition, and it lands in any log that echoes the command
# it ran. llama-server takes --api-key-file for this reason. #716.

# Print the key held in FILE, or fail saying why.
#
# STRIPS A UTF-8 BOM, which is not cosmetic. PowerShell 5.1 writes one for
# `-Encoding utf8`, so a key file written on the Windows half is 67 bytes where
# 64 were meant. Those three bytes went into the key the server expected and
# were dropped from the Authorization header on the way in, so the CORRECT key
# answered 401 and read as a mismatch. Both sides print identically in every
# log, which is what made it expensive.
#
# Parameter expansion rather than sed: BSD sed on the macOS runner does not
# understand \xef, and the portable spelling of that one substitution is
# longer than this.
read_api_key() {
  local file="$1" key bom
  [ -n "$file" ] || { echo "read_api_key: no file given" >&2; return 1; }
  [ -r "$file" ] || { echo "read_api_key: cannot read $file" >&2; return 1; }
  key="$(cat "$file")"
  bom=$'\xef\xbb\xbf'
  key="${key#"$bom"}"
  # Every kind of whitespace, not just the trailing newline: a file edited on
  # either half of this machine can carry CR, and a key with one in it fails
  # the same way the BOM did.
  key="${key//[[:space:]]/}"
  # AN EMPTY KEY IS NOT A KEYLESS SERVER. It is a server that accepts the empty
  # string, on a LAN address, which is worse than refusing to start.
  [ -n "$key" ] || { echo "read_api_key: $file holds no key" >&2; return 1; }
  printf '%s\n' "$key"
}
