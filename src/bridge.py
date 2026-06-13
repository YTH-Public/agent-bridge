#!/usr/bin/env python3
"""AI Bridge — Gemini + Codex 전역 CLI.

어떤 프로젝트에서든 bridge/ 디렉토리를 통해 Gemini/Codex와 통신한다.
순수 Python stdlib만 사용 (외부 의존성 없음).

사용법:
    python3 bridge.py --dir /path/to/project init
    python3 bridge.py --dir /path/to/project send "메시지"
    python3 bridge.py --dir /path/to/project --target codex send "메시지"
    python3 bridge.py --dir /path/to/project --source gemini latest
    python3 bridge.py --dir /path/to/project --source codex latest
    python3 bridge.py --dir /path/to/project ask "질문" --timeout 600
    python3 bridge.py --dir /path/to/project --target codex ask "질문"
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

BRIDGE_OUTPUT_RULE = """\
# Bridge Output Rule — Gemini 전용

> **이 규칙은 Gemini 에이전트 전용입니다.** Codex는 `codex-output.md`를 참조하세요.

## 1. 응답 저장 (모든 작업의 기본)

모든 실질적 응답은 `bridge/from-gemini/`에 마크다운 파일로 저장합니다.
이것은 리뷰든, 코드 구현이든, 조사든 **어떤 작업이든 항상** 수행하는 기본 동작입니다.

### 파일명 규칙
```
YYYY-MM-DD_HH-MM_주제요약.md
```
- 타임스탬프는 현재 시각 기준
- 주제요약은 영문 kebab-case, 최대 5단어
- 예: `2026-02-24_14-30_quadratic-formula-proof.md`

### 파일 형식
```markdown
---
timestamp: "YYYY-MM-DDTHH:MM:SS"
topic: "주제 한줄 요약 (한국어)"
tags: [관련, 태그, 목록]
query: "원래 질문 요약"
task: "<태스크 카테고리>"
source: gemini
---

# 제목

(응답 본문)
```

## 2. 소스 코드 수정 — 명시적 요청이 있을 때만

### 중요: 언제 코드를 수정하고 언제 하지 않는가

| 요청 유형 | 예시 | 코드 수정 | 마크다운 저장 |
|----------|------|----------|-------------|
| **구현/수정 요청** | "구현해줘", "수정해줘", "리팩토링해줘", "만들어줘", "바꿔줘" | O (1순위) | O (작업 요약) |
| **리뷰/분석 요청** | "리뷰해줘", "이 구조 어떻게 생각해?", "문제점 분석해줘" | X | O (분석 결과) |
| **의견/제안 요청** | "어떻게 하면 좋을까?", "설계 방향 제안해줘" | X | O (의견/제안) |
| **조사 요청** | "이 라이브러리 비교해줘", "트렌드 조사해줘" | X | O (조사 결과) |

- **명시적 구현 지시가 있을 때만** 소스 파일을 직접 수정합니다.
- **구현을 요청받지 않았는데 자의적으로 소스 파일을 수정하지 마세요.**
- 애매한 경우: 코드를 수정하지 않고, 마크다운에 "이렇게 바꾸면 어떨까" 제안 형태로 작성합니다.

### 코드 수정이 포함된 작업의 흐름
1. **소스 파일 직접 수정** (이것이 1순위)
2. `bridge/from-gemini/`에 **작업 요약** 마크다운 저장 (무엇을 왜 어떻게 바꿨는지)

### 코드 수정이 없는 작업의 흐름
1. `bridge/from-gemini/`에 응답 마크다운 저장 (이것만으로 완료)

## 3. 태스크 카테고리별 응답 가이드

Claude가 `[TASK: <category>]` 헤더를 붙여 보내면, 해당 카테고리에 맞는 응답을 작성합니다.

