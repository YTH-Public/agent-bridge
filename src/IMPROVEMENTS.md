# Agent Bridge 개선사항

## 의사결정 기록 (ADR)

### ADR-1. agy CLI 전환 vs 파일 브릿지 유지 (2026-06-13)
- **맥락**: Gemini CLI → Antigravity CLI(`agy`) 전환(2026-06-18 구 CLI 종료). "파일 브릿지를 버리고 agy 직접 호출로 갈아탈까?"
- **조사 결과**:
  - `agy -p`는 non-TTY(서브프로세스/파이프/리다이렉트)에서 stdout에 응답을 안 씀 = 문서화된 버그(antigravity-cli Issue #76/#115). 직접 재현됨.
  - 우회는 비공식 경로 `~/.gemini/antigravity-cli/brain/<conv-id>/.../transcript.jsonl` 읽기뿐 → 업데이트 취약.
  - 채팅패널과 agy는 같은 구독 할당량 풀 공유. agy는 요청당 토큰 오버헤드가 커 할당량을 더 빨리 소진(개선 중이나 여전).
  - agy `-p`는 승인 게이트 없이 도구 자동 실행(보안 리스크). 실제로 사소한 질문에도 워크스페이스를 `list_dir`함.
  - 약관상 본인 구독으로 공식 agy 바이너리를 본인 개발용 구동 + 자기 transcript 읽기는 위반 아님.
- **결정 (Claude + Codex 독립 합의)**: **파일 브릿지를 핵심으로 유지**하고, **agy는 선택적 provider로 추가**. 안정적 stdout/공식 출력 API·권한 제어·할당량 영향·fallback이 확인되면 그때 Gemini 경로만 단계적 전환.
- **구현**: `bridge-config.json`의 `gemini.mode`로 `file-bridge`(기본) / `agy`(실험적) 선택. `agy_provider.py`가 transcript 우회 + 실패 시 file-bridge 폴백 안내.

## 해결됨

### 10. 전송 모드 선택 (file-bridge / agy) + 런타임 자동 선택
- **해결일**: 2026-06-13
- **해결**:
  - `bridge-config.json` 도입, `init --mode` / `config --gemini-mode`로 모드 선택. init이 두 모드를 안내.
  - `agy_provider.py` 신규 — `agy -p` 호출 후 transcript.jsonl에서 최종 응답 추출(stdout 버그 우회), `--sandbox` 기본 적용.
  - `run-bridge.ps1` 런처 — WSL 우선, 없으면 네이티브(py→python→uv), agy 모드는 항상 네이티브. → **WSL 없는 Windows 환경 지원**.

### 11. Antigravity IDE 분리 대응 (익스텐션 경로)
- **해결일**: 2026-06-13
- **증상**: `Antigravity` → `Antigravity IDE`로 제품이 분리되며 익스텐션 디렉토리가 `.antigravity-ide`(신) / `.antigravity`(구)로 나뉨. deploy.sh가 구 경로에만 배포해 새 IDE가 못 읽음.
- **해결**: deploy.sh가 신·구 베이스(Windows `.antigravity-ide`/`.antigravity`, WSL `.antigravity-ide-server`/`.antigravity-server`) 중 **존재하는 곳 모두에 배포**.

### 12. Codex 전송 한글 인코딩 깨짐
- **해결일**: 2026-06-13
- **증상**: Codex에 한글 지시 전송 시 인코딩이 깨짐. WSL 로케일·인자전달·파일은 모두 UTF-8 정상 → 원인은 익스텐션 인라인 채널(`chatgpt.implementTodo` comment).
- **해결**: Codex는 **항상 본문을 UTF-8 detail 파일로 분리**하고, 트리거(=익스텐션에 넘기는 값)에는 **ASCII 포인터만** 담는다. 한글이 인라인 채널을 거치지 않음.



### 5. WSL Remote 지원 + extensions.json 안정화
- **해결일**: 2026-03-13
- **증상**: WSL Remote에서 Claude Bridge 익스텐션이 로드 안 됨, deploy.sh의 sed가 extensions.json을 손상시킴
- **해결**:
  - `package.json`에 `extensionKind: ["workspace"]` 추가 → WSL Remote에서 익스텐션 실행
  - deploy.sh의 extensions.json 업데이트를 sed → Python(`json` 모듈)으로 교체
  - WSL extensions.json 깨진 것 Python으로 복구

### 6. 병렬 전송 + status 커맨드
- **해결일**: 2026-03-13
- **증상**: Gemini와 Codex 동시 전송 시 하나가 블로킹되어 순차 실행됨
- **해결**:
  - `send` (논블로킹) + `status` (양쪽 응답 확인) 패턴 도입
  - SKILL 파일에 병렬 전송 가이드 추가

### 7. Gemini/Codex 규칙 분리
- **해결일**: 2026-03-13
- **증상**: Codex가 Gemini 전용 bridge-output.md를 읽고 "마크다운 저장이 내 역할"로 착각
- **해결**:
  - `BRIDGE_OUTPUT_RULE` → Gemini 전용 명시
  - `CODEX_OUTPUT_RULE` 신규 추가
  - `cmd_init()`에서 `.agent/rules/codex-output.md` 도 생성

### 9. Windows에서 Codex 패널 안 보이는 문제
- **해결일**: 2026-03-16
- **증상**: Windows Antigravity에서 Codex 익스텐션이 설치·활성화 상태인데 패널이 Activity Bar에 안 뜸. WSL Remote에서는 정상 표시
- **원인**: Codex 익스텐션의 `viewsContainers`에 `when: "chatgpt.doesNotSupportSecondarySidebar"` 조건이 있어서, Secondary Sidebar 지원하는 Antigravity에서는 우측 Secondary Sidebar에만 등록됨. Gemini Agent 패널과 겹쳐 보이지 않음
- **해결**: deploy.sh에서 Codex 익스텐션 package.json의 `when` 조건을 자동 제거 → 항상 좌측 Activity Bar에 표시
- **주의**: Codex 익스텐션 업데이트 시 패치가 초기화됨 → `bash deploy.sh` 재실행 필요
- **미해결**: Codex에 메시지 전송 시 `chatgpt.implementTodo`가 내부적으로 우측 Secondary Sidebar에 빈 Codex 패널을 여는 부작용 있음 (Windows만). Gemini에 다시 말걸면 Gemini 패널로 복원됨. 실사용에 지장 없음

### 8. 한글 별칭 지원
- **해결일**: 2026-03-13
- **해결**: SKILL description에 "제미나이", "코덱스", "챗지피티" 별칭 추가

### 1. Antigravity 에러 시 자동 재시도 없음
- **발견일**: 2026-02-24
- **해결일**: 2026-02-28
- **증상**: Gemini에게 메시지 전송 후 Antigravity 측에서 에러 발생 → 응답 생성 중단
- **해결**:
  - **bridge.py `ask` 모드**: `--retries` 옵션 추가. 타임아웃(기본 3분) 내에 응답 없으면 "continue" trigger 자동 전송, 최대 3회 재시도
  - **extension.js**: `from-gemini/*.md` 감시 + 응답 타임아웃 시 `sendPromptToAgentPanel('continue')` 직접 전송, 최대 3회 재시도
  - 두 레이어가 독립 동작: `ask` 사용 시 Claude가 감시, `send` 사용 시 extension이 감시

## 미해결 이슈 (Sprint Backlog)

### 2. Gemini 응답 완료 확인 자동화
- **발견일**: 2026-02-28
- **증상**: Gemini가 응답을 from-gemini/에 저장하지 않으면 Claude 측에서 완료 여부를 확인할 방법이 없음. 결국 사용자에게 Antigravity 채팅 패널을 직접 확인하라고 요청하게 됨
- **현재 상태**: from-gemini/*.md 파일 감시에만 의존. Gemini가 파일을 안 만들면 감지 불가
- **개선 방안**:
  - Antigravity가 agent 상태 API를 노출하면 활용 (현재 미지원)
  - Gemini 규칙(.agent/rules/)에 "반드시 파일 저장" 강제 지시 강화
  - extension.js에서 UI 상태 변화 간접 감지 방법 조사

### 3. Gemini 권한 설정 자동화
- **발견일**: 2026-02-28
- **증상**: Antigravity에서 Gemini 에이전트의 파일 읽기/쓰기 권한을 수동으로 설정해야 함. 새 프로젝트를 열 때마다 권한 허용을 수동 클릭해야 하는 불편함
- **현재 상태**: extension.js의 auto-approve가 `acceptAgentStep` 등을 폴링하지만, 초기 권한 설정(프로젝트별 파일 접근 허용)은 별도로 수동 진행 필요
- **개선 방안**:
  - Antigravity 설정에서 글로벌 auto-approve 옵션이 있는지 조사
  - .antigravity/ 또는 workspace 설정 파일에서 권한 사전 설정 가능 여부 확인
  - extension.js에서 workspace 열릴 때 자동 권한 부여 명령어 탐색

### 4. Gemini 코드 리뷰 결과 수집 및 반영 워크플로우
- **발견일**: 2026-02-28
- **증상**: Gemini에게 코드 리뷰를 요청하면 응답이 올 때까지 Claude가 대기하거나 사용자가 수동 확인해야 함. 리뷰 결과를 Claude가 자동으로 읽고 반영하는 end-to-end 워크플로우가 없음
- **개선 방안**:
  - `ask` 모드로 리뷰 요청 → 응답 수신 → Claude가 자동으로 읽고 개선사항 적용하는 파이프라인 구축
  - SKILL.md에 "리뷰 후 반영" 워크플로우 패턴 문서화
