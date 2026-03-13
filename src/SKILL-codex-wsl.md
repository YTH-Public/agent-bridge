---
name: codex
description: "Codex(ChatGPT/챗지피티)에게 메시지를 보내거나 응답을 읽는 브릿지 명령. send/ask/read/list/init 지원. 예: /codex 이 함수 리팩토링해줘, /codex read, /codex init. '코덱스', '챗지피티', 'ChatGPT'도 이 명령을 사용."
---

# Codex Bridge Skill

Antigravity IDE의 Codex(ChatGPT)와 통신하는 브릿지. 어떤 프로젝트에서든 사용 가능.

## 사용법

```
/codex init                         # 현재 프로젝트에 bridge 구조 초기화 (codex-context.md 자동 생성)
/codex <메시지>                     # Codex에게 메시지 전송
/codex --topic <토픽> <메시지>      # 토픽 지정하여 전송
/codex ask <메시지>                 # 전송 + 응답 대기
/codex read                         # 최신 Codex 응답 읽기
/codex list                         # 최근 응답 목록
/codex search <키워드>              # 키워드로 검색
```

## 핵심 규칙

- 모든 명령은 **현재 프로젝트의 bridge/ 디렉토리**를 사용한다.
- `--dir` 옵션으로 프로젝트 경로를 지정한다. Claude Code의 작업 디렉토리를 사용.
- `--target codex` 옵션으로 Codex 모드 지정.
- 스크립트 경로: `~/.claude/skills/agent-bridge/bridge.py`
- **순수 Python3 stdlib** — uv나 pip 의존성 없음.
- Codex 전송은 `chatgpt.implementTodo` 명령을 통해 이루어진다.

## Codex에게 맡기면 좋은 작업

| 작업 | 예시 |
|------|------|
| 코드 리팩토링 | "이 함수를 더 효율적으로 리팩토링해줘" |
| 코드 리뷰 | "이 PR 코드 리뷰해줘" |
| 버그 수정 | "이 에러 원인 찾아서 수정해줘" |
| 테스트 작성 | "이 모듈의 유닛 테스트 작성해줘" |
| 문서화 | "이 API의 JSDoc 작성해줘" |
| 일반 코딩 | 위에 해당 안 되는 코딩 요청 |

## 메시지 포맷

Claude는 전송 시 아래 형식으로 메시지를 구성한다:

```
[PROJECT: <project-name>]

<사용자 요청 또는 Claude가 정리한 요청>

응답은 bridge/from-codex/ 디렉토리에 마크다운 파일로 저장해주세요.

---
[CONTEXT]
<bridge/codex-context.md 내용 자동 삽입>
```

**구현 방법**: Claude가 `send`/`ask` 실행 전에:
1. `bridge/codex-context.md` 읽기
2. 위 포맷으로 조합하여 전송

### 긴 메시지 자동 파일 분리

bridge.py는 메시지가 **500자 초과**이면 자동으로:
1. 상세 내용을 `bridge/from-claude/{timestamp}_{topic}-detail.md`로 저장
2. 트리거에는 **파일 경로만** 포함하여 Codex에게 "이 파일을 읽어라"고 전달

## 프로젝트 컨텍스트 (codex-context.md)

각 프로젝트의 `bridge/codex-context.md`에 프로젝트별 정보가 담긴다.
`/codex init` 시 **CLAUDE.md를 읽고 자동 생성**한다.

포함 내용:
- 프로젝트명, 설명
- 기술 스택
- Codex 주 역할 (이 프로젝트에서 뭘 맡길지)

### init 후속 절차 (Claude가 수행)

1. `python3 bridge.py --dir <path> init` 실행 (디렉토리 + 스켈레톤 생성)
2. 프로젝트의 CLAUDE.md 읽기
3. (있으면) package.json, pyproject.toml 등 읽기
4. 파악한 정보로 `bridge/codex-context.md` 내용 채우기 (Write tool)

## 실행 방법

### 초기화 (init) — 새 프로젝트에서 최초 1회

```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<프로젝트절대경로>" init
```

이 명령이 생성하는 파일:
- `bridge/from-gemini/.gitkeep`
- `bridge/from-codex/.gitkeep`
- `bridge/from-claude/.gitkeep`
- `bridge/gemini-context.md` (스켈레톤)
- `bridge/codex-context.md` (스켈레톤)
- `.agent/rules/bridge-output.md`

### 전송 (send) — 기본 동작

인자가 `init/read/list/search/ask`가 아닐 때:

```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --target codex --dir "<프로젝트절대경로>" send "<메시지>" --topic "<토픽>"
```

### 전송 + 대기 (ask)

```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --target codex --dir "<프로젝트절대경로>" ask "<메시지>" --topic "<토픽>" --timeout 600 --retries 3
```

### 읽기 (read)

```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<프로젝트절대경로>" --source codex latest
```

### 목록 (list)

```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<프로젝트절대경로>" --source codex list
```

### 검색 (search)

```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<프로젝트절대경로>" --source codex search "<키워드>"
```

## 새 프로젝트에서 Codex 사용하기

1. `/codex init` 실행 → bridge 디렉토리 + codex-context.md 자동 생성
2. Antigravity에서 해당 프로젝트를 열고 Codex 익스텐션 활성화
3. `/codex 요청` 으로 Codex에게 요청

## 병렬 전송 (Gemini + Codex 동시)

사용자가 Gemini와 Codex 양쪽에 동시에 보내달라고 하면, **`ask` 대신 `send`를 사용**한다.
`ask`는 응답을 기다리며 블로킹하므로 병렬 전송이 불가능하다.

### 절차

1. **Gemini에 send** (즉시 리턴):
```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<경로>" send "<메시지>" --topic "<토픽>"
```

2. **Codex에 send** (즉시 리턴):
```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --target codex --dir "<경로>" send "<메시지>" --topic "<토픽>"
```

3. **양쪽 응답 상태 확인** (둘 다 올 때까지 반복):
```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<경로>" status --after "<전송시각ISO>"
```
- exit code 0 = 양쪽 모두 응답 완료
- exit code 1 = 아직 대기 중인 응답 있음

4. **응답 읽기**:
```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<경로>" --source gemini latest
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<경로>" --source codex latest
```

## 주의사항

- bridge/ 디렉토리가 없으면 init 이외의 명령은 에러가 난다.
- `.codex-trigger` 파일이 생성되면 Antigravity 익스텐션이 감지하여 `chatgpt.implementTodo`로 Codex에게 전달한다.
- Codex는 코딩 에이전트로 동작하므로 파일 읽기/쓰기/터미널 명령을 자체적으로 수행한다.
- codex-context.md가 없어도 전송은 가능하지만, 컨텍스트가 포함되면 응답 품질이 높아진다.
