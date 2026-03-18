#!/usr/bin/env python3
"""Minimal CLI for interacting with the AI Assistant API."""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")


def _colored(text: str, color: str) -> str:
    return text


def _print_json(data: object | str | None) -> None:
    if data is None:
        print("no data returned")
        return
    if isinstance(data, str):
        print(data)
        return
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _call(method: str, path: str, **kwargs) -> object | None:
    url = f"{API_BASE.rstrip('/')}/{path.lstrip('/')}"
    resp = requests.request(method, url, **kwargs)
    resp.raise_for_status()
    if not resp.text:
        return None
    try:
        return resp.json()
    except ValueError:
        return resp.text


def _list_tasks(_: argparse.Namespace) -> None:
    data = _call("GET", "/tasks")
    _print_json(data)


def _create_task(args: argparse.Namespace) -> None:
    payload = {"user_input": args.input}
    data = _call("POST", "/tasks", json=payload)
    _print_json(data)


def _show_task(args: argparse.Namespace) -> None:
    data = _call("GET", f"/tasks/{args.task_id}")
    _print_json(data)


def _show_steps(args: argparse.Namespace) -> None:
    data = _call("GET", f"/tasks/{args.task_id}/steps")
    _print_json(data)


def _show_checkpoint(args: argparse.Namespace) -> None:
    data = _call("GET", f"/tasks/{args.task_id}/checkpoint")
    _print_json(data)


def _resume_task(args: argparse.Namespace) -> None:
    payload = {"note": args.note or "", "from_step": args.from_step}
    data = _call("POST", f"/tasks/{args.task_id}/resume", json=payload)
    _print_json(data)


def _interrupt_task(args: argparse.Namespace) -> None:
    payload = {"note": args.note or ""}
    data = _call("POST", f"/tasks/{args.task_id}/interrupt", json=payload)
    _print_json(data)


def _list_approvals(args: argparse.Namespace) -> None:
    if args.task_id:
        data = _call("GET", f"/tasks/{args.task_id}/approvals")
    else:
        params = {"status": args.status} if args.status else {}
        data = _call("GET", "/approvals", params=params)
    _print_json(data)


def _decide_approval(args: argparse.Namespace) -> None:
    path = "approve" if args.approve else "reject"
    payload = {"note": args.note or ""}
    data = _call("POST", f"/approvals/{args.approval_id}/{path}", json=payload)
    _print_json(data)


def _list_risk_policies(_: argparse.Namespace) -> None:
    data = _call("GET", "/risk-policies")
    _print_json(data)


def _set_risk_policy(args: argparse.Namespace) -> None:
    raw_value = args.value
    try:
        policy_value = json.loads(raw_value)
    except ValueError:
        lowered = raw_value.strip().lower()
        if lowered == "true":
            policy_value = True
        elif lowered == "false":
            policy_value = False
        else:
            policy_value = raw_value

    data = _call("PUT", f"/risk-policies/{args.policy_key}", json={"policy_value": policy_value})
    _print_json(data)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI for ai-assistant API")
    subparsers = parser.add_subparsers(dest="command")

    task_parser = subparsers.add_parser("task", help="Task operations")
    task_sub = task_parser.add_subparsers(dest="subcommand")
    task_list = task_sub.add_parser("list", help="List tasks")
    task_list.set_defaults(func=_list_tasks)

    task_create = task_sub.add_parser("create", help="Create a task")
    task_create.add_argument("-i", "--input", required=True, help="Task description / prompt")
    task_create.set_defaults(func=_create_task)

    task_show = task_sub.add_parser("show", help="Show a task")
    task_show.add_argument("task_id", type=int, help="Task ID")
    task_show.set_defaults(func=_show_task)

    task_resume = task_sub.add_parser("resume", help="Resume a failed or paused task")
    task_resume.add_argument("task_id", type=int, help="Task ID")
    task_resume.add_argument("--from-step", type=int, help="Resume from a specific step order")
    task_resume.add_argument("--note", default="", help="Optional resume note")
    task_resume.set_defaults(func=_resume_task)

    task_interrupt = task_sub.add_parser("interrupt", help="Interrupt or pause a task")
    task_interrupt.add_argument("task_id", type=int, help="Task ID")
    task_interrupt.add_argument("--note", default="", help="Optional interrupt note")
    task_interrupt.set_defaults(func=_interrupt_task)

    steps_parser = subparsers.add_parser("steps", help="Show task steps")
    steps_parser.add_argument("task_id", type=int, help="Task ID")
    steps_parser.set_defaults(func=_show_steps)

    checkpoint_parser = subparsers.add_parser("checkpoint", help="Show task checkpoint")
    checkpoint_parser.add_argument("task_id", type=int, help="Task ID")
    checkpoint_parser.set_defaults(func=_show_checkpoint)

    approvals_parser = subparsers.add_parser("approvals", help="Approval operations")
    approvals_sub = approvals_parser.add_subparsers(dest="subcommand")
    approvals_list = approvals_sub.add_parser("list", help="List approvals")
    approvals_list.add_argument("--status", choices=("pending", "approved", "rejected"), help="Filter by status")
    approvals_list.add_argument("--task-id", type=int, help="Only list approvals for a task")
    approvals_list.set_defaults(func=_list_approvals)

    approvals_decide = approvals_sub.add_parser("decide", help="Approve or reject an approval")
    approvals_decide.add_argument("approval_id", type=int, help="Approval ID")
    approvals_decide.add_argument("--approve", action="store_true", help="Approve the request")
    approvals_decide.add_argument("--reject", action="store_true", help="Reject the request")
    approvals_decide.add_argument("--note", default="", help="Optional decision note")
    approvals_decide.set_defaults(func=_decide_approval)

    risk_parser = subparsers.add_parser("risk", help="Risk policy operations")
    risk_sub = risk_parser.add_subparsers(dest="subcommand")

    risk_list = risk_sub.add_parser("list", help="List risk policies")
    risk_list.set_defaults(func=_list_risk_policies)

    risk_set = risk_sub.add_parser("set", help="Update a risk policy")
    risk_set.add_argument("policy_key", help="Risk policy key")
    risk_set.add_argument("value", help='Policy value. Use JSON for lists, e.g. \'["GET","POST"]\'')
    risk_set.set_defaults(func=_set_risk_policy)

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        sys.exit(1)

    if getattr(args, "approve", False) and getattr(args, "reject", False):
        print("Choose either --approve or --reject", file=sys.stderr)
        sys.exit(1)
    if getattr(args, "reject", False) and not getattr(args, "approve", False):
        # mark reject for helper
        args.approve = False

    if args.command == "approvals" and args.subcommand == "decide" and not (args.approve or args.reject):
        print("Please specify --approve or --reject", file=sys.stderr)
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
