#!/usr/bin/env python3
"""Queue a dated wakeup of the original project goal through the installed CLI."""

import argparse
import json
import os
import re
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class CommandFailure(Exception):
    def __init__(self, code="CLI_REQUEST_FAILED"):
        self.code = code
        super().__init__(code)


def run_cli(arguments):
    result = subprocess.run(
        ["roami", *arguments],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        data = None
    if result.returncode:
        error = data.get("error", {}) if isinstance(data, dict) else {}
        code = error.get("code") if isinstance(error, dict) else None
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}", code):
            # Public CLI errors are text; keep only the initial bounded error code.
            match = re.match(r"(?:Error: )?([A-Z][A-Z0-9_]{0,100})(?:\b|:)", result.stderr.strip())
            code = match[1] if match else "CLI_REQUEST_FAILED"
        raise CommandFailure(code)
    if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
        raise CommandFailure("INVALID_CLI_RESPONSE")
    return data["data"]


def wake(
    project,
    conversation,
    swarm,
    delegation,
    timezone,
    slot,
    *,
    date=None,
    dry_run=False,
    clock=None,
    cli=run_cli,
):
    if os.environ.get("ROAMI_AGENT_CALLER_ROLE") or os.environ.get("ROAMI_AGENT_TURN_ID"):
        return {
            "state": "blocked",
            "reason": "EXTERNAL_TRIGGER_REQUIRED",
            "delivered": False,
        }
    if not all(
        isinstance(value, str) and value.strip()
        for value in [project, conversation, swarm, delegation]
    ):
        raise ValueError("original project, Main, Swarm and delegation are required")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", slot):
        raise ValueError("slot must be a short lowercase name")
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError("timezone must be an installed IANA timezone") from None
    stamp = clock or datetime.now(zone)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("clock must include its timezone")
    local_date = date or stamp.astimezone(zone).date().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", local_date):
        raise ValueError("date must be YYYY-MM-DD")
    receipt = {
        "projectId": project,
        "conversationId": conversation,
        "swarmId": swarm,
        "delegationId": delegation,
        "timezone": timezone,
        "date": local_date,
        "slot": slot,
    }
    try:
        status = cli(["agent", "status"])
        if status.get("projectGoalDailyWake") is not True:
            return {
                **receipt,
                "state": "blocked",
                "reason": "GOAL_DAILY_NOT_SUPPORTED",
                "delivered": False,
            }
        actual = cli(["agent", "identity", "--conversation", conversation])
        if (
            actual.get("kind") != "project_main"
            or actual.get("projectId") != project
            or actual.get("conversationId") != conversation
            or not actual.get("activeBranchId")
        ):
            return {
                **receipt,
                "state": "blocked",
                "reason": "PROJECT_MAIN_IDENTITY_MISMATCH",
                "delivered": False,
            }
    except (CommandFailure, subprocess.TimeoutExpired):
        return {
            **receipt,
            "state": "blocked",
            "reason": "MAIN_VERIFICATION_UNAVAILABLE",
            "delivered": False,
        }
    arguments = [
        "swarm",
        "daily",
        swarm,
        "--delegation",
        delegation,
        "--project",
        project,
        "--main-conversation",
        conversation,
        "--timezone",
        timezone,
        "--date",
        local_date,
        "--slot",
        slot,
        "--json",
    ]
    if dry_run:
        arguments.append("--dry-run")
    try:
        result = cli(arguments)
    except CommandFailure as error:
        if error.code in {
            "PROJECT_MAIN_IDENTITY_MISMATCH",
            "SWARM_NOT_FOUND",
            "SWARM_PROJECT_REQUIRED",
            "SWARM_DELEGATION_REQUIRED",
            "SWARM_DELEGATION_SOURCE_FORGOTTEN",
            "SWARM_DELEGATION_SOURCE_STOPPED",
            "SWARM_COORDINATION_PAUSED",
            "SWARM_DAILY_DATE_EXPIRED",
            "INVALID_SWARM_DAILY_SLOT",
            "INVALID_SWARM_DAILY_TIMEZONE",
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
    except subprocess.TimeoutExpired:
        return {
            **receipt,
            "state": "unknown",
            "reason": "DELIVERY_UNCONFIRMED",
            "delivered": None,
        }
    marker = result.get("dailySlot")
    expected = {key: receipt[key] for key in ["delegationId", "timezone", "date", "slot"]}
    if (
        marker != expected
        or result.get("swarmId") != swarm
        or result.get("state") != ("prepared" if dry_run else "accepted")
        or result.get("delivered") is not (not dry_run)
        or not dry_run
        and not result.get("jobId")
    ):
        return {
            **receipt,
            "state": "unknown",
            "reason": "DELIVERY_UNCONFIRMED",
            "delivered": None,
        }
    return {**receipt, **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["project", "conversation", "swarm", "delegation", "timezone", "slot"]:
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--date")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = wake(
            args.project,
            args.conversation,
            args.swarm,
            args.delegation,
            args.timezone,
            args.slot,
            date=args.date,
            dry_run=args.dry_run,
        )
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["state"] in {"prepared", "accepted"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
