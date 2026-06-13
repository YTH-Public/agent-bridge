#!/usr/bin/env bash
# deploy.sh — Agent Bridge 배포 스크립트
# Windows(Git Bash) / WSL 양쪽에서 실행 가능, 환경 자동 감지.
#
# Antigravity가 "Antigravity"(구) → "Antigravity IDE"(신)로 분리되면서
# 익스텐션 디렉토리가 둘로 나뉘었다. 신버전 우선 + 기존 구버전에도 배포한다.
#   Windows: ~/.antigravity-ide/extensions (신), ~/.antigravity/extensions (구)
#   WSL:     ~/.antigravity-ide-server/extensions (신), ~/.antigravity-server/extensions (구)
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
echo "=== Agent Bridge Deploy ==="
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
    echo "$p" | sed -E 's|^/([a-zA-Z])/|/mnt/\L\1/|'
}

# WSL 사용 가능 여부 (없으면 Windows 네이티브만 배포)
wsl_available() {
    command -v wsl >/dev/null 2>&1 && MSYS_NO_PATHCONV=1 wsl -e true >/dev/null 2>&1
}

# ── 설정 ──────────────────────────────────────────────────
WSL_HOME="/home/$(MSYS_NO_PATHCONV=1 wsl whoami 2>/dev/null || echo "$USER")"
EXT_PUBLISHER="yth1133"
EXT_NAME="claude-bridge"
EXT_VERSION="0.2.0"
EXT_ID="${EXT_PUBLISHER}.${EXT_NAME}"

# 신버전(.antigravity-ide*) 우선, 그 다음 구버전(.antigravity*).
WIN_EXT_BASES=(".antigravity-ide" ".antigravity")
WSL_EXT_BASES=(".antigravity-ide-server" ".antigravity-server")

# ── Windows: skill 파일(런타임 포함) 배포 ──────────────────
deploy_windows_skill_files() {
    local win_home="$1"
    local skill="$win_home/.claude/skills/agent-bridge"

    # 네이티브 실행용: bridge.py + agy_provider.py + 런처 (WSL 없는 환경 대비)
    copy_file "$SCRIPT_DIR/src/bridge.py"       "$skill/bridge.py"       "bridge.py (Windows native)"
    copy_file "$SCRIPT_DIR/src/agy_provider.py" "$skill/agy_provider.py" "agy_provider.py (Windows native)"
    copy_file "$SCRIPT_DIR/src/run-bridge.ps1"  "$skill/run-bridge.ps1"  "run-bridge.ps1 (런처)"

    # SKILL 문서
    copy_file "$SCRIPT_DIR/src/SKILL-windows.md"       "$skill/SKILL.md"        "SKILL.md (Gemini/Windows)"
    copy_file "$SCRIPT_DIR/src/SKILL-codex-windows.md" "$skill/SKILL-codex.md"  "SKILL-codex.md (Windows)"

    copy_file "$SCRIPT_DIR/src/GEMINI.md" "$win_home/.gemini/GEMINI.md" "GEMINI.md (Windows)"
}

# ── Windows: 익스텐션 1개 베이스에 배포 ────────────────────
deploy_windows_extension_to() {
    local win_home="$1" base="$2"
    local ext_root="$win_home/$base/extensions"
    local ext_dst="$ext_root/${EXT_PUBLISHER}.${EXT_NAME}-${EXT_VERSION}-universal"

    copy_file "$SCRIPT_DIR/extension/extension.js"   "$ext_dst/extension.js"   "extension.js → $base"
    copy_file "$SCRIPT_DIR/extension/package.json"   "$ext_dst/package.json"   "package.json → $base"
    copy_file "$SCRIPT_DIR/extension/.vsixmanifest"  "$ext_dst/.vsixmanifest"  ".vsixmanifest → $base"

    # extensions.json 업데이트 (Python으로 안전 처리; 파일 없으면 새로 생성)
    local ext_json="$ext_root/extensions.json"
    local ext_rel="${EXT_PUBLISHER}.${EXT_NAME}-${EXT_VERSION}-universal"
    local ext_path="/c:/Users/${USERNAME}/${base}/extensions/${ext_rel}"
    py -c "
import json, sys, os
fp, ext_id, ext_ver, ext_path, ext_rel = sys.argv[1:6]
if os.path.exists(fp):
    with open(fp, 'r', encoding='utf-8') as f: data = json.loads(f.read())
else:
    data = []
data = [e for e in data if e.get('identifier',{}).get('id') != ext_id]
data.append({'identifier':{'id':ext_id},'version':ext_ver,'location':{'\$mid':1,'path':ext_path,'scheme':'file'},'relativeLocation':ext_rel,'metadata':{'installedTimestamp':1772243460000,'pinned':False,'source':'gallery','targetPlatform':'universal','updated':False,'private':False,'isPreReleaseVersion':False,'hasPreReleaseVersion':False}})
with open(fp, 'w', encoding='utf-8') as f: json.dump(data, f, separators=(',',':'))
print('  [OK] extensions.json 업데이트 → $base')
" "$ext_json" "$EXT_ID" "$EXT_VERSION" "$ext_path" "$ext_rel"

    # Codex 익스텐션 패치: Secondary Sidebar → Activity Bar 강제 이동
    local codex_ext_dir
    codex_ext_dir="$(ls -d "$ext_root/openai.chatgpt-"* 2>/dev/null | head -1)"
    if [ -n "$codex_ext_dir" ] && [ -f "$codex_ext_dir/package.json" ]; then
        py -c "
import json, sys
fp = sys.argv[1]
with open(fp, 'r', encoding='utf-8') as f: d = json.load(f)
changed = False
vc = d.get('contributes',{}).get('viewsContainers',{})
for item in vc.get('activitybar',[]):
    if 'codex' in item.get('id','').lower() and 'when' in item:
        del item['when']; changed = True
for item in vc.get('secondarySidebar',[]):
    if 'codex' in item.get('id','').lower() and item.get('when') != 'false':
        item['when'] = 'false'; changed = True
for vlist in d.get('contributes',{}).get('views',{}).values():
    for v in vlist:
        if 'chatgpt' in v.get('id','').lower() and 'doesNotSupportSecondarySidebar' in v.get('when',''):
            del v['when']; changed = True
if changed:
    with open(fp, 'w', encoding='utf-8') as f: json.dump(d, f, indent=2, ensure_ascii=False)
    print('  [OK] Codex 패널 → Activity Bar 패치 ($base)')
else:
    print('  [OK] Codex 패널 패치 불필요 ($base)')
" "$codex_ext_dir/package.json"
    fi
}

