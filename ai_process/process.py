#!/usr/bin/env python3
"""Feed Franciscus source texts to Claude Code block-by-block for translation and/or annotation.

Results are saved incrementally to a .progress.jsonl file so that interrupted runs
can be resumed automatically. Use --compile to recompile outputs from a progress
file without calling Claude again. Shared logic lives in common.py; this tool drives
Claude via the `claude` CLI. See process_api.py for the Anthropic API variant.

Usage:
    python ai_process/process.py books/1Cel.md --translate it
    python ai_process/process.py books/1Cel.md --annotate topics/topics.yaml
    python ai_process/process.py books/1Cel.md --translate it --annotate topics/topics.yaml
    python ai_process/process.py books/1Cel.md --translate it --compile  # recompile only
"""

import json
import subprocess
import sys

import common


def call_claude(system_prompt: str, user_prompt: str, schema: dict) -> dict:
    """Invoke the claude CLI and return parsed JSON."""
    cmd = [
        "claude",
        "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--system-prompt", system_prompt,
        "--allowedTools", "",
    ]

    result = subprocess.run(
        cmd,
        input=user_prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    if result.returncode != 0:
        print(f"  [ERROR] claude exited {result.returncode}: {result.stderr[:200]}", file=sys.stderr)
        return {}

    try:
        envelope = json.loads(result.stdout)
        # structured_output contains the parsed JSON object directly
        if "structured_output" in envelope and envelope["structured_output"]:
            return envelope["structured_output"]
        # fallback: try result field
        raw = envelope.get("result", "")
        if isinstance(raw, str) and raw:
            return json.loads(raw)
        return {}
    except (json.JSONDecodeError, TypeError):
        print(f"  [ERROR] could not parse JSON: {result.stdout[:200]}", file=sys.stderr)
        return {}


def main():
    parser = common.build_arg_parser(
        "Process Franciscus source texts with Claude Code for translation/annotation"
    )
    args = parser.parse_args()
    common.run(parser, args, call_claude)


if __name__ == "__main__":
    main()