| 카테고리 | 응답에 포함할 것 | 코드 수정 여부 |
|---------|----------------|--------------|
| `design-review` | 개선 포인트, before/after 비교, Tailwind 클래스 제안 | 명시 요청 시만 |
| `design-create` | HTML/Tailwind 목업 코드, 색상 팔레트, 레이아웃 구조도 | 명시 요청 시만 |
| `web-research` | 출처 URL, 비교표, 핵심 요약, 적용 권장사항 | 안 함 |
| `image-generate` | 생성된 이미지를 bridge/from-gemini/에 저장 | 안 함 |
| `verify-check` | 체크 항목별 pass/fail, 스크린샷, 개선 필요 사항 | 안 함 |
| `implement` | 구현 결과 요약 + 변경 파일 목록 | **함** |
| `general` | 자유 형식 | 명시 요청 시만 |

## 4. 프로젝트 컨텍스트

`bridge/gemini-context.md`에 이 프로젝트의 기술 스택, 디자인 시스템, Gemini 역할이 정의되어 있습니다.
요청에 `[CONTEXT]` 섹션이 포함되면 참고하여 프로젝트에 맞는 응답을 작성합니다.

## 5. 기타 규칙
1. 단순 인사나 확인 응답은 파일 저장 불필요
2. 수식 → LaTeX 형식
3. 코드 → 적절한 언어 태그의 코드 블록
4. 파일 저장 후 사용자에게 저장 완료를 알립니다

## 목적
이 파일들은 Claude Code가 읽어서 활용합니다. Gemini의 응답을 Claude가 참조할 수 있도록 하는 브릿지 역할입니다.
"""

CODEX_OUTPUT_RULE = """\
# Bridge Output Rule — Codex 전용

> **이 규칙은 Codex 에이전트 전용입니다.** Gemini는 `bridge-output.md`를 참조하세요.

## 1. 응답 저장 (모든 작업의 기본)

모든 실질적 응답은 `bridge/from-codex/`에 마크다운 파일로 저장합니다.
이것은 리뷰든, 코드 구현이든, 조사든 **어떤 작업이든 항상** 수행하는 기본 동작입니다.

### 파일명 규칙
```
YYYY-MM-DD_HH-MM_주제요약.md
```
- 타임스탬프는 현재 시각 기준
- 주제요약은 영문 kebab-case, 최대 5단어

### 파일 형식
```markdown
---
timestamp: "YYYY-MM-DDTHH:MM:SS"
topic: "주제 한줄 요약 (한국어)"
tags: [관련, 태그, 목록]
query: "원래 질문 요약"
task: "<태스크 카테고리>"
source: codex
---

# 제목

(응답 본문)
```

## 2. 소스 코드 수정 — 명시적 요청이 있을 때만

### 중요: 언제 코드를 수정하고 언제 하지 않는가

| 요청 유형 | 예시 | 코드 수정 | 마크다운 저장 |
|----------|------|----------|-------------|
| **구현/수정 요청** | "구현해줘", "수정해줘", "리팩토링해줘", "만들어줘", "바꿔줘" | O (1순위) | O (작업 요약) |
| **리뷰/분석 요청** | "리뷰해줘", "이 구조 어떻게 생각해?", "문제점 분석해줘" | X | O (분석 결과) |
| **의견/제안 요청** | "어떻게 하면 좋을까?", "설계 방향 제안해줘" | X | O (의견/제안) |
| **조사 요청** | "이 라이브러리 비교해줘", "트렌드 조사해줘" | X | O (조사 결과) |

- **명시적 구현 지시가 있을 때만** 소스 파일을 직접 수정합니다.
- **구현을 요청받지 않았는데 자의적으로 소스 파일을 수정하지 마세요.**
- 애매한 경우: 코드를 수정하지 않고, 마크다운에 "이렇게 바꾸면 어떨까" 제안 형태로 작성합니다.

### 코드 수정이 포함된 작업의 흐름
1. **소스 파일 직접 수정** (이것이 1순위 — 마크다운 저장이 본업이 아닙니다)
2. `bridge/from-codex/`에 **작업 요약** 마크다운 저장 (무엇을 왜 어떻게 바꿨는지, 변경 파일 목록)

### 코드 수정이 없는 작업의 흐름
1. `bridge/from-codex/`에 응답 마크다운 저장 (이것만으로 완료)

## 3. 프로젝트 컨텍스트

