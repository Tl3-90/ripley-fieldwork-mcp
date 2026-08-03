#!/usr/bin/env bash
set -euo pipefail

project_dir="${1:-/opt/ripley-api}"
secret_dir="$project_dir/secrets"
state_dir="$project_dir/state"

install -d -m 0700 "$secret_dir"
install -d -m 0700 -o 10001 -g 10001 "$state_dir"

IFS= read -r -p "Ripley email: " ripley_username </dev/tty
IFS= read -r -s -p "Ripley password: " ripley_password </dev/tty
printf '\n' >/dev/tty

if [[ -z "$ripley_username" || -z "$ripley_password" ]]; then
  printf 'Email and password are required.\n' >&2
  exit 1
fi

umask 077
username_tmp="$(mktemp "$secret_dir/.username.XXXXXX")"
password_tmp="$(mktemp "$secret_dir/.password.XXXXXX")"
trap 'rm -f "$username_tmp" "$password_tmp"' EXIT
printf '%s' "$ripley_username" >"$username_tmp"
printf '%s' "$ripley_password" >"$password_tmp"
install -m 0400 -o 10001 -g 10001 "$username_tmp" "$secret_dir/ripley_username.txt"
install -m 0400 -o 10001 -g 10001 "$password_tmp" "$secret_dir/ripley_password.txt"

if [[ ! -s "$secret_dir/ripley_api_key.txt" ]]; then
  api_key_tmp="$(mktemp "$secret_dir/.api-key.XXXXXX")"
  openssl rand -hex 32 >"$api_key_tmp"
  install -m 0400 -o 10001 -g 10001 "$api_key_tmp" "$secret_dir/ripley_api_key.txt"
  rm -f "$api_key_tmp"
else
  chown 10001:10001 "$secret_dir/ripley_api_key.txt"
  chmod 0400 "$secret_dir/ripley_api_key.txt"
fi

unset ripley_username ripley_password
printf 'Ripley credentials stored with mode 400; session state directory is ready.\n'
