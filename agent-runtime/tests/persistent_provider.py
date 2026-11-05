"""Offline interactive provider fixture with real lifecycle callbacks and retained context."""

import json
import os
import re
import shlex
import subprocess
import sys
import time
import tty
import uuid
from datetime import UTC, datetime
from pathlib import Path


def main():
    args = sys.argv[1:]
    provider = Path(sys.argv[0]).name
    if "--help" in args:
        print(
            "fixture temporarily unavailable"
            if Path("deny-restore.txt").exists()
            else "--no-daemon --settings"
        )
        return
    if "app-server" in args:
        for line in sys.stdin:
            request = json.loads(line)
            if "id" in request:
                result = {"config": {}} if request["method"] == "config/read" else {}
                print(json.dumps({"id": request["id"], "result": result}), flush=True)
        return
    if provider == "claude":
        assert args[args.index("--permission-mode") + 1] == "auto", args
    else:
        assert "--dangerously-bypass-approvals-and-sandbox" in args, args
    hooks, notifier = {}, None
    if provider == "claude":
        hooks = json.loads(args[args.index("--settings") + 1])["hooks"]
    else:
        for index, value in enumerate(args):
            if value != "-c":
                continue
            override = args[index + 1]
            if override.startswith("notify="):
                notifier = json.loads(override[7:])
            elif override.startswith("hooks."):
                name = override.split("=", 1)[0][6:]
                command = json.loads(
                    re.search(r'command=("(?:\\.|[^"\\])*"),timeout=', override)[1]
                )
                hooks[name] = [{"hooks": [{"command": command}]}]
    context_file = Path("provider-context.json")
    resume_flag = "--resume" if provider == "claude" else "resume"
    resuming = resume_flag in args
    if resuming:
        context = json.loads(context_file.read_text())
        identity, count = context["provider"], context["count"]
        assert args[args.index(resume_flag) + 1] == identity, args
    else:
        identity = (
            args[args.index("--session-id") + 1] if provider == "claude" else str(uuid.uuid4())
        )
        count = 0
    transcripts = Path(os.environ["ROAMI_DATA"]) / "provider-transcripts"
    os.environ["CODEX_HOME"] = str(transcripts / "codex")
    os.environ["CLAUDE_CONFIG_DIR"] = str(transcripts / "claude")
    if provider == "codex":
        transcript = transcripts / "codex/sessions/2026/11/05" / f"rollout-fixture-{identity}.jsonl"
    else:
        transcript = transcripts / "claude/projects/fixture" / f"{identity}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)

    def transcript_turn(prompt, text, turn_id):
        stamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        cwd = str(Path.cwd())
        if provider == "codex":

            def record(kind, payload):
                return {"type": kind, "timestamp": stamp, "payload": payload}

            records = [
                record("session_meta", {"id": identity, "cwd": cwd}),
                record(
                    "event_msg",
                    {"type": "task_started", "turn_id": turn_id, "root_turn_id": turn_id},
                ),
                record(
                    "response_item",
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": prompt}],
                    },
                ),
                record(
                    "response_item",
                    {
                        "type": "message",
                        "role": "assistant",
                        "phase": "final_answer",
                        "content": [{"type": "output_text", "text": text}],
                    },
                ),
                record(
                    "event_msg",
                    {
                        "type": "task_complete",
                        "turn_id": turn_id,
                        "root_turn_id": turn_id,
                        "last_agent_message": text,
                    },
                ),
            ]
        else:
            records = [
                {
                    "type": "user",
                    "sessionId": identity,
                    "cwd": cwd,
                    "promptId": turn_id,
                    "message": {"content": [{"type": "text", "text": prompt}]},
                },
                {
                    "type": "assistant",
                    "sessionId": identity,
                    "cwd": cwd,
                    "message": {
                        "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": text}],
                    },
                },
            ]
        with transcript.open("a") as stream:
            for record in records:
                stream.write(json.dumps(record) + "\n")
        transcript.chmod(0o600)

    def event(name, **fields):
        payload = {"hook_event_name": name, "session_id": identity, **fields}
        command = shlex.split(hooks[name][0]["hooks"][0]["command"])
        result = subprocess.run(
            command, input=json.dumps(payload).encode(), capture_output=True, check=False
        )
        if result.returncode:
            raise RuntimeError(f"{name}: {result.stderr.decode()}")

    def turn(prompt):
        nonlocal count
        count += 1
        turn_id = f"fixture-turn-{count}"
        event("UserPromptSubmit", prompt_id=turn_id, turn_id=turn_id, prompt=prompt)
        Path("turn-count.txt").write_text(str(count))
        if prompt == "Hold correction":
            Path("held.txt").touch()
            while not Path("release.txt").exists():
                time.sleep(0.05)
        text = f"{provider}: retained context turn {count}"
        context_file.write_text(json.dumps({"provider": identity, "count": count}))
        transcript_turn(prompt, text, turn_id)
        if provider == "codex":
            result = subprocess.run(
                [
                    *notifier,
                    json.dumps(
                        {
                            "type": "agent-turn-complete",
                            "thread-id": identity,
                            "turn-id": turn_id,
                            "input-messages": [prompt],
                            "last-assistant-message": text,
                        }
                    ),
                ],
                capture_output=True,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(result.stderr.decode())
        else:
            event(
                "Stop",
                prompt_id=turn_id,
                last_assistant_message=text,
                background_tasks=[],
                session_crons=[],
            )
            event("Notification", prompt_id=turn_id, notification_type="idle_prompt")
        Path("last-completed.txt").write_text(str(count))
        print(text, flush=True)

    event("SessionStart")
    turn(args[-1])
    tty.setraw(sys.stdin.fileno())
    print("\x1b[?2004h", end="", flush=True)
    buffer, pasting = "", False
    while True:
        char = os.read(sys.stdin.fileno(), 1).decode()
        if not char:
            return
        buffer += char
        if buffer.endswith("\x1b[200~"):
            buffer = buffer[:-6]
            pasting = True
        elif buffer.endswith("\x1b[201~"):
            buffer = buffer[:-6]
            pasting = False
        elif char in "\r\n" and not pasting:
            prompt, buffer = buffer.strip(), ""
            if prompt:
                turn(prompt.replace("\r\n", "\n").replace("\r", "\n"))


if __name__ == "__main__":
    main()
