#!/usr/bin/env bash
set -euo pipefail

TERMINAL_MODE="auto"
TAGS="${AIWF_CAPTURE_TAGS:-codex}"
WITH_NOTE="${AIWF_CAPTURE_WITH_NOTE:-0}"
PROFILE="${AIWF_CAPTURE_PROFILE:-deep}"
LINES="${AIWF_CAPTURE_LINES:-160}"
MAX_CHARS="${AIWF_CAPTURE_MAX_CHARS:-20000}"
TITLE=""
SILENT=0

usage() {
  cat <<'EOF'
Usage:
  wf_capture_current.sh [options]

Options:
  --terminal <auto|iterm|warp|clipboard>  Capture source (default: auto)
  --tags <csv>                            Capture tags (default: codex)
  --with-note                             Generate AI note
  --profile <name>                        Model profile for note (default: deep)
  --lines <n>                             Keep last n lines for iTerm mode (default: 160)
  --max-chars <n>                         Keep max n chars (default: 20000)
  --title <text>                          Optional title
  --silent                                Disable macOS notification
  -h, --help                              Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --terminal)
      TERMINAL_MODE="${2:-}"
      shift 2
      ;;
    --tags)
      TAGS="${2:-}"
      shift 2
      ;;
    --with-note)
      WITH_NOTE=1
      shift
      ;;
    --profile)
      PROFILE="${2:-}"
      shift 2
      ;;
    --lines)
      LINES="${2:-}"
      shift 2
      ;;
    --max-chars)
      MAX_CHARS="${2:-}"
      shift 2
      ;;
    --title)
      TITLE="${2:-}"
      shift 2
      ;;
    --silent)
      SILENT=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

frontmost_app() {
  run_osascript_with_timeout 1 <<'APPLESCRIPT' || true
tell application "System Events"
  get name of first application process whose frontmost is true
end tell
APPLESCRIPT
}

run_osascript_with_timeout() {
  local timeout_sec="$1"
  shift || true
  local tmp out pid
  tmp="$(mktemp)"
  out="$(mktemp)"
  cat >"$tmp"
  osascript "$tmp" >"$out" 2>/dev/null &
  pid=$!
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [[ "$waited" -ge $((timeout_sec * 20)) ]]; then
      kill "$pid" >/dev/null 2>&1 || true
      wait "$pid" >/dev/null 2>&1 || true
      rm -f "$tmp" "$out"
      return 124
    fi
    sleep 0.05
    waited=$((waited + 1))
  done
  wait "$pid" >/dev/null 2>&1 || true
  cat "$out"
  rm -f "$tmp" "$out"
}

capture_from_iterm() {
  run_osascript_with_timeout 2 <<'APPLESCRIPT' || true
tell application "iTerm2"
  if (count of windows) is 0 then return ""
  tell current session of current window
    return contents
  end tell
end tell
APPLESCRIPT
}

trigger_warp_copy_outputs() {
  # Warp default "Copy Outputs" shortcut is Option+Shift+Command+C.
  run_osascript_with_timeout 1 <<'APPLESCRIPT' >/dev/null 2>&1 || true
tell application "Warp" to activate
delay 0.05
tell application "System Events"
  keystroke "c" using {command down, option down, shift down}
end tell
APPLESCRIPT
}

trim_text() {
  local text="$1"
  local max="$2"
  if [[ "${#text}" -le "$max" ]]; then
    printf "%s" "$text"
  else
    printf "%s" "${text:0:max}"
  fi
}

run_aiwf() {
  if command -v wf >/dev/null 2>&1; then
    wf "$@"
    return
  fi
  if command -v aiwf >/dev/null 2>&1; then
    aiwf "$@"
    return
  fi
  if python3 -c 'import importlib.util as u; import sys; sys.exit(0 if u.find_spec("aiwf") else 1)' >/dev/null 2>&1; then
    python3 -m aiwf "$@"
    return
  fi
  echo "aiwf command not found. Please run: pip install -e /Users/yangrui/code/ai" >&2
  exit 1
}

notify_ok() {
  local msg="$1"
  if [[ "$SILENT" == "1" ]]; then
    return
  fi
  osascript -e "display notification \"${msg}\" with title \"AIWF Capture\"" >/dev/null 2>&1 || true
}

source_kind="$TERMINAL_MODE"
raw=""

case "$TERMINAL_MODE" in
  iterm)
    raw="$(capture_from_iterm)"
    raw="$(printf "%s\n" "$raw" | tail -n "$LINES")"
    ;;
  warp)
    before="$(pbpaste 2>/dev/null || true)"
    trigger_warp_copy_outputs
    sleep 0.35
    after="$(pbpaste 2>/dev/null || true)"
    if [[ -n "$after" && "$after" != "$before" ]]; then
      raw="$after"
    else
      raw="$after"
    fi
    ;;
  clipboard)
    raw="$(pbpaste 2>/dev/null || true)"
    ;;
  auto)
    app="$(frontmost_app)"
    if [[ "$app" == "iTerm2" ]]; then
      source_kind="iterm"
      raw="$(capture_from_iterm)"
      raw="$(printf "%s\n" "$raw" | tail -n "$LINES")"
    elif [[ "$app" == "Warp" ]]; then
      source_kind="warp"
      before="$(pbpaste 2>/dev/null || true)"
      trigger_warp_copy_outputs
      sleep 0.35
      after="$(pbpaste 2>/dev/null || true)"
      raw="$after"
      if [[ -z "$raw" || "$raw" == "$before" ]]; then
        raw="$after"
      fi
    else
      source_kind="clipboard"
      raw="$(pbpaste 2>/dev/null || true)"
    fi
    ;;
  *)
    echo "Invalid --terminal value: $TERMINAL_MODE" >&2
    exit 2
    ;;
esac

raw="$(trim_text "$raw" "$MAX_CHARS")"
if [[ -z "${raw//[[:space:]]/}" ]]; then
  echo "No content captured from ${source_kind}. Please ensure there is output to capture." >&2
  exit 1
fi

if [[ -z "$TITLE" ]]; then
  TITLE="snapshot-$(date '+%Y%m%d-%H%M%S')-${source_kind}"
fi

cmd=(capture add --title "$TITLE" --tags "$TAGS")
if [[ "$WITH_NOTE" == "1" ]]; then
  cmd+=(--auto-note --profile "$PROFILE")
fi

printf "%s" "$raw" | run_aiwf "${cmd[@]}"
notify_ok "Saved ${source_kind} snapshot: ${TITLE}"
echo "Captured from ${source_kind}: ${TITLE}"
