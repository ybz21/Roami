"""Offline interactive provider fixture with real lifecycle callbacks and retained context."""

import json
import os
import re
import shlex
import subprocess
import sys
import time
import tty
from pathlib import Path


def main():
    args = sys.argv[1:]
    provider = Path(sys.argv[0]).name
    if "--help" in args:
        print("--no-daemon --settings")
        return
    if "app-server" in args:
        for line in sys.stdin:
            request = json.loads(line)
            if "id" in request:
                result = {"config": {}} if request["method"] == "config/read" else {}
                print(json.dumps({"id": request["id"], "result": result}), flush=True)
        return
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
    identity, count = "fixture-" + provider, 0

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