`bridge/gemini-context.md` 또는 `bridge/codex-context.md`에 프로젝트 정보가 있습니다.
요청에 `[CONTEXT]` 섹션이 포함되면 참고하여 프로젝트에 맞는 응답을 작성합니다.

## 4. 기타 규칙
1. 단순 인사나 확인 응답은 파일 저장 불필요
2. 코드 → 적절한 언어 태그의 코드 블록
3. 파일 저장 후 사용자에게 저장 완료를 알립니다

## 목적
이 파일들은 Claude Code가 읽어서 활용합니다. Codex의 응답을 Claude가 참조할 수 있도록 하는 브릿지 역할입니다.
"""

GEMINI_CONTEXT_SKELETON = """\
# Gemini Context — {project_name}

> 이 파일은 Claude가 Gemini에게 요청할 때 자동으로 포함되는 프로젝트 컨텍스트입니다.
> `/gemini init` 시 자동 생성되며, 프로젝트가 발전하면 Claude가 자동 업데이트합니다.

## 프로젝트 개요
<!-- Claude가 CLAUDE.md를 읽고 채움 -->

## 기술 스택
<!-- Claude가 CLAUDE.md / package.json / pyproject.toml 읽고 채움 -->

## 디자인 시스템
<!-- 색상, 폰트, 컴포넌트 라이브러리 등 -->

## Gemini 주 역할
<!-- 이 프로젝트에서 Gemini에게 주로 맡길 작업 -->

## 현재 상태
<!-- 최근 Sprint, 진행 중인 작업 -->
"""

CODEX_CONTEXT_SKELETON = """\
# Codex Context — {project_name}

> 이 파일은 Claude가 Codex에게 요청할 때 자동으로 포함되는 프로젝트 컨텍스트입니다.
> `/codex init` 시 자동 생성되며, 프로젝트가 발전하면 Claude가 자동 업데이트합니다.

## 프로젝트 개요
<!-- Claude가 CLAUDE.md를 읽고 채움 -->

## 기술 스택
<!-- Claude가 CLAUDE.md / package.json / pyproject.toml 읽고 채움 -->

## Codex 주 역할
<!-- 이 프로젝트에서 Codex에게 주로 맡길 작업 -->

