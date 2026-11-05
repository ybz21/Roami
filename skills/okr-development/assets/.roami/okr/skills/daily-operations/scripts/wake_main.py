#!/usr/bin/env python3
"""Deliver one dated request to an existing project Main through the installed CLI."""

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class CommandFailure(Exception):
    def __init__(self, code="CLI_REQUEST_FAILED"):
        self.code = code
        super().__init__(code)


def run_cli(arguments, text=None):
    result = subprocess.run(
        ["roami", "agent", *arguments],
        input=text,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise CommandFailure() from None
    if result.returncode:
        error = data.get("error", {}) if isinstance(data, dict) else {}
        code = error.get("code") if isinstance(error, dict) else None
        raise CommandFailure(
            code
            if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}", code)
            else "CLI_REQUEST_FAILED"
        )
    if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
        raise CommandFailure("INVALID_CLI_RESPONSE")
    return data["data"]


def wake(
    project,
    conversation,
    timezone,
    slot,
    prompt,
    *,
    dry_run=False,
    now=None,
    cli=run_cli,
):
    if os.environ.get("ROAMI_AGENT_CALLER_ROLE") or os.environ.get(
        "ROAMI_AGENT_TURN_ID"
    ):
        return {"state": "blocked", "reason": "EXTERNAL_TRIGGER_REQUIRED"}
    if (
        not project.strip()
        or not conversation.strip()
        or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", slot)
    ):
        raise ValueError("project, conversation and a short slot name are required")
    if not prompt.strip() or len(prompt.encode()) > 8000:
        raise ValueError("prompt must contain 1..8000 UTF-8 bytes")
    project, conversation = project.strip(), conversation.strip()
    try:
        location = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise ValueError("timezone must be an installed IANA timezone") from None
    today = (now or datetime.now(location)).astimezone(location).date().isoformat()
    key = (
        "okr-daily-"
        + hashlib.sha256(
            json.dumps(
                [project, conversation, today, slot], separators=(",", ":")
            ).encode()
        ).hexdigest()
    )
    receipt = {
        "projectId": project,
        "conversationId": conversation,
        "date": today,
        "timezone": timezone,
        "slot": slot,
        "requestKey": key,
    }
    try:
        status = cli(["status"])
        supported = status.get("projectMainWake") is True
        identity = cli(["identity", "--conversation", conversation])
        if (
            identity.get("kind") != "project_main"
            or identity.get("projectId") != project
            or identity.get("conversationId") != conversation
            or not identity.get("activeBranchId")
        ):
            return {
                **receipt,
                "state": "blocked",
                "reason": "PROJECT_MAIN_IDENTITY_MISMATCH",
            }
        branch = identity["activeBranchId"]
        history = cli(
            [
                "history",
                "--conversation",
                conversation,
                "--branch",
                branch,
                "--limit",
                "1",
            ]
        )
        if (
            history.get("conversation", {}).get("id") != conversation
            or history.get("branchId") != branch
        ):
            return {
                **receipt,
                "state": "blocked",
                "reason": "MAIN_HISTORY_IDENTITY_MISMATCH",
            }
        if any(
            turn.get("state") in {"queued", "running"}
            for turn in history.get("turns", [])
        ):
            return {**receipt, "state": "deferred", "reason": "MAIN_ACTIVE"}
        messages = history.get("messages", [])
        if (
            messages
            and messages[-1].get("role") == "assistant"
            and messages[-1].get("content", {}).get("question")
        ):
            return {**receipt, "state": "deferred", "reason": "USER_ANSWER_PENDING"}
        if dry_run:
            return {
                **receipt,
                "state": "prepared",
                "delivered": False,
                "supported": supported,
            }
        if not supported:
            return {
                **receipt,
                "state": "blocked",
                "reason": "MAIN_WAKE_NOT_SUPPORTED",
                "delivered": False,
            }
    except (CommandFailure, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {
            **receipt,
            "state": "blocked",
            "reason": "MAIN_VERIFICATION_UNAVAILABLE",
        }
    text = (
        f"定时协作请求：{today}（{timezone}），时段 {slot}。\n"
        "这是已配置的日程触发，不是账号或发布批准，不回答待确认事项。"
        "继续原Main和原成员；核对已有任务，不重复创建或派发。投递不是完成。\n\n"
        + prompt.strip()
    )
    try:
        result = cli(
            [
                "wake",
                "--conversation",
                conversation,
                "--project",
                project,
                "--key",
                key,
                "--file",
                "-",
            ],
            text,
        )
    except CommandFailure as error:
        if error.code in {"MAIN_BUSY", "MAIN_WAITING_USER"}:
            return {
                **receipt,
                "state": "deferred",
                "reason": error.code,
                "delivered": False,
            }
        if error.code in {
            "PROJECT_MAIN_IDENTITY_MISMATCH",
            "CONVERSATION_NOT_FOUND",
            "REQUEST_KEY_CONFLICT",
            "MODEL_NOT_CONFIGURED",
            "INVALID_MESSAGE",
        }:
            return {
                **receipt,
                "state": "blocked",
                "reason": error.code,
                "delivered": False,
            }
        return {
            **receipt,
            "state": "unknown",
            "reason": "DELIVERY_UNCONFIRMED",
            "delivered": None,
        }
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return {
            **receipt,
            "state": "unknown",
            "reason": "DELIVERY_UNCONFIRMED",
            "delivered": None,
        }
    if (
        result.get("kind") != "message"
        or not result.get("messageId")
        or not result.get("turnId")
    ):
        return {
            **receipt,
            "state": "unknown",
            "reason": "DELIVERY_UNCONFIRMED",
            "delivered": None,
        }
    return {
        **receipt,
        "state": "accepted",
        "delivered": True,
        "messageId": result["messageId"],
        "turnId": result["turnId"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["project", "conversation", "timezone", "slot", "prompt-file"]:
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = wake(
            args.project,
            args.conversation,
            args.timezone,
            args.slot,
            Path(args.prompt_file).read_text(),
            dry_run=args.dry_run,
        )
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["state"] in {"prepared", "deferred", "accepted"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
