#!/usr/bin/env python3
"""Gemini-Claude Bridge — 전역 CLI.

어떤 프로젝트에서든 bridge/ 디렉토리를 통해 Gemini와 통신한다.
순수 Python stdlib만 사용 (외부 의존성 없음).

사용법:
    python3 bridge.py --dir /path/to/project init
    python3 bridge.py --dir /path/to/project send "메시지"
    python3 bridge.py --dir /path/to/project --source gemini latest
    python3 bridge.py --dir /path/to/project --source gemini list
    python3 bridge.py --dir /path/to/project --source gemini search "키워드"
    python3 bridge.py --dir /path/to/project ask "질문" --timeout 120
"""

import argparse
import datetime
import os
import time
from pathlib import Path
from typing import Optional

BRIDGE_OUTPUT_RULE = """\
# Bridge Output Rule

## 핵심 규칙: 모든 응답을 bridge 디렉토리에 자동 저장

당신(Gemini)은 이 워크스페이스에서 응답할 때마다, 반드시 해당 응답을 마크다운 파일로 저장해야 합니다.

### 저장 위치
`bridge/from-gemini/` 디렉토리에 저장합니다.

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

### 태스크 카테고리별 응답 가이드

Claude가 `[TASK: <category>]` 헤더를 붙여 보내면, 해당 카테고리에 맞는 응답을 작성합니다.

| 카테고리 | 응답에 포함할 것 |
|---------|----------------|
| `design-review` | 구체적 개선 포인트 (색상, 간격, 타이포, 레이아웃), before/after 비교, Tailwind 클래스 제안 |
| `design-create` | HTML/Tailwind 목업 코드, 색상 팔레트, 레이아웃 구조도 |
| `web-research` | 출처 URL 포함, 비교표, 핵심 요약, 적용 권장사항 |
| `image-generate` | 생성된 이미지를 bridge/from-gemini/ 에 저장 |
| `verify-check` | 체크 항목별 pass/fail, 스크린샷, 개선 필요 사항 |
| `general` | 자유 형식 |

### 프로젝트 컨텍스트

`bridge/gemini-context.md` 파일에 이 프로젝트의 기술 스택, 디자인 시스템, Gemini 역할이 정의되어 있습니다.
요청에 `[CONTEXT]` 섹션이 포함되면 참고하여 프로젝트에 맞는 응답을 작성합니다.

### 규칙
1. **모든** 실질적 응답에 대해 파일을 생성합니다 (단순 인사나 확인 응답 제외)
2. 수식이 포함된 경우 LaTeX 형식으로 작성합니다
3. 코드가 포함된 경우 적절한 언어 태그로 코드 블록을 사용합니다
4. 파일 저장 후 사용자에게 저장 완료를 알립니다

### 목적
이 파일들은 Claude Code가 읽어서 활용합니다. Gemini의 응답을 Claude가 참조할 수 있도록 하는 브릿지 역할입니다.
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
        "claude": bridge / "from-claude",
    }


def get_md_files(bridge: Path, source: str = "all") -> list:
    sources = get_sources(bridge)
    if source == "all":
        dirs = [sources["gemini"], sources["claude"]]
    else:
        dirs = [sources[source]]

    files = []
    for d in dirs:
        if d and d.exists():
            files.extend(d.glob("*.md"))

    return sorted(files, key=lambda f: f.name, reverse=True)


# === Commands ===

def cmd_init(args, bridge_dir_override=None):
    """프로젝트에 bridge 구조를 초기화한다."""
    base = Path(args.dir) if args.dir else Path(os.getcwd())

    bridge = base / "bridge"
    from_gemini = bridge / "from-gemini"
    from_claude = bridge / "from-claude"
    agent_rules = base / ".agent" / "rules"

    from_gemini.mkdir(parents=True, exist_ok=True)
    from_claude.mkdir(parents=True, exist_ok=True)
    agent_rules.mkdir(parents=True, exist_ok=True)

    # .gitkeep
    for d in [from_gemini, from_claude]:
        gitkeep = d / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

    # bridge-output.md 규칙 (항상 최신으로 덮어쓰기)
    rule_file = agent_rules / "bridge-output.md"
    rule_file.write_text(BRIDGE_OUTPUT_RULE, encoding="utf-8")
    print(f"  {'업데이트' if rule_file.exists() else '생성'}: {rule_file.relative_to(base)}")

    # gemini-context.md 스켈레톤 (없을 때만 생성)
    context_file = bridge / "gemini-context.md"
    project_name = base.name
    if not context_file.exists():
        skeleton = GEMINI_CONTEXT_SKELETON.replace("{project_name}", project_name)
        context_file.write_text(skeleton, encoding="utf-8")
        print(f"  생성: {context_file.relative_to(base)}")
        print(f"  ℹ️  Claude가 CLAUDE.md를 읽고 내용을 채웁니다.")
    else:
        print(f"  이미 존재: {context_file.relative_to(base)}")

    print(f"✅ Bridge 초기화 완료: {base}")
    print(f"   bridge/from-gemini/  — Gemini 응답 저장소")
    print(f"   bridge/from-claude/  — Claude 요청 저장소")
    print(f"   bridge/gemini-context.md — 프로젝트 컨텍스트 (Gemini용)")
    print(f"   .agent/rules/bridge-output.md — Antigravity 규칙")


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


def cmd_send(args):
    bridge = resolve_bridge_dir(args.dir)
    sources = get_sources(bridge)
    from_claude = sources["claude"]
    from_claude.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")
    file_ts = now.strftime("%Y-%m-%d_%H-%M")

    topic = args.topic or "message"
    message = args.message

    # 긴 메시지는 별도 .md 파일로 저장하고 트리거에는 경로만 포함
    if len(message) > MAX_TRIGGER_LENGTH:
        detail_filename = f"{file_ts}_{topic}-detail.md"
        detail_path = from_claude / detail_filename
        detail_path.write_text(
            f"---\ntimestamp: \"{timestamp}\"\ntopic: \"{topic}\"\nsource: claude\n---\n\n{message}\n",
            encoding="utf-8",
        )
        rel_detail = f"bridge/from-claude/{detail_filename}"
        trigger_message = (
            f"아래 파일에 상세 요청이 있습니다. 파일을 읽고 그 안의 요청대로 처리해주세요.\n\n"
            f"📄 파일 경로: {rel_detail}\n\n"
            f"응답은 bridge/from-gemini/ 에 저장해주세요."
        )
        print(f"📄 긴 메시지 → 파일 분리: {rel_detail} ({len(message)}자)")
    else:
        trigger_message = message

    filename = f"{file_ts}_{topic}.trigger"
    trigger_path = from_claude / filename

    content = f"""---
