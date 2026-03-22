#!/usr/bin/env python3
import json
import sys


def main() -> int:
    raw = sys.stdin.read()
    payload = json.loads(raw or "{}")
    tool_name = str(payload.get("tool_name") or "")
    arguments = payload.get("arguments") or {}
    message = str(arguments.get("message") or "")
    response = {
        "ok": True,
        "output_text": f"mcp_stdio_echo 成功：{message}",
        "output_data": {
            "tool_name": tool_name,
            "echo": message,
            "arguments": arguments,
        },
        "error": "",
    }
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
