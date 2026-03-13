---
name: gemini
description: "Gemini(제미나이)에게 메시지를 보내거나 응답을 읽는 브릿지 명령. send/ask/read/list/init 지원. 예: /gemini 단어 데이터 생성해줘, /gemini read, /gemini init. '제미나이'도 이 명령을 사용."
---

# Gemini Bridge Skill

Antigravity IDE의 Gemini와 통신하는 브릿지. 어떤 프로젝트에서든 사용 가능.

## 사용법

```
/gemini init                         # 현재 프로젝트에 bridge 구조 초기화 (gemini-context.md 자동 생성)
/gemini <메시지>                     # Gemini에게 메시지 전송
/gemini --topic <토픽> <메시지>      # 토픽 지정하여 전송
/gemini ask <메시지>                 # 전송 + 응답 대기
/gemini read                         # 최신 Gemini 응답 읽기
/gemini list                         # 최근 응답 목록
/gemini search <키워드>              # 키워드로 검색
```

## 핵심 규칙

- 모든 명령은 **현재 프로젝트의 bridge/ 디렉토리**를 사용한다.
- `--dir` 옵션으로 프로젝트 경로를 지정한다. Claude Code의 작업 디렉토리를 사용.
- 스크립트 경로: `~/.claude/skills/agent-bridge/bridge.py`
- **순수 Python3 stdlib** — uv나 pip 의존성 없음.

## 태스크 카테고리 (자동 라우팅)

메시지를 보낼 때, Claude는 내용을 분석해서 적절한 태스크 카테고리를 판단하고 `[TASK: <category>]` 헤더를 자동으로 붙여 보낸다.

### 카테고리 판단 규칙

| 카테고리 | 키워드/상황 | Gemini에게 기대하는 것 |
|---------|-----------|---------------------|
| `design-review` | 디자인 리뷰, UI 피드백, 레이아웃 평가 | 스크린샷/코드 기반 UI/UX 개선 의견 |
| `design-create` | 디자인 만들어줘, 목업, 스타일링 제안 | Tailwind 클래스, HTML 목업, 컬러/레이아웃 시안 |
| `web-research` | 조사해줘, 트렌드, 비교, 최신 | 웹 검색 기반 조사 결과 정리 |
| `image-generate` | 이미지, 아이콘, OG 이미지, 로고 | 이미지 생성 (Gemini Imagen) |
| `verify-check` | 확인해줘, 접근성, SEO 체크, 테스트 | 브라우저에서 실제 확인 결과 |
| `general` | 위에 해당 안 되는 일반 요청 | 자유 응답 |

### 메시지 포맷

Claude는 전송 시 아래 형식으로 메시지를 구성한다:

```
[TASK: <category>]
[PROJECT: <project-name>]

<사용자 요청 또는 Claude가 정리한 요청>

---
[CONTEXT]
<bridge/gemini-context.md 내용 자동 삽입>
```

**구현 방법**: Claude가 `send`/`ask` 실행 전에:
1. 메시지 내용으로 카테고리 판단
2. `bridge/gemini-context.md` 읽기
3. 위 포맷으로 조합하여 전송

### 긴 메시지 자동 파일 분리

bridge.py는 메시지가 **500자 초과**이면 자동으로:
1. 상세 내용을 `bridge/from-claude/{timestamp}_{topic}-detail.md`로 저장
2. 트리거에는 **파일 경로만** 포함하여 Gemini에게 "이 파일을 읽어라"고 전달

이렇게 하면 Antigravity의 Gemini 에이전트가 긴 메시지로 크래시하는 문제를 방지한다.
Claude도 긴 요청을 보낼 때 이 패턴을 따른다 — 메시지를 직접 넣지 말고 bridge.py에 넘기면 자동 처리됨.

## 프로젝트 컨텍스트 (gemini-context.md)

