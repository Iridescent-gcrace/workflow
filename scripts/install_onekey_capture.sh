#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CAPTURE_SCRIPT="${SCRIPT_DIR}/wf_capture_current.sh"

ZSHRC="${ZDOTDIR:-$HOME}/.zshrc"
SKHDRC="${HOME}/.skhdrc"
AIWF_HOME="${AIWF_HOME:-$HOME/.aiwf}"
BIN_DIR="${AIWF_HOME}/bin"
WRAPPER="${BIN_DIR}/wf-capture-current"

INSTALL_HOTKEY=1
HOTKEY="${AIWF_ONEKEY_HOTKEY:-cmd + shift - s}"
TAGS="${AIWF_CAPTURE_TAGS:-codex}"
TERMINAL_MODE="${AIWF_CAPTURE_TERMINAL:-auto}"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage:
  install_onekey_capture.sh [options]

Options:
  --no-hotkey                    Do not install global hotkey (skhd)
  --hotkey "<combo>"             skhd hotkey (default: cmd + shift - s)
  --tags <csv>                   default tags (default: codex)
  --terminal <auto|iterm|warp|clipboard>
                                 default terminal mode for capture script
  --dry-run                      preview changes only
  -h, --help                     show help

Example:
  bash scripts/install_onekey_capture.sh --hotkey "cmd + shift - s" --terminal auto
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-hotkey)
      INSTALL_HOTKEY=0
      shift
      ;;
    --hotkey)
      HOTKEY="${2:-}"
      shift 2
      ;;
    --tags)
      TAGS="${2:-}"
      shift 2
      ;;
    --terminal)
      TERMINAL_MODE="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
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

if [[ ! -f "${CAPTURE_SCRIPT}" ]]; then
  echo "capture script not found: ${CAPTURE_SCRIPT}" >&2
  exit 1
fi

ensure_block() {
  local file="$1"
  local start="$2"
  local end="$3"
  local content="$4"
  local tmp
  tmp="$(mktemp)"
  if [[ -f "$file" ]]; then
    awk -v s="$start" -v e="$end" '
      $0==s{inblock=1; next}
      $0==e{inblock=0; next}
      !inblock{print}
    ' "$file" >"$tmp"
  else
    : >"$tmp"
  fi
  {
    cat "$tmp"
    echo "$start"
    printf "%s\n" "$content"
    echo "$end"
  } >"$tmp.new"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "---- $file ----"
    cat "$tmp.new"
  else
    mkdir -p "$(dirname "$file")"
    mv "$tmp.new" "$file"
  fi
  rm -f "$tmp"
}

if [[ "$DRY_RUN" != "1" ]]; then
  mkdir -p "$BIN_DIR"
  cat >"$WRAPPER" <<EOF
#!/usr/bin/env bash
exec "${CAPTURE_SCRIPT}" --terminal "${TERMINAL_MODE}" --tags "${TAGS}" "\$@"
EOF
  chmod +x "$WRAPPER"
fi

ZSH_BLOCK=$(cat <<EOF
alias wf='aiwf'
alias wfc='${WRAPPER}'
alias wfs='${WRAPPER} --silent'
EOF
)

ensure_block "$ZSHRC" "# >>> aiwf-onekey >>>" "# <<< aiwf-onekey <<<" "$ZSH_BLOCK"

if [[ "$INSTALL_HOTKEY" == "1" ]]; then
  if ! command -v skhd >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
      if [[ "$DRY_RUN" == "1" ]]; then
        echo "[dry-run] brew install skhd"
      else
        brew install skhd >/dev/null
      fi
    else
      echo "skhd not found and brew unavailable. Skip hotkey install." >&2
      INSTALL_HOTKEY=0
    fi
  fi
fi

if [[ "$INSTALL_HOTKEY" == "1" ]]; then
  SKHD_BLOCK="${HOTKEY} : ${WRAPPER}"
  ensure_block "$SKHDRC" "# >>> aiwf-onekey >>>" "# <<< aiwf-onekey <<<" "$SKHD_BLOCK"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] brew services restart skhd"
  else
    if command -v brew >/dev/null 2>&1; then
      brew services restart skhd >/dev/null || brew services start skhd >/dev/null || true
    fi
  fi
fi

if [[ "$DRY_RUN" != "1" ]]; then
  # Best effort: ensure CLI is installed for current user.
  if ! command -v wf >/dev/null 2>&1 && ! command -v aiwf >/dev/null 2>&1; then
    python3 -m pip install -e "${PROJECT_ROOT}" >/dev/null || true
  fi
fi

echo
echo "Install complete."
echo "1) Reload shell: source ${ZSHRC}"
echo "2) Run once: wfc --terminal ${TERMINAL_MODE}"
if [[ "$INSTALL_HOTKEY" == "1" ]]; then
  echo "3) Global hotkey ready: ${HOTKEY}"
  echo "4) If hotkey does not respond, enable Accessibility for skhd in macOS settings."
else
  echo "3) Hotkey skipped. You can run manually: wfc"
fi
echo
echo "Tips:"
echo "- iTerm: wfc 默认直接抓当前 session 尾部输出"
echo "- Warp: wfc 默认触发 Copy Outputs 后沉淀（依赖默认 Warp 复制快捷键）"