## 현재 상태
<!-- 최근 Sprint, 진행 중인 작업 -->
"""


def resolve_bridge_dir(args_dir: Optional[str]) -> Path:
    """프로젝트의 bridge/ 디렉토리를 찾는다."""
    if args_dir:
        base = Path(args_dir)
    else:
        base = Path(os.getcwd())

    bridge = base / "bridge"
    if not bridge.exists():
        print(f"⚠️  bridge/ 디렉토리가 없습니다: {bridge}")
        print("   `python3 bridge.py --dir <프로젝트경로> init` 으로 초기화하세요.")
        raise SystemExit(1)
    return bridge


def get_sources(bridge: Path) -> dict:
    return {
        "gemini": bridge / "from-gemini",
        "codex": bridge / "from-codex",
        "claude": bridge / "from-claude",
    }


def get_md_files(bridge: Path, source: str = "all") -> list:
    sources = get_sources(bridge)
    if source == "all":
        dirs = [sources["gemini"], sources["codex"], sources["claude"]]
    else:
        dirs = [sources[source]]

    files = []
    for d in dirs:
        if d and d.exists():
            files.extend(d.glob("*.md"))

    return sorted(files, key=lambda f: f.name, reverse=True)


# === 모드 설정 (file-bridge vs agy) ===

CONFIG_FILENAME = "bridge-config.json"
VALID_GEMINI_MODES = ("file-bridge", "agy")


def _config_path(bridge: Path) -> Path:
    return bridge / CONFIG_FILENAME


def load_config(bridge: Path) -> dict:
    """bridge-config.json을 읽는다. 없으면 기본값(file-bridge)."""
    fp = _config_path(bridge)
    default = {"gemini": {"mode": "file-bridge"}, "codex": {"mode": "file-bridge"}}
    if not fp.exists():
        return default
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default
    # 누락 키 보정
    data.setdefault("gemini", {}).setdefault("mode", "file-bridge")
    data.setdefault("codex", {}).setdefault("mode", "file-bridge")
    return data


def save_config(bridge: Path, config: dict) -> None:
    _config_path(bridge).write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def get_mode(bridge: Path, target: str) -> str:
    """대상(gemini/codex)의 전송 모드를 반환한다. codex는 항상 file-bridge."""
    if target == "codex":
        return "file-bridge"  # Codex는 전용 CLI가 없으므로 항상 파일 브릿지
    return load_config(bridge).get("gemini", {}).get("mode", "file-bridge")


_TOPIC_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_topic(topic: Optional[str]) -> str:
    """topic을 안전한 파일명 slug로 정규화한다.

    경로 구분자/`..`/Windows 금지 문자/과도한 길이를 차단한다.
    """
    t = (topic or "").strip()
    t = _TOPIC_RE.sub("-", t)          # 허용 외 문자 → 하이픈
    t = t.strip("-._")                  # 양끝 구두점 제거
    t = t[:50]                          # 길이 제한
    return t or "message"


# === Commands ===

def cmd_init(args, bridge_dir_override=None):
    """프로젝트에 bridge 구조를 초기화한다."""
    base = Path(args.dir) if args.dir else Path(os.getcwd())

    bridge = base / "bridge"
    from_gemini = bridge / "from-gemini"
    from_codex = bridge / "from-codex"
    from_claude = bridge / "from-claude"
    agent_rules = base / ".agent" / "rules"

    from_gemini.mkdir(parents=True, exist_ok=True)
    from_codex.mkdir(parents=True, exist_ok=True)
    from_claude.mkdir(parents=True, exist_ok=True)
    agent_rules.mkdir(parents=True, exist_ok=True)

    # .gitkeep
    for d in [from_gemini, from_codex, from_claude]:
        gitkeep = d / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

    # bridge-output.md 규칙 — Gemini 전용 (항상 최신으로 덮어쓰기)
    rule_file = agent_rules / "bridge-output.md"
    rule_file.write_text(BRIDGE_OUTPUT_RULE, encoding="utf-8")
    print(f"  {'업데이트' if rule_file.exists() else '생성'}: {rule_file.relative_to(base)}")

    # codex-output.md 규칙 — Codex 전용 (항상 최신으로 덮어쓰기)
    codex_rule_file = agent_rules / "codex-output.md"
    codex_rule_file.write_text(CODEX_OUTPUT_RULE, encoding="utf-8")
    print(f"  {'업데이트' if codex_rule_file.exists() else '생성'}: {codex_rule_file.relative_to(base)}")

    # gemini-context.md 스켈레톤 (없을 때만 생성)
    project_name = base.name
    gemini_ctx = bridge / "gemini-context.md"
    if not gemini_ctx.exists():
        gemini_ctx.write_text(
            GEMINI_CONTEXT_SKELETON.replace("{project_name}", project_name),
            encoding="utf-8",
        )
        print(f"  생성: {gemini_ctx.relative_to(base)}")
    else:
        print(f"  이미 존재: {gemini_ctx.relative_to(base)}")

    # codex-context.md 스켈레톤 (없을 때만 생성)
    codex_ctx = bridge / "codex-context.md"
    if not codex_ctx.exists():
        codex_ctx.write_text(
            CODEX_CONTEXT_SKELETON.replace("{project_name}", project_name),
            encoding="utf-8",
        )
        print(f"  생성: {codex_ctx.relative_to(base)}")
    else:
        print(f"  이미 존재: {codex_ctx.relative_to(base)}")

    # bridge-config.json — Gemini 전송 모드 (file-bridge | agy)
    requested_mode = getattr(args, "mode", None) or "file-bridge"
    if requested_mode not in VALID_GEMINI_MODES:
        print(f"⚠️  알 수 없는 모드 '{requested_mode}' → file-bridge로 설정")
        requested_mode = "file-bridge"
    config = load_config(bridge)
    config["gemini"]["mode"] = requested_mode
    save_config(bridge, config)
    print(f"  생성: {_config_path(bridge).relative_to(base)} (gemini.mode={requested_mode})")

    print(f"✅ Bridge 초기화 완료: {base}")
    print(f"   bridge/from-gemini/       — Gemini 응답 저장소")
    print(f"   bridge/from-codex/        — Codex 응답 저장소")
    print(f"   bridge/from-claude/       — Claude 요청 저장소 (.trigger / .codex-trigger)")
    print(f"   bridge/gemini-context.md  — 프로젝트 컨텍스트 (Gemini용)")
    print(f"   bridge/codex-context.md   — 프로젝트 컨텍스트 (Codex용)")
    print(f"   bridge/{CONFIG_FILENAME}  — 전송 모드 설정")
    print(f"   .agent/rules/bridge-output.md — Gemini 규칙")
    print(f"   .agent/rules/codex-output.md  — Codex 규칙")
    print()
    print(f"📡 Gemini 전송 모드: {requested_mode}")
    print(f"   • file-bridge — Antigravity IDE 채팅패널 경유 (권장: 할당량 효율·안정적·승인 게이트)")
    print(f"   • agy         — Antigravity CLI 직접 호출 (실험적: 빠르지만 할당량 소모·비공식 경로 의존)")
    print(f"   전환: python3 bridge.py --dir <경로> config --gemini-mode <file-bridge|agy>")


def cmd_latest(args):
    bridge = resolve_bridge_dir(args.dir)
    files = get_md_files(bridge, args.source)
    if not files:
        print("bridge에 파일이 없습니다.")
        return

    latest = files[0]
    print(f"=== {latest.relative_to(bridge)} ===\n")
    print(latest.read_text(encoding="utf-8"))


def cmd_list(args):
    bridge = resolve_bridge_dir(args.dir)
    files = get_md_files(bridge, args.source)
    if not files:
        print("bridge에 파일이 없습니다.")
        return

    count = min(args.n, len(files))
    print(f"최근 {count}개 파일:\n")
    for f in files[:count]:
        rel = f.relative_to(bridge)
        topic = ""
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("topic:"):
                topic = line.split(":", 1)[1].strip().strip('"')
                break
        suffix = f"  — {topic}" if topic else ""
        print(f"  {rel}{suffix}")


def cmd_search(args):
    bridge = resolve_bridge_dir(args.dir)
    keyword = args.keyword.lower()
    files = get_md_files(bridge, args.source)
    if not files:
        print("bridge에 파일이 없습니다.")
        return

    matches = []
    for f in files:
        content = f.read_text(encoding="utf-8")
        if keyword in content.lower():
            matches.append(f)

    if not matches:
        print(f"'{args.keyword}'에 대한 결과가 없습니다.")
        return

    print(f"'{args.keyword}' 검색 결과: {len(matches)}건\n")
    for f in matches:
        print(f"  {f.relative_to(bridge)}")

    print(f"\n=== 가장 최근 매칭: {matches[0].relative_to(bridge)} ===\n")
    print(matches[0].read_text(encoding="utf-8"))


MAX_TRIGGER_LENGTH = 500  # 트리거 메시지 최대 길이 (이 이상이면 파일로 분리)


def _send_via_agy(args, bridge, topic, message):
    """Gemini agy 모드: agy CLI로 직접 실행하고 응답을 from-gemini/에 저장한다."""
    try:
        import agy_provider
    except ImportError:
        print("❌ agy_provider 모듈을 찾을 수 없습니다. file-bridge 모드를 사용하세요.")
        raise SystemExit(1)

    sources = get_sources(bridge)
    response_dir = sources["gemini"]
    config = load_config(bridge)
    agy_cfg = config.get("agy", {})
    workdir = str(bridge.parent)  # 프로젝트 루트에서 실행 (conv-id 매핑 기준)

    print(f"🤖 agy 직접 호출 (mode=agy)... 워크스페이스: {workdir}")
    try:
        out = agy_provider.run(
            message,
            response_dir,
            topic=topic,
            workdir=workdir,
            model=agy_cfg.get("model"),
            sandbox=agy_cfg.get("sandbox", True),
        )
    except agy_provider.AgyError as e:
        print(f"❌ agy 실행 실패: {e}")
        raise SystemExit(1)

    print(f"📨 Gemini(agy) 응답 저장: {out.relative_to(bridge)}\n")
    print(out.read_text(encoding="utf-8"))


def cmd_send(args):
    target = getattr(args, "target", "gemini")
    bridge = resolve_bridge_dir(args.dir)
    topic = safe_topic(args.topic)
    message = args.message

    # Gemini + agy 모드 → 파일 트리거 대신 agy CLI 직접 호출
    if target == "gemini" and get_mode(bridge, "gemini") == "agy":
        _send_via_agy(args, bridge, topic, message)
        return

    sources = get_sources(bridge)
    from_claude = sources["claude"]
    from_claude.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")
    file_ts = now.strftime("%Y-%m-%d_%H-%M")

    # Codex용 응답 파일 경로 생성
    response_file = ""
    if target == "codex":
        response_filename = f"{file_ts}_{topic}.md"
        response_file = f"bridge/from-codex/{response_filename}"

    response_dir_name = "from-codex" if target == "codex" else "from-gemini"

    # 파일 분리 조건:
    #   - Codex는 항상 파일 분리 (한글을 익스텐션 인라인 채널에 안 태움 → 인코딩 깨짐 방지)
    #   - Gemini는 MAX_TRIGGER_LENGTH 초과 시에만
    split_to_file = (target == "codex") or (len(message) > MAX_TRIGGER_LENGTH)

    if split_to_file:
        detail_filename = f"{file_ts}_{topic}-detail.md"
        detail_path = from_claude / detail_filename
        detail_path.write_text(
            f"---\ntimestamp: \"{timestamp}\"\ntopic: \"{topic}\"\nsource: claude\ntarget: {target}\n---\n\n{message}\n",
            encoding="utf-8",
        )
        rel_detail = f"bridge/from-claude/{detail_filename}"
        if target == "codex":
            # ASCII 전용 포인터 — 한글 본문은 UTF-8 파일(rel_detail)에만 존재
            trigger_message = (
                f"Read the request file and follow it exactly: {rel_detail}\n"
                f"Save your response to bridge/{response_dir_name}/ ."
            )
        else:
            trigger_message = (
                f"아래 파일에 상세 요청이 있습니다. 파일을 읽고 그 안의 요청대로 처리해주세요.\n\n"
                f"📄 파일 경로: {rel_detail}\n\n"
                f"응답은 bridge/{response_dir_name}/ 에 저장해주세요."
            )
        print(f"📄 파일 분리: {rel_detail} ({len(message)}자)")
    else:
        trigger_message = message

    # 트리거 확장자: .trigger (Gemini) / .codex-trigger (Codex)
    ext = ".codex-trigger" if target == "codex" else ".trigger"
    filename = f"{file_ts}_{topic}{ext}"
    trigger_path = from_claude / filename

    content = f"""---