# ── WSL: skill 파일 배포 (via wsl) ─────────────────────────
deploy_wsl_skill_files_via_wsl() {
    local wsl_src="$1"
    local wsl_skill="$WSL_HOME/.claude/skills/agent-bridge"
    MSYS_NO_PATHCONV=1 wsl mkdir -p "$wsl_skill" "$WSL_HOME/.gemini"
    for pair in \
        "src/bridge.py:bridge.py" \
        "src/agy_provider.py:agy_provider.py" \
        "src/SKILL-wsl.md:SKILL.md" \
        "src/SKILL-codex-wsl.md:SKILL-codex.md" \
        "src/IMPROVEMENTS.md:IMPROVEMENTS.md"; do
        local s="${pair%%:*}" d="${pair##*:}"
        MSYS_NO_PATHCONV=1 wsl cp "$wsl_src/$s" "$wsl_skill/$d"
        echo "  [OK] $d (WSL)"
    done
    MSYS_NO_PATHCONV=1 wsl cp "$wsl_src/src/GEMINI.md" "$WSL_HOME/.gemini/GEMINI.md"
    echo "  [OK] GEMINI.md (WSL)"
}

# ── WSL: 익스텐션 1개 베이스에 배포 (via wsl) ──────────────
deploy_wsl_extension_to_via_wsl() {
    local wsl_src="$1" base="$2"
    local ext_root="$WSL_HOME/$base/extensions"
    # 베이스가 없으면 건너뜀 (신버전 강제 생성은 하지 않음 — IDE가 만든 곳에만)
    if ! MSYS_NO_PATHCONV=1 wsl test -d "$ext_root"; then
        echo "  [skip] $base/extensions 없음"
        return 0
    fi
    local ext_rel="${EXT_PUBLISHER}.${EXT_NAME}-${EXT_VERSION}"
    local wsl_ext="$ext_root/${ext_rel}"
    MSYS_NO_PATHCONV=1 wsl mkdir -p "$wsl_ext"
    for f in extension.js package.json .vsixmanifest; do
        MSYS_NO_PATHCONV=1 wsl cp "$wsl_src/extension/$f" "$wsl_ext/$f"
    done
    echo "  [OK] extension → $base"

    local wsl_ext_json="$ext_root/extensions.json"
    local wsl_ext_path="$ext_root/${ext_rel}"
    MSYS_NO_PATHCONV=1 wsl python3 -c '
import json, sys, os
fp, ext_id, ext_ver, ext_path, ext_rel = sys.argv[1:6]
if not os.path.exists(fp):
    data = []
else:
    with open(fp, "r", encoding="utf-8") as f: data = json.loads(f.read())
data = [e for e in data if e.get("identifier",{}).get("id") != ext_id]
data.append({"identifier":{"id":ext_id},"version":ext_ver,"location":{"$mid":1,"path":ext_path,"scheme":"file"},"relativeLocation":ext_rel,"metadata":{"isApplicationScoped":False,"isMachineScoped":True,"isBuiltin":False,"installedTimestamp":1772243460000,"pinned":True,"source":"vsix"}})
with open(fp, "w", encoding="utf-8") as f: json.dump(data, f, separators=(",",":"))
print("  [OK] extensions.json 업데이트 (WSL %s)" % os.path.basename(os.path.dirname(os.path.dirname(fp))))
' "$wsl_ext_json" "$EXT_ID" "$EXT_VERSION" "$wsl_ext_path" "$ext_rel"
}

