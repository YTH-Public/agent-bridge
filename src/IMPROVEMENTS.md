# Gemini Bridge 개선사항

## 해결됨

### 1. Antigravity 에러 시 자동 재시도 없음
- **발견일**: 2026-02-24
- **해결일**: 2026-02-28
- **증상**: Gemini에게 메시지 전송 후 Antigravity 측에서 에러 발생 → 응답 생성 중단
- **해결**:
  - **bridge.py `ask` 모드**: `--retries` 옵션 추가. 타임아웃(기본 3분) 내에 응답 없으면 "continue" trigger 자동 전송, 최대 3회 재시도
  - **extension.js**: `from-gemini/*.md` 감시 + 응답 타임아웃 시 `sendPromptToAgentPanel('continue')` 직접 전송, 최대 3회 재시도
  - 두 레이어가 독립 동작: `ask` 사용 시 Claude가 감시, `send` 사용 시 extension이 감시

## 미해결 이슈

(현재 없음)