timestamp: "{timestamp}"
topic: "{topic}"
source: claude
---

{trigger_message}
"""

    trigger_path.write_text(content, encoding="utf-8")
    print(f"✅ Trigger 생성: {trigger_path.relative_to(bridge)}")
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
    bridge = resolve_bridge_dir(args.dir)
    sources = get_sources(bridge)
    from_gemini = sources["gemini"]
    before_files = set(from_gemini.glob("*.md")) if from_gemini.exists() else set()

    cmd_send(args)

    max_retries = args.retries
    for attempt in range(max_retries + 1):
        if attempt > 0:
            print(f"\n🔄 응답 없음 → continue 전송 ({attempt}/{max_retries})")
            _send_continue(args)

        print(f"\n⏳ Gemini 응답 대기 중 (최대 {args.timeout}초)...")
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            time.sleep(3)
            current_files = set(from_gemini.glob("*.md")) if from_gemini.exists() else set()
            new_files = current_files - before_files
            if new_files:
                newest = max(new_files, key=lambda f: f.stat().st_mtime)
                print(f"\n📨 응답 도착: {newest.relative_to(bridge)}\n")
                print(newest.read_text(encoding="utf-8"))
                return

    print(f"\n⏰ {max_retries}회 재시도 후에도 응답 없음.")
    print("   나중에 `latest --source gemini` 로 확인하세요.")


def main():
    parser = argparse.ArgumentParser(description="Gemini-Claude Bridge")
    parser.add_argument(
        "--dir",
        default=None,
        help="프로젝트 디렉토리 (기본: CWD)",
    )
    parser.add_argument(
        "--source",
        choices=["gemini", "claude", "all"],
        default="all",
        help="검색 소스 (기본: all)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="프로젝트에 bridge 구조 초기화")

    sub.add_parser("latest", help="최신 응답 출력")

    p_list = sub.add_parser("list", help="최근 파일 목록")
    p_list.add_argument("-n", type=int, default=10, help="표시 개수 (기본: 10)")

    p_search = sub.add_parser("search", help="키워드 검색")
    p_search.add_argument("keyword", help="검색할 키워드")

    p_send = sub.add_parser("send", help="Gemini에게 메시지 전송")
    p_send.add_argument("message", help="전송할 메시지")
    p_send.add_argument("--topic", default="message", help="메시지 토픽")

    p_ask = sub.add_parser("ask", help="Gemini에게 전송 + 응답 대기")
    p_ask.add_argument("message", help="전송할 메시지")
    p_ask.add_argument("--topic", default="message", help="메시지 토픽")
    p_ask.add_argument("--timeout", type=int, default=180, help="대기 시간 초 (기본: 180)")
    p_ask.add_argument("--retries", type=int, default=3, help="continue 재시도 횟수 (기본: 3)")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "latest": cmd_latest,
        "list": cmd_list,
        "search": cmd_search,
        "send": cmd_send,
        "ask": cmd_ask,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