각 프로젝트의 `bridge/gemini-context.md`에 프로젝트별 정보가 담긴다.
`/gemini init` 시 **CLAUDE.md를 읽고 자동 생성**한다.

포함 내용:
- 프로젝트명, 설명
- 기술 스택
- 디자인 시스템 (색상, 폰트, 컴포넌트 등)
- Gemini 주 역할 (이 프로젝트에서 뭘 맡길지)

### init 후속 절차 (Claude가 수행)

1. `python3 bridge.py --dir <path> init` 실행 (디렉토리 + 스켈레톤 생성)
2. 프로젝트의 CLAUDE.md 읽기
3. (있으면) package.json, pyproject.toml 등 읽기
4. 파악한 정보로 `bridge/gemini-context.md` 내용 채우기 (Write tool)

## 실행 방법

### 초기화 (init) — 새 프로젝트에서 최초 1회

```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<프로젝트절대경로>" init
```

이 명령이 생성하는 파일:
- `bridge/from-gemini/.gitkeep`
- `bridge/from-claude/.gitkeep`
- `bridge/gemini-context.md` (스켈레톤 — Claude가 이후 채움)
- `.agent/rules/bridge-output.md`

### 전송 (send) — 기본 동작

인자가 `init/read/list/search/ask`가 아닐 때:

```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<프로젝트절대경로>" send "<메시지>" --topic "<토픽>"
```

- `<프로젝트절대경로>`: 현재 Claude Code의 작업 디렉토리 절대경로
- `<메시지>`: 사용자가 전달한 전체 메시지 (Claude가 태스크 헤더 + 컨텍스트를 붙여서 전달)
- `<토픽>`: 메시지에서 핵심 키워드를 kebab-case로 추출

### 전송 + 대기 (ask)

```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<프로젝트절대경로>" ask "<메시지>" --topic "<토픽>" --timeout 600 --retries 3
```

- `--timeout`: 응답 대기 시간 (초, 기본 180)
- `--retries`: 타임아웃 시 "continue" 자동 재시도 횟수 (기본 3)

**자동 재시도 동작**: 타임아웃 내에 `bridge/from-gemini/`에 새 `.md` 파일이 안 나타나면, 자동으로 "continue" trigger를 전송하고 다시 대기한다. Gemini가 에러로 멈췄을 때 수동 개입 없이 복구된다.

Gemini 응답을 기다려야 하는 경우 `send` 대신 `ask`를 사용한다. `send`는 fire-and-forget이고, `ask`는 응답이 올 때까지 대기 + 자동 재시도한다.

### 읽기 (read)

```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<프로젝트절대경로>" --source gemini latest
```

### 목록 (list)

```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<프로젝트절대경로>" --source gemini list
```

### 검색 (search)

```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<프로젝트절대경로>" --source gemini search "<키워드>"
```

## 새 프로젝트에서 Gemini 사용하기

1. `/gemini init` 실행 → bridge 디렉토리 + Antigravity 규칙 + gemini-context.md 자동 생성
2. Antigravity에서 해당 프로젝트를 열기
3. `/gemini 질문` 으로 Gemini에게 요청 (태스크 카테고리 자동 판단)

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
- `--after`에 전송 시각을 넣으면 그 이후에 생성된 파일만 확인

4. **응답 읽기**:
```bash
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<경로>" --source gemini latest
python3 ~/.claude/skills/agent-bridge/bridge.py --dir "<경로>" --source codex latest
```

## 주의사항

- bridge/ 디렉토리가 없으면 init 이외의 명령은 에러가 난다.
- Antigravity에서 해당 프로젝트를 열어야 `.agent/rules/bridge-output.md` 규칙이 적용된다.
- trigger 파일이 생성되면 Antigravity 익스텐션이 감지하여 Gemini에게 자동 전달한다.
- gemini-context.md가 없어도 전송은 가능하지만, 컨텍스트가 포함되면 Gemini 응답 품질이 높아진다.
