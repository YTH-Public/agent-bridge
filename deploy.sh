#!/usr/bin/env bash
# deploy.sh — Gemini Bridge 배포 스크립트
# Windows(Git Bash) / WSL 양쪽에서 실행 가능, 환경 자동 감지.
#
# Usage: bash deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 환경 감지 ──────────────────────────────────────────────
detect_env() {
    if grep -qiE '(microsoft|wsl)' /proc/version 2>/dev/null; then
        echo "wsl"
    elif [[ "$OSTYPE" == msys* || "$OSTYPE" == mingw* || "$OSTYPE" == cygwin* ]]; then
        echo "windows"
    else
        echo "linux"
    fi
}

ENV="$(detect_env)"
echo "=== Gemini Bridge Deploy ==="
echo "Environment: $ENV"
echo "Source dir:   $SCRIPT_DIR"
echo ""

# ── 헬퍼 ─────────────────────────────────────────────────
copy_file() {
    local src="$1" dst="$2" label="$3"
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    echo "  [OK] $label"
    echo "       $dst"
}

# Git Bash MSYS 경로 (/d/foo) → WSL 경로 (/mnt/d/foo) 변환
to_wsl_path() {
    local p="$1"
    # /d/project → /mnt/d/project
    echo "$p" | sed -E 's|^/([a-zA-Z])/|/mnt/\L\1/|'
}

# ── 설정 (환경에 맞게 수정) ────────────────────────────────
# WSL 사용자 홈 디렉토리 (Windows에서 WSL 배포 시 사용)
WSL_HOME="/home/$(MSYS_NO_PATHCONV=1 wsl whoami 2>/dev/null || echo '$USER')"
# 익스텐션 publisher.name
EXT_PUBLISHER="yth1133"
EXT_NAME="claude-bridge"
EXT_VERSION="0.1.0"

# ── Windows (Git Bash) 배포 ───────────────────────────────
deploy_windows() {
    local win_home="$USERPROFILE"

    echo "── Windows 배포 ──"

    # SKILL-windows.md → ~/.claude/skills/gemini-bridge/SKILL.md
    copy_file "$SCRIPT_DIR/src/SKILL-windows.md" \
              "$win_home/.claude/skills/gemini-bridge/SKILL.md" \
              "SKILL.md (Windows)"

    # GEMINI.md → ~/.gemini/GEMINI.md
    copy_file "$SCRIPT_DIR/src/GEMINI.md" \
              "$win_home/.gemini/GEMINI.md" \
              "GEMINI.md (Windows)"

    # extension → ~/.antigravity/extensions/${EXT_PUBLISHER}.${EXT_NAME}-${EXT_VERSION}-universal/
    local ext_dst="$win_home/.antigravity/extensions/${EXT_PUBLISHER}.${EXT_NAME}-${EXT_VERSION}-universal"
    copy_file "$SCRIPT_DIR/extension/extension.js" "$ext_dst/extension.js" "extension.js (Windows)"
    copy_file "$SCRIPT_DIR/extension/package.json"  "$ext_dst/package.json"  "package.json (Windows)"
    copy_file "$SCRIPT_DIR/extension/.vsixmanifest"  "$ext_dst/.vsixmanifest"  ".vsixmanifest (Windows)"

    echo ""
    echo "── WSL 배포 (via wsl) ──"

    # MSYS 경로를 WSL 경로로 변환
    local wsl_src
    wsl_src="$(to_wsl_path "$SCRIPT_DIR")"

    # bridge.py → WSL ~/.claude/skills/gemini-bridge/bridge.py
    local wsl_skill="$WSL_HOME/.claude/skills/gemini-bridge"
    MSYS_NO_PATHCONV=1 wsl mkdir -p "$wsl_skill"
    MSYS_NO_PATHCONV=1 wsl cp "$wsl_src/src/bridge.py" "$wsl_skill/bridge.py"
    echo "  [OK] bridge.py (WSL)"
    echo "       $wsl_skill/bridge.py"

    # SKILL-wsl.md → WSL ~/.claude/skills/gemini-bridge/SKILL.md
    MSYS_NO_PATHCONV=1 wsl cp "$wsl_src/src/SKILL-wsl.md" "$wsl_skill/SKILL.md"
    echo "  [OK] SKILL.md (WSL)"
    echo "       $wsl_skill/SKILL.md"

    # IMPROVEMENTS.md → WSL ~/.claude/skills/gemini-bridge/IMPROVEMENTS.md
    MSYS_NO_PATHCONV=1 wsl cp "$wsl_src/src/IMPROVEMENTS.md" "$wsl_skill/IMPROVEMENTS.md"
    echo "  [OK] IMPROVEMENTS.md (WSL)"
    echo "       $wsl_skill/IMPROVEMENTS.md"

    # GEMINI.md → WSL ~/.gemini/GEMINI.md
    MSYS_NO_PATHCONV=1 wsl mkdir -p "$WSL_HOME/.gemini"
    MSYS_NO_PATHCONV=1 wsl cp "$wsl_src/src/GEMINI.md" "$WSL_HOME/.gemini/GEMINI.md"
    echo "  [OK] GEMINI.md (WSL)"
    echo "       $WSL_HOME/.gemini/GEMINI.md"

    # extension → WSL ~/.antigravity-server/extensions/${EXT_PUBLISHER}.${EXT_NAME}-${EXT_VERSION}/
    local wsl_ext="$WSL_HOME/.antigravity-server/extensions/${EXT_PUBLISHER}.${EXT_NAME}-${EXT_VERSION}"
    MSYS_NO_PATHCONV=1 wsl mkdir -p "$wsl_ext"
    for f in extension.js package.json .vsixmanifest; do
        MSYS_NO_PATHCONV=1 wsl cp "$wsl_src/extension/$f" "$wsl_ext/$f"
        echo "  [OK] $f (WSL)"
        echo "       $wsl_ext/$f"
    done
}

# ── WSL 네이티브 배포 ─────────────────────────────────────
deploy_wsl() {
    echo "── WSL 네이티브 배포 ──"

    local skill="$HOME/.claude/skills/gemini-bridge"
    mkdir -p "$skill"

    # bridge.py
    copy_file "$SCRIPT_DIR/src/bridge.py" "$skill/bridge.py" "bridge.py"

    # SKILL-wsl.md → SKILL.md
    copy_file "$SCRIPT_DIR/src/SKILL-wsl.md" "$skill/SKILL.md" "SKILL.md"

    # IMPROVEMENTS.md
    copy_file "$SCRIPT_DIR/src/IMPROVEMENTS.md" "$skill/IMPROVEMENTS.md" "IMPROVEMENTS.md"

    # GEMINI.md
    mkdir -p "$HOME/.gemini"
    copy_file "$SCRIPT_DIR/src/GEMINI.md" "$HOME/.gemini/GEMINI.md" "GEMINI.md"

    # extension
    local ext="$HOME/.antigravity-server/extensions/${EXT_PUBLISHER}.${EXT_NAME}-${EXT_VERSION}"
    mkdir -p "$ext"
    for f in extension.js package.json .vsixmanifest; do
        copy_file "$SCRIPT_DIR/extension/$f" "$ext/$f" "$f"
    done
}

# ── 실행 ──────────────────────────────────────────────────
case "$ENV" in
    windows)
        deploy_windows
        ;;
    wsl)
        deploy_wsl
        ;;
    *)
        echo "ERROR: 지원하지 않는 환경입니다: $ENV"
        exit 1
        ;;
esac

echo ""
echo "=== 배포 완료 ==="
