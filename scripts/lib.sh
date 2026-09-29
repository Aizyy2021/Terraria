# Shared helpers for the scripts in this folder. Source it, don't run it.

# Loads .env into the environment without executing it, so values with
# spaces or special characters (e.g. DISCORD_TITLE=Terraria Server) are safe.
load_env() {
  local line key value
  [[ -f .env ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    value="${value%"${value##*[![:space:]]}"}"          # trim trailing spaces
    if [[ "$value" =~ ^\'(.*)\'$ || "$value" =~ ^\"(.*)\"$ ]]; then
      value="${BASH_REMATCH[1]}"
    fi
    export "$key=$value"
  done < .env
}
