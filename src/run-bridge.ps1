<#
run-bridge.ps1 — bridge.py 런타임 자동 선택 런처 (Windows)

목적: WSL이 없는 Windows 환경에서도 bridge.py를 실행할 수 있게 한다.
런타임 우선순위:
  1) -Native 강제 또는 agy 모드  → 네이티브 Windows Python (py → python → uv run)
  2) WSL 사용 가능               → WSL의 ~/.claude/skills/agent-bridge/bridge.py
  3) 그 외                        → 네이티브 Windows Python

agy 모드(Antigravity CLI 직접 호출)는 agy.exe와 transcript(~/.gemini)가 모두
Windows 쪽에 있으므로 반드시 네이티브로 실행해야 한다. WSL에서 실행하면
Path.home()이 달라 응답을 못 읽는다.

사용:
  run-bridge.ps1 [-Native] [-WslDir <wsl경로>] -- <bridge.py 인자들>
예:
  run-bridge.ps1 -- --dir "C:\proj" init
  run-bridge.ps1 -Native -- --dir "C:\proj" --target gemini send "안녕"
#>
[CmdletBinding()]
param(
    [switch]$Native,
    [string]$WslDir,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$BridgeArgs
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BridgePy  = Join-Path $ScriptDir 'bridge.py'

# '--' 구분자 제거
if ($BridgeArgs.Count -gt 0 -and $BridgeArgs[0] -eq '--') {
    $BridgeArgs = $BridgeArgs[1..($BridgeArgs.Count - 1)]
}

function Test-WslAvailable {
    try {
        $null = & wsl.exe -e true 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Invoke-Native {
    # 네이티브 Windows Python 해석: py → python → uv run
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { & py -3 $BridgePy @BridgeArgs; exit $LASTEXITCODE }

    $python = Get-Command python -ErrorAction SilentlyContinue
    # WindowsApps 스토어 스텁(실행 시 안내만 출력) 회피: 경로에 WindowsApps 포함되면 건너뜀
    if ($python -and ($python.Source -notmatch 'WindowsApps')) {
        & python $BridgePy @BridgeArgs; exit $LASTEXITCODE
    }

    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        # bridge.py는 순수 stdlib이므로 의존성 설치 불필요. uv가 Python을 제공.
        & uv run --python 3.12 python $BridgePy @BridgeArgs; exit $LASTEXITCODE
    }

    Write-Error "네이티브 Python을 찾지 못했습니다 (py / python / uv 모두 없음). Python 3 또는 uv를 설치하세요."
    exit 1
}

function Invoke-Wsl {
    # WSL HOME을 조회해 절대 경로로 만든다.
    # (`wsl -e python3 ~/...`는 셸을 안 거쳐 '~'가 확장되지 않으므로 절대경로 필수)
    $wslHome = (& wsl.exe -e printenv HOME 2>$null)
    if ($wslHome) { $wslHome = ($wslHome | Select-Object -First 1).Trim() }
    if (-not $wslHome) { $wslHome = '/root' }
    $wslBridge = "$wslHome/.claude/skills/agent-bridge/bridge.py"

    # --dir 경로(Windows)를 WSL 경로로 변환
    $converted = @()
    $i = 0
    while ($i -lt $BridgeArgs.Count) {
        $a = $BridgeArgs[$i]
        if ($a -eq '--dir' -and ($i + 1) -lt $BridgeArgs.Count) {
            $converted += $a
            $converted += (Convert-ToWslPath $BridgeArgs[$i + 1])
            $i += 2; continue
        }
        $converted += $a; $i++
    }
    & wsl.exe -e python3 $wslBridge @converted
    exit $LASTEXITCODE
}

function Convert-ToWslPath([string]$p) {
    if ($p -match '^[A-Za-z]:[\\/]') {
        $drive = $p.Substring(0, 1).ToLower()
        $rest  = $p.Substring(2) -replace '\\', '/'
        return "/mnt/$drive$rest"
    }
    return $p
}

# agy 모드 감지: config가 agy면 네이티브 강제
function Test-AgyMode {
    $dir = $null
    for ($i = 0; $i -lt $BridgeArgs.Count; $i++) {
        if ($BridgeArgs[$i] -eq '--dir' -and ($i + 1) -lt $BridgeArgs.Count) {
            $dir = $BridgeArgs[$i + 1]; break
        }
    }
    # --dir 생략 시 현재 디렉터리 기준 (bridge.py의 기본 동작과 일치)
    if (-not $dir) { $dir = (Get-Location).Path }
    $cfg = Join-Path $dir 'bridge\bridge-config.json'
    if (-not (Test-Path $cfg)) { return $false }
    try {
        $json = Get-Content $cfg -Raw | ConvertFrom-Json
        return ($json.gemini.mode -eq 'agy')
    } catch { return $false }
}

if ($Native -or (Test-AgyMode)) { Invoke-Native }
elseif (Test-WslAvailable)      { Invoke-Wsl }
else                            { Invoke-Native }
