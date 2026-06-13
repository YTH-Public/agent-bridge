# Agent Bridge

Claude Code와 Antigravity IDE(Gemini + Codex)를 연결하는 파일 기반 브릿지.

## 프로젝트 구조

```
agent-bridge/
├── deploy.sh                  # 배포 (WSL + Windows 자동 감지, .antigravity-ide 신경로 대응)
├── src/
│   ├── bridge.py              # CLI (순수 Python3 stdlib)
│   ├── agy_provider.py        # agy 모드 어댑터 (Antigravity CLI 직접 호출, transcript 읽기)
│   ├── run-bridge.ps1         # Windows 런처 (WSL→네이티브→uv 런타임 자동 선택)
│   ├── SKILL-wsl.md           # WSL Claude Code용 Gemini 스킬
│   ├── SKILL-windows.md       # Windows Claude Code용 Gemini 스킬
│   ├── SKILL-codex-wsl.md     # WSL Claude Code용 Codex 스킬
│   ├── SKILL-codex-windows.md # Windows Claude Code용 Codex 스킬
│   ├── GEMINI.md              # Gemini 글로벌 규칙
│   └── IMPROVEMENTS.md        # 개선 이력 + Sprint Backlog
└── extension/
    ├── extension.js           # Antigravity 익스텐션 (Gemini + Codex)
    ├── package.json           # extensionKind: ["workspace"] (WSL Remote 지원)
    └── .vsixmanifest
```

## 전송 모드 (file-bridge vs agy)

`bridge/bridge-config.json`이 Gemini 전송 모드를 결정한다 (`init` 시 생성).

- **file-bridge** (기본·권장) — Antigravity IDE 채팅패널 경유. 트리거 파일 → 익스텐션 → 채팅패널. 할당량 효율·안정·승인 게이트.
- **agy** (실험적) — `agy_provider.py`가 `agy -p`를 직접 호출. `agy -p`는 non-TTY에서 stdout이 비는 버그(Issue #76/#115)가 있어, `~/.gemini/antigravity-cli/brain/<conv-id>/.../transcript.jsonl`에서 최종 응답을 읽는다. **Windows 네이티브 전용**(agy.exe·transcript가 Windows 쪽). 비공식 경로 의존이라 깨지면 file-bridge로 폴백 안내.
- Codex는 항상 file-bridge (전용 CLI 없음).
- 변경: `bridge.py config --gemini-mode <file-bridge|agy>`

## 런타임 선택 (WSL 우선, 없으면 네이티브)

`run-bridge.ps1`이 자동 선택: agy 모드 → 네이티브 / WSL 가능 → WSL / WSL 없음 → 네이티브(py→python→uv). bridge.py는 순수 stdlib라 uv는 Python 제공용으로만 쓴다.

## 핵심 개념

### bridge.py 커맨드
- `init` — bridge/ 디렉토리 + `.agent/rules/` 규칙 파일 생성
- `send` — 트리거 파일 생성 (논블로킹, fire-and-forget)
- `ask` — 트리거 생성 + 응답 대기 (블로킹)
- `status` — Gemini/Codex 양쪽 응답 상태 확인 (병렬 전송 후 사용)
- `latest` / `list` / `search` — 응답 읽기

### 규칙 파일 (init이 생성)
- `.agent/rules/bridge-output.md` — Gemini 전용 (Codex가 착각하지 않도록 분리)
- `.agent/rules/codex-output.md` — Codex 전용

### 병렬 전송
Gemini + Codex 동시 전송 시 `ask` 대신 `send` 사용 → `status`로 양쪽 응답 확인

## 개발 규칙

### 배포
- 파일 수정 후 반드시 `bash deploy.sh` 실행하여 양쪽(WSL + Windows) 동기화
- deploy.sh는 Git Bash(Windows)와 WSL 양쪽에서 실행 가능
- extensions.json 업데이트는 Python(`json` 모듈)으로 처리 (sed 사용 금지 — JSON 손상 방지)
- **익스텐션 경로 분리**: Antigravity가 `Antigravity`(구) → `Antigravity IDE`(신)로 나뉘며 익스텐션 디렉토리도 둘이 됨. deploy.sh는 **존재하는 모든 베이스에 배포**한다.
  - Windows: `~/.antigravity-ide/extensions`(신), `~/.antigravity/extensions`(구)
  - WSL: `~/.antigravity-ide-server/extensions`(신), `~/.antigravity-server/extensions`(구)
- deploy.sh는 bridge.py·agy_provider.py·run-bridge.ps1을 **Windows skill 디렉토리에도** 복사한다 (WSL 없는 환경/agy 모드 네이티브 실행 대비).

### 코드 스타일
- bridge.py: 순수 Python3 stdlib만 사용 (pip/uv 의존성 금지)
- extension.js: Antigravity(VS Code 호환) 익스텐션 API 사용
- 사용자명/경로 하드코딩 금지 — `~`, `$HOME`, `wsl whoami` 등으로 동적 해결

### WSL 관련
- Git Bash에서 WSL 호출 시 반드시 `MSYS_NO_PATHCONV=1` 접두사 사용
- `~` 경로 확장이 필요하면 `wsl -e bash -c '...'` 패턴 사용
- Windows 경로 → WSL 변환: `D:\x` → `/mnt/d/x`
- WSL Remote 지원: `extensionKind: ["workspace"]`로 익스텐션이 WSL 쪽에서 실행됨

### Git
- 브랜치: main
- 커밋 메시지: 한국어, 간결하게

### 문서
- README.md: 합니다 존댓말 톤
- IMPROVEMENTS.md: 해결된 이슈 / 미해결 Sprint Backlog 구분 유지
- SKILL-wsl.md와 SKILL-windows.md: 동일 기능이지만 실행 경로가 다름 — 기능 변경 시 양쪽 모두 수정
- SKILL-codex-wsl.md와 SKILL-codex-windows.md: Codex 스킬도 동일 — 기능 변경 시 양쪽 모두 수정
- SKILL description에 한글 별칭 포함 (제미나이/코덱스/챗지피티)

## 테스트

변경 후 확인 사항:
1. `bash deploy.sh` 성공
2. `python3 bridge.py --dir /tmp/test init` → bridge-output.md + codex-output.md + bridge-config.json 생성 확인
3. `config --gemini-mode agy` → bridge-config.json 반영 + agy 실행파일 탐지 출력
4. Windows에서 `/gemini 테스트`(file-bridge) → .trigger 파일 생성 확인
5. Windows에서 `/codex 한글 테스트` → **항상 detail 파일 분리 + .codex-trigger엔 ASCII 포인터만** (한글 인코딩 보호)
6. Antigravity IDE에서 trigger 감지 → Gemini/Codex 채팅 전달 확인
7. WSL Remote에서 Claude Bridge 상태바 표시 확인
8. (agy 모드) Windows 네이티브에서 `send` → from-gemini/에 응답 .md 저장 확인
9. (WSL 없는 환경 가정) `run-bridge.ps1 -- --dir <경로> init` → 네이티브 Python으로 실행 확인
