#!/bin/zsh

set -u
umask 077

server_name="ripley"
server_url="https://digi.hopto.me/ripley-api/mcp"
health_url="https://digi.hopto.me/ripley-api/health"
environment_name="RIPLEY_API_KEY"
keychain_service="Ripley MCP API Key"
config_directory="$HOME/.codex"
config_path="$config_directory/config.toml"
helper_path="$config_directory/load-ripley-environment.command"
launch_agent_label="com.ripley.codex-mcp-environment"
launch_agent_path="$HOME/Library/LaunchAgents/$launch_agent_label.plist"
temporary_config=""
token=""

cleanup() {
    if [[ -n "$temporary_config" && -f "$temporary_config" ]]; then
        /bin/rm -f "$temporary_config"
    fi
    token=""
}
trap cleanup EXIT HUP INT TERM

finish_with_error() {
    echo ""
    echo "SETUP ERROR: $1"
    echo "Take a screenshot of this window and send it to Thomas."
    echo ""
    read -r "?Press Return to close this window."
    exit 1
}

read_private_token() {
    echo "Paste the Ripley connection key Thomas gave you."
    echo "The key will not appear while you paste or type it."
    printf "Ripley connection key: "
    IFS= read -r -s token
    echo ""
}

token_looks_valid() {
    [[ ${#token} -ge 16 && "$token" != *[[:space:]]* ]]
}

connection_is_healthy() {
    local response
    response=$(/usr/bin/curl --silent --show-error --fail \
        --max-time 30 \
        --header "X-API-Key: $token" \
        "$health_url" 2>/dev/null) || return 1
    echo "$response" | /usr/bin/grep -Eq \
        '"authenticated"[[:space:]]*:[[:space:]]*true' || return 1
    echo "$response" | /usr/bin/grep -Eq \
        '"form_60_available"[[:space:]]*:[[:space:]]*true' || return 1
}

remove_existing_ripley_section() {
    local source_path="$1"
    local destination_path="$2"
    /usr/bin/awk -v section="[mcp_servers.$server_name]" '
        $0 == section { skipping = 1; next }
        skipping && /^\[/ { skipping = 0 }
        !skipping { print }
    ' "$source_path" > "$destination_path"
}

xml_escape() {
    printf "%s" "$1" | /usr/bin/sed \
        -e 's/&/\&amp;/g' \
        -e 's/</\&lt;/g' \
        -e 's/>/\&gt;/g'
}

clear
echo "Ripley MCP setup for Codex on Mac"
echo "----------------------------------"
echo ""

token=$(/usr/bin/security find-generic-password \
    -a "$USER" -s "$keychain_service" -w 2>/dev/null || true)

if [[ -n "$token" ]]; then
    echo "A saved Ripley connection key was found. It will be reused."
else
    read_private_token
fi

if ! token_looks_valid; then
    finish_with_error "That connection key does not look valid."
fi

if ! connection_is_healthy; then
    if /usr/bin/security find-generic-password \
        -a "$USER" -s "$keychain_service" >/dev/null 2>&1; then
        echo "The saved key is no longer valid. Enter the current key."
        token=""
        read_private_token
        if ! token_looks_valid || ! connection_is_healthy; then
            finish_with_error "The Ripley service rejected that connection key."
        fi
    else
        finish_with_error "The Ripley service rejected that connection key."
    fi
fi

/bin/mkdir -p "$config_directory" "$HOME/Library/LaunchAgents" || \
    finish_with_error "The Codex configuration folders could not be created."

/usr/bin/security add-generic-password -U \
    -a "$USER" -s "$keychain_service" -w "$token" \
    -T /usr/bin/security >/dev/null 2>&1 || \
    finish_with_error "The connection key could not be saved in macOS Keychain."

temporary_config=$(/usr/bin/mktemp "${TMPDIR:-/tmp}/ripley-codex-config.XXXXXX") || \
    finish_with_error "A temporary configuration file could not be created."

if [[ -f "$config_path" ]]; then
    /bin/cp "$config_path" "$config_path.before-ripley" || \
        finish_with_error "The existing Codex configuration could not be backed up."
    remove_existing_ripley_section "$config_path" "$temporary_config" || \
        finish_with_error "The existing Codex configuration could not be read."
else
    : > "$temporary_config"
fi

if [[ -s "$temporary_config" ]]; then
    printf "\n" >> "$temporary_config"
fi
{
    printf "[mcp_servers.%s]\n" "$server_name"
    printf "url = \"%s\"\n" "$server_url"
    printf "bearer_token_env_var = \"%s\"\n" "$environment_name"
} >> "$temporary_config"

/bin/mv "$temporary_config" "$config_path" || \
    finish_with_error "The Codex configuration could not be updated."
temporary_config=""
/bin/chmod 600 "$config_path"

cat > "$helper_path" <<'HELPER'
#!/bin/zsh
token=$(/usr/bin/security find-generic-password \
    -a "$(/usr/bin/id -un)" -s "Ripley MCP API Key" -w 2>/dev/null) || exit 1
[[ -n "$token" ]] || exit 1
/bin/launchctl setenv RIPLEY_API_KEY "$token"
token=""
HELPER
/bin/chmod 700 "$helper_path" || \
    finish_with_error "The Codex environment helper could not be secured."

escaped_helper_path=$(xml_escape "$helper_path")
cat > "$launch_agent_path" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$launch_agent_label</string>
    <key>ProgramArguments</key>
    <array>
        <string>$escaped_helper_path</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
PLIST
/bin/chmod 600 "$launch_agent_path" || \
    finish_with_error "The automatic login helper could not be secured."

user_id=$(/usr/bin/id -u)
/bin/launchctl bootout "gui/$user_id" "$launch_agent_path" >/dev/null 2>&1 || true
/bin/launchctl bootstrap "gui/$user_id" "$launch_agent_path" >/dev/null 2>&1 || \
    finish_with_error "The automatic Ripley connection could not be enabled."
"$helper_path" || \
    finish_with_error "The Ripley connection key could not be loaded for Codex."

if command -v codex >/dev/null 2>&1; then
    codex mcp get "$server_name" >/dev/null 2>&1 || \
        finish_with_error "Codex could not read the new Ripley MCP registration."
fi

token=""
echo ""
echo "SUCCESS: Ripley is connected to Codex."
echo "Close Codex completely, reopen it, and start a new chat."
echo "Then say: Check my Ripley connection."
echo ""
read -r "?Press Return to close this window."
exit 0