# ── Windows (Git Bash) 배포 ───────────────────────────────
deploy_windows() {
    local win_home="$USERPROFILE"

    echo "── Windows 배포 ──"
    deploy_windows_skill_files "$win_home"

    local base deployed=0
    for base in "${WIN_EXT_BASES[@]}"; do
        if [ -d "$win_home/$base/extensions" ]; then
            deploy_windows_extension_to "$win_home" "$base"
            deployed=1
        fi
    done
    if [ "$deployed" -eq 0 ]; then
        # 하나도 없으면 신버전 경로에 생성
        deploy_windows_extension_to "$win_home" "${WIN_EXT_BASES[0]}"
    fi

    echo ""
    if ! wsl_available; then
        echo "── WSL 미감지 → Windows 네이티브만 배포 (WSL 배포 skip) ──"
        echo "   (WSL 없는 환경에서는 run-bridge.ps1이 네이티브 Python으로 실행됩니다)"
        return 0
    fi

    echo "── WSL 배포 (via wsl) ──"
    local wsl_src
    wsl_src="$(to_wsl_path "$SCRIPT_DIR")"
    deploy_wsl_skill_files_via_wsl "$wsl_src"
    for base in "${WSL_EXT_BASES[@]}"; do
        deploy_wsl_extension_to_via_wsl "$wsl_src" "$base"
    done
}

# ── WSL 네이티브 배포 ─────────────────────────────────────
deploy_wsl() {
    echo "── WSL 네이티브 배포 ──"

    local skill="$HOME/.claude/skills/agent-bridge"
    mkdir -p "$skill" "$HOME/.gemini"
    copy_file "$SCRIPT_DIR/src/bridge.py"           "$skill/bridge.py"        "bridge.py"
    copy_file "$SCRIPT_DIR/src/agy_provider.py"     "$skill/agy_provider.py"  "agy_provider.py"
    copy_file "$SCRIPT_DIR/src/SKILL-wsl.md"        "$skill/SKILL.md"         "SKILL.md (Gemini)"
    copy_file "$SCRIPT_DIR/src/SKILL-codex-wsl.md"  "$skill/SKILL-codex.md"   "SKILL-codex.md"
    copy_file "$SCRIPT_DIR/src/IMPROVEMENTS.md"     "$skill/IMPROVEMENTS.md"  "IMPROVEMENTS.md"
    copy_file "$SCRIPT_DIR/src/GEMINI.md"           "$HOME/.gemini/GEMINI.md" "GEMINI.md"

    local base
    for base in "${WSL_EXT_BASES[@]}"; do
        local ext_root="$HOME/$base/extensions"
        if [ ! -d "$ext_root" ]; then
            echo "  [skip] $base/extensions 없음"
            continue
        fi
        local ext_rel="${EXT_PUBLISHER}.${EXT_NAME}-${EXT_VERSION}"
        local ext="$ext_root/${ext_rel}"
        mkdir -p "$ext"
        for f in extension.js package.json .vsixmanifest; do
            cp "$SCRIPT_DIR/extension/$f" "$ext/$f"
        done
        echo "  [OK] extension → $base"

        # extensions.json 갱신 (via-wsl 경로와 동일하게 — 환경별 불일치 방지)
        python3 -c '
import json, sys, os
fp, ext_id, ext_ver, ext_path, ext_rel = sys.argv[1:6]
if os.path.exists(fp):
    with open(fp, "r", encoding="utf-8") as f: data = json.loads(f.read())
else:
    data = []
data = [e for e in data if e.get("identifier",{}).get("id") != ext_id]
data.append({"identifier":{"id":ext_id},"version":ext_ver,"location":{"$mid":1,"path":ext_path,"scheme":"file"},"relativeLocation":ext_rel,"metadata":{"isApplicationScoped":False,"isMachineScoped":True,"isBuiltin":False,"installedTimestamp":1772243460000,"pinned":True,"source":"vsix"}})
with open(fp, "w", encoding="utf-8") as f: json.dump(data, f, separators=(",",":"))
print("  [OK] extensions.json 업데이트 → %s" % os.path.basename(os.path.dirname(os.path.dirname(fp))))
' "$ext_root/extensions.json" "$EXT_ID" "$EXT_VERSION" "$ext" "$ext_rel"
    done
}

# ── 실행 ──────────────────────────────────────────────────
case "$ENV" in
    windows) deploy_windows ;;
    wsl)     deploy_wsl ;;
    *)
        echo "ERROR: 지원하지 않는 환경입니다: $ENV"
        exit 1
        ;;
esac

echo ""
echo "=== 배포 완료 ==="
