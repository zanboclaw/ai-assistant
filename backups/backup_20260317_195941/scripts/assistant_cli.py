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

    steps_parser = subparsers.add_parser("steps", help="Show task steps")
    steps_parser.add_argument("task_id", type=int, help="Task ID")
    steps_parser.set_defaults(func=_show_steps)

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