timestamp: "{timestamp}"
topic: "{topic}"
source: claude
target: {target}
response_file: "{response_file}"
---

{trigger_message}
"""

    trigger_path.write_text(content, encoding="utf-8")
    label = "Codex" if target == "codex" else "Gemini"
    print(f"✅ {label} Trigger 생성: {trigger_path.relative_to(bridge)}")
    print(f"   메시지: {trigger_message[:200]}{'...' if len(trigger_message) > 200 else ''}")


def _send_continue(args):
    """'continue' 메시지를 trigger로 전송한다."""
    bridge = resolve_bridge_dir(args.dir)
    sources = get_sources(bridge)
    from_claude = sources["claude"]
    from_claude.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")
    file_ts = now.strftime("%Y-%m-%d_%H-%M")

    filename = f"{file_ts}_continue.trigger"
    trigger_path = from_claude / filename
    content = f"""---
timestamp: "{timestamp}"
topic: "continue"
source: claude
---

continue
"""
    trigger_path.write_text(content, encoding="utf-8")
    print(f"🔄 Continue trigger 전송: {trigger_path.relative_to(bridge)}")


def cmd_ask(args):
    target = getattr(args, "target", "gemini")
    bridge = resolve_bridge_dir(args.dir)

    # Gemini + agy 모드는 동기 실행 — cmd_send가 이미 응답을 저장·출력함
    if target == "gemini" and get_mode(bridge, "gemini") == "agy":
        cmd_send(args)
        return

    sources = get_sources(bridge)
    response_dir = sources[target]
    before_files = set(response_dir.glob("*.md")) if response_dir.exists() else set()

    cmd_send(args)

    label = "Codex" if target == "codex" else "Gemini"
    max_retries = args.retries
    for attempt in range(max_retries + 1):
        if attempt > 0:
            if target == "gemini":
                print(f"\n🔄 응답 없음 → continue 전송 ({attempt}/{max_retries})")
                _send_continue(args)
            else:
                print(f"\n⏳ {label} 아직 작업 중... ({attempt}/{max_retries})")

        print(f"\n⏳ {label} 응답 대기 중 (최대 {args.timeout}초)...")
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            time.sleep(3)
            current_files = set(response_dir.glob("*.md")) if response_dir.exists() else set()
            new_files = current_files - before_files
            if new_files:
                newest = max(new_files, key=lambda f: f.stat().st_mtime)
                print(f"\n📨 {label} 응답 도착: {newest.relative_to(bridge)}\n")
                print(newest.read_text(encoding="utf-8"))
                return

    print(f"\n⏰ {max_retries}회 재시도 후에도 응답 없음.")
    print(f"   나중에 `latest --source {target}` 로 확인하세요.")


def cmd_status(args):
    """양쪽 브릿지의 응답 상태를 확인한다."""
    bridge = resolve_bridge_dir(args.dir)
    sources = get_sources(bridge)

    # --after 타임스탬프 이후의 새 파일만 확인
    after_ts = 0.0
    if args.after:
        try:
            dt = datetime.datetime.strptime(args.after, "%Y-%m-%dT%H:%M:%S")
            after_ts = dt.timestamp()
        except ValueError:
            try:
                after_ts = float(args.after)
            except ValueError:
                print(f"⚠️  --after 형식 오류: {args.after}")
                after_ts = 0.0

    results = {}
    for target in ["gemini", "codex"]:
        resp_dir = sources[target]
        if not resp_dir.exists():
            results[target] = {"status": "no_dir", "file": None}
            continue

        md_files = sorted(resp_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not md_files:
            results[target] = {"status": "empty", "file": None}
            continue

        newest = md_files[0]
        mtime = newest.stat().st_mtime

        if after_ts > 0 and mtime < after_ts:
            results[target] = {"status": "waiting", "file": None}
        else:
            results[target] = {"status": "ready", "file": newest, "mtime": mtime}

    # 출력
    all_ready = True
    for target in ["gemini", "codex"]:
        r = results[target]
        label = "Gemini" if target == "gemini" else "Codex"
        if r["status"] == "ready":
            rel = r["file"].relative_to(bridge)
            ago = int(time.time() - r["mtime"])
            if ago < 60:
                ago_str = f"{ago}초 전"
            else:
                ago_str = f"{ago // 60}분 전"
            print(f"  {label}: ✅ {rel} ({ago_str})")
        elif r["status"] == "waiting":
            print(f"  {label}: ⏳ 응답 대기 중")
            all_ready = False
        elif r["status"] == "no_dir":
            print(f"  {label}: — 디렉토리 없음")
            all_ready = False
        else:
            print(f"  {label}: — 파일 없음")
            all_ready = False

    if all_ready:
        print("\n✅ 양쪽 모두 응답 완료")
    else:
        print("\n⏳ 아직 대기 중인 응답이 있습니다")

    # exit code로도 상태 전달 (스크립트 활용용)
    if not all_ready:
        raise SystemExit(1)


def cmd_config(args):
    """전송 모드를 확인하거나 변경한다."""
    bridge = resolve_bridge_dir(args.dir)
    config = load_config(bridge)

    changed = False
    if args.gemini_mode:
        if args.gemini_mode not in VALID_GEMINI_MODES:
            print(f"⚠️  알 수 없는 모드: {args.gemini_mode} (가능: {', '.join(VALID_GEMINI_MODES)})")
            raise SystemExit(1)
        config["gemini"]["mode"] = args.gemini_mode
        changed = True
    if args.agy_sandbox is not None:
        config.setdefault("agy", {})["sandbox"] = args.agy_sandbox
        changed = True
    if args.agy_model:
        config.setdefault("agy", {})["model"] = args.agy_model
        changed = True

    if changed:
        save_config(bridge, config)
        print(f"✅ 설정 저장: {_config_path(bridge).relative_to(bridge.parent)}")

    gemini_mode = config.get("gemini", {}).get("mode", "file-bridge")
    print(f"📡 Gemini 전송 모드: {gemini_mode}")
    print(f"   Codex 전송 모드: file-bridge (고정 — Codex 전용 CLI 없음)")
    if gemini_mode == "agy":
        agy_cfg = config.get("agy", {})
        print(f"   agy.sandbox={agy_cfg.get('sandbox', True)}  agy.model={agy_cfg.get('model') or '(기본)'}")
        import agy_provider  # noqa: F401 — 가용성 확인용 지연 임포트
        found = agy_provider.find_agy()
        print(f"   agy 실행 파일: {found or '❌ PATH에서 못 찾음 (네이티브 Windows에서 실행 필요)'}")


def main():
    parser = argparse.ArgumentParser(description="AI Bridge — Gemini + Codex")
    parser.add_argument(
        "--dir",
        default=None,
        help="프로젝트 디렉토리 (기본: CWD)",
    )
    parser.add_argument(
        "--source",
        choices=["gemini", "codex", "claude", "all"],
        default="all",
        help="검색 소스 (기본: all)",
    )
    parser.add_argument(
        "--target",
        choices=["gemini", "codex"],
        default="gemini",
        help="전송 대상 (기본: gemini)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="프로젝트에 bridge 구조 초기화")
    p_init.add_argument(
        "--mode",
        choices=list(VALID_GEMINI_MODES),
        default="file-bridge",
        help="Gemini 전송 모드 (기본: file-bridge)",
    )

    p_config = sub.add_parser("config", help="전송 모드 확인/변경")
    p_config.add_argument(
        "--gemini-mode",
        choices=list(VALID_GEMINI_MODES),
        default=None,
        help="Gemini 전송 모드 변경",
    )
    p_config.add_argument(
        "--agy-sandbox",
        dest="agy_sandbox",
        type=lambda v: v.lower() in ("1", "true", "yes", "on"),
        default=None,
        help="agy 모드 sandbox 사용 여부 (true/false)",
    )
    p_config.add_argument(
        "--agy-model",
        dest="agy_model",
        default=None,
        help="agy 모드에서 사용할 모델명",
    )

    sub.add_parser("latest", help="최신 응답 출력")

    p_list = sub.add_parser("list", help="최근 파일 목록")
    p_list.add_argument("-n", type=int, default=10, help="표시 개수 (기본: 10)")

    p_search = sub.add_parser("search", help="키워드 검색")
    p_search.add_argument("keyword", help="검색할 키워드")

    p_send = sub.add_parser("send", help="메시지 전송")
    p_send.add_argument("message", help="전송할 메시지")
    p_send.add_argument("--topic", default="message", help="메시지 토픽")

    p_ask = sub.add_parser("ask", help="전송 + 응답 대기")
    p_ask.add_argument("message", help="전송할 메시지")
    p_ask.add_argument("--topic", default="message", help="메시지 토픽")
    p_ask.add_argument("--timeout", type=int, default=600, help="대기 시간 초 (기본: 600)")
    p_ask.add_argument("--retries", type=int, default=3, help="재시도 횟수 (기본: 3)")

    p_status = sub.add_parser("status", help="양쪽 브릿지 응답 상태 확인")
    p_status.add_argument("--after", default=None, help="이 시각 이후 파일만 확인 (ISO 또는 epoch)")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "config": cmd_config,
        "latest": cmd_latest,
        "list": cmd_list,
        "search": cmd_search,
        "send": cmd_send,
        "ask": cmd_ask,
        "status": cmd_status,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
