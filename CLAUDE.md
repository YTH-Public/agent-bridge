# Gemini Bridge

Claude Code와 Antigravity IDE(Gemini)를 연결하는 파일 기반 브릿지.

## 프로젝트 구조

```
gemini-bridge/
├── deploy.sh              # 배포 (WSL + Windows 자동 감지)
├── src/
│   ├── bridge.py          # CLI (순수 Python3 stdlib, WSL에서 실행)
│   ├── SKILL-wsl.md       # WSL Claude Code용 스킬
│   ├── SKILL-windows.md   # Windows Claude Code용 스킬
│   ├── GEMINI.md          # Gemini 글로벌 규칙
│   └── IMPROVEMENTS.md    # 개선 이력 + Sprint Backlog
└── extension/
    ├── extension.js       # Antigravity 익스텐션
    ├── package.json
    └── .vsixmanifest
```

## 개발 규칙

### 배포
- 파일 수정 후 반드시 `bash deploy.sh` 실행하여 양쪽(WSL + Windows) 동기화
- deploy.sh는 Git Bash(Windows)와 WSL 양쪽에서 실행 가능

### 코드 스타일
- bridge.py: 순수 Python3 stdlib만 사용 (pip/uv 의존성 금지)
- extension.js: Antigravity(VS Code 호환) 익스텐션 API 사용
- 사용자명/경로 하드코딩 금지 — `~`, `$HOME`, `wsl whoami` 등으로 동적 해결

### WSL 관련
- Git Bash에서 WSL 호출 시 반드시 `MSYS_NO_PATHCONV=1` 접두사 사용
- `~` 경로 확장이 필요하면 `wsl -e bash -c '...'` 패턴 사용
- Windows 경로 → WSL 변환: `D:\x` → `/mnt/d/x`

### Git
- 브랜치: main
- 커밋 메시지: 한국어, 간결하게

### 문서
- README.md: 합니다 존댓말 톤
- IMPROVEMENTS.md: 해결된 이슈 / 미해결 Sprint Backlog 구분 유지
- SKILL-wsl.md와 SKILL-windows.md: 동일 기능이지만 실행 경로가 다름 — 기능 변경 시 양쪽 모두 수정

## 테스트

변경 후 확인 사항:
1. `bash deploy.sh` 성공
2. Windows에서 `/gemini 테스트` → trigger 파일 생성 확인
3. Antigravity에서 trigger 감지 → Gemini 채팅 전달 확인
