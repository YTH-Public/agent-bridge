#!/usr/bin/env python3
"""agy_provider — Antigravity CLI(agy) 실행 백엔드 (실험적).

파일 브릿지의 대안 provider. Gemini 대상 요청을 Antigravity 채팅패널 대신
`agy` CLI로 직접 실행한다. 순수 Python stdlib만 사용.

## 왜 transcript 파일을 읽는가
`agy -p`는 non-TTY(서브프로세스/파이프/리다이렉트) 환경에서 모델 응답을
stdout에 쓰지 않는 문서화된 버그가 있다(antigravity-cli Issue #76/#115).
exit code는 0이지만 stdout은 비어 있다. 그래서 이 어댑터는 stdout 대신
agy가 디스크에 남기는 transcript.jsonl에서 최종 응답을 추출한다.

    ~/.gemini/antigravity-cli/brain/<conv-id>/.system_generated/logs/transcript.jsonl

conv-id는 `cache/last_conversations.json`이 워크스페이스 경로 → conv-id로
매핑한다. 매핑 실패 시 가장 최근 수정된 transcript로 폴백한다.

## 주의 (Codex 지적 반영)
- agy는 승인 게이트 없이 도구(list_dir/파일쓰기/셸/네트워크)를 자동 실행한다.
  기본적으로 `--sandbox`로 실행해 위험을 줄인다(config에서 끌 수 있음).
- 내부 transcript 경로는 비공식이라 agy 업데이트로 깨질 수 있다.
  실패하면 명확한 에러를 던져 file-bridge로 폴백하도록 한다.
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional


class AgyError(Exception):
    """agy provider 실행 실패. 호출측은 file-bridge 폴백을 안내해야 한다."""


def _agy_home() -> Path:
    return Path.home() / ".gemini" / "antigravity-cli"


def find_agy() -> Optional[str]:
    """PATH에서 agy 실행 파일을 찾는다 (없으면 None)."""
    return shutil.which("agy") or shutil.which("agy.exe")


def _last_conversations() -> dict:
    cache = _agy_home() / "cache" / "last_conversations.json"
    if not cache.exists():
        return {}
    try:
        return json.loads(cache.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _conv_id_for(workdir: str) -> Optional[str]:
    """워크스페이스 경로에 매핑된 conv-id를 찾는다 (대소문자 무시)."""
    target = os.path.normcase(os.path.abspath(workdir))
    for key, conv_id in _last_conversations().items():
        if os.path.normcase(os.path.abspath(key)) == target:
            return conv_id
    return None


def _transcript_path(conv_id: str) -> Path:
    return _agy_home() / "brain" / conv_id / ".system_generated" / "logs" / "transcript.jsonl"


def _newest_transcript() -> Optional[Path]:
    brain = _agy_home() / "brain"
    if not brain.exists():
        return None
    candidates = list(brain.glob("*/.system_generated/logs/transcript.jsonl"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _extract_final_response(transcript: Path) -> Optional[str]:
    """transcript.jsonl에서 마지막 PLANNER_RESPONSE 본문(content)을 추출한다.

    중간 PLANNER_RESPONSE는 tool_calls만 있고 content가 없다. 최종 답변만
    content 문자열을 가진다. 가장 마지막 것을 최종 응답으로 본다.
    """
    if not transcript.exists():
        return None
    final = None
    try:
        lines = transcript.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            d.get("source") == "MODEL"
            and d.get("type") == "PLANNER_RESPONSE"
            and d.get("status") == "DONE"
        ):
            content = d.get("content")
            if isinstance(content, str) and content.strip():
                final = content.strip()
    return final


def run(
    prompt: str,
    response_dir: Path,
    topic: str = "message",
    workdir: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 300,
    poll_timeout: int = 45,
    sandbox: bool = True,
) -> Path:
    """agy로 프롬프트를 실행하고 응답을 response_dir에 .md로 저장한다.

    Returns: 저장한 응답 파일 경로.
    Raises: AgyError — agy 미설치 / 실행 실패 / transcript에서 응답 못 찾음.
    """
    agy = find_agy()
    if not agy:
        raise AgyError(
            "agy CLI를 찾을 수 없습니다. PATH에 agy가 있는지 확인하거나 "
            "file-bridge 모드를 사용하세요 (bridge.py config --gemini-mode file-bridge)."
        )

    workdir = workdir or os.getcwd()

    # 실행 전 스냅샷: 워크스페이스 conv-id (실행 후 mtime 게이트는 start_time 기준)
    conv_before = _conv_id_for(workdir)

    cmd = [agy, "-p", prompt]
    if model:
        cmd += ["--model", model]
    if sandbox:
        cmd += ["--sandbox"]

    # 이 시각 이후에 갱신된 transcript만 "이번 실행의 응답"으로 인정한다.
    # (stale transcript 오인 방지 — 다른 워크스페이스/이전 실행 결과 차단)
    # fs mtime 해상도/클럭 라운딩 대비 1초 여유.
    started = time.time() - 1.0

    # stdout은 non-TTY 버그로 비어 있으므로 버린다. stdin은 닫아 블로킹 방지.
    returncode = None
    timed_out = False
    try:
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        returncode = proc.returncode
    except FileNotFoundError as e:
        raise AgyError(f"agy 실행 실패: {e}")
    except subprocess.TimeoutExpired:
        # 타임아웃이어도 transcript에 부분 응답이 남았을 수 있으니 계속 진행
        timed_out = True

    # transcript에서 최종 응답을 폴링 (파일 flush 지연 대비).
    # 반드시 started 이후에 갱신된 transcript만 허용한다.
    deadline = time.time() + poll_timeout
    response = None
    while time.time() < deadline:
        conv = _conv_id_for(workdir) or conv_before
        transcript = _transcript_path(conv) if conv else _newest_transcript()
        if (
            transcript
            and transcript.exists()
            and transcript.stat().st_mtime >= started
        ):
            response = _extract_final_response(transcript)
            if response:
                break
        time.sleep(1)

    if not response:
        detail = ""
        if returncode not in (None, 0):
            detail = f" (agy 종료코드 {returncode})"
        elif timed_out:
            detail = " (타임아웃)"
        raise AgyError(
            "agy 응답을 transcript에서 찾지 못했습니다 (stdout 버그 우회 실패)"
            f"{detail}. file-bridge 모드를 권장합니다."
        )

    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")
    file_ts = now.strftime("%Y-%m-%d_%H-%M")
    # 파일명 안전화 (호출측이 정규화하지만 방어적으로 한 번 더)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (topic or "").strip()).strip("-._")[:50] or "message"
    response_dir.mkdir(parents=True, exist_ok=True)
    out_path = response_dir / f"{file_ts}_{safe}.md"
    out_path.write_text(
        f"---\n"
        f'timestamp: "{timestamp}"\n'
        f'topic: "{topic}"\n'
        f"source: gemini\n"
        f"provider: agy\n"
        f"---\n\n"
        f"{response}\n",
        encoding="utf-8",
    )
    return out_path
