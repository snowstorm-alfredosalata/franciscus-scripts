#!/usr/bin/env python3
"""Feed Franciscus source texts to the Claude API block-by-block for translation and/or annotation.

This is the Anthropic API variant of process.py: instead of shelling out to the
`claude` CLI, it calls the Messages API directly via the official SDK. The API key
is read from `../.claude-api-key` (relative to this script) or from the
ANTHROPIC_API_KEY environment variable. Shared logic lives in common.py.

Usage:
    python ai_process/process_api.py books/1Cel.md --translate it
    python ai_process/process_api.py books/1Cel.md --annotate topics.toml
    python ai_process/process_api.py books/1Cel.md --translate it --annotate topics.toml
    python ai_process/process_api.py books/1Cel.md --translate it --compile  # recompile only
"""

import json
import os
import sys
from pathlib import Path

import anthropic

import common

DEFAULT_MODEL = "claude-opus-4-8"
KEY_FILE = Path(__file__).resolve().parent.parent / ".claude-api-key"


def load_api_key() -> str:
    """Resolve the Anthropic API key from the key file, or ANTHROPIC_API_KEY env var."""
    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env_key:
        return env_key
    print(
        f"Error: no API key found. Expected a key in {KEY_FILE} or the "
        "ANTHROPIC_API_KEY environment variable.",
        file=sys.stderr,
    )
    sys.exit(1)


def call_claude(client: anthropic.Anthropic, model: str, system_prompt: str, user_prompt: str, schema: dict) -> dict:
    """Invoke the Claude Messages API with structured output and return parsed JSON."""
    try:
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            # System prompt is identical for every block in a run, so cache it:
            # the first block pays the write, the rest read at ~0.1x.
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_prompt}],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": schema,
                }
            },
        )
    except anthropic.APIError as e:
        print(f"  [ERROR] API call failed: {e}", file=sys.stderr)
        return {}

    if response.stop_reason == "refusal":
        print("  [ERROR] request refused by safety classifier", file=sys.stderr)
        return {}

    # output_config.format guarantees the first text block is valid JSON
    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        print("  [ERROR] empty response", file=sys.stderr)
        return {}

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"  [ERROR] could not parse JSON: {text[:200]}", file=sys.stderr)
        return {}


def main():
    parser = common.build_arg_parser(
        "Process Franciscus source texts with the Claude API for translation/annotation"
    )
    parser.add_argument("--model", metavar="MODEL", default=DEFAULT_MODEL, help=f"Claude model ID (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    # Lazily build the client so --compile / --dry-run don't require an API key.
    client = None

    def process_block(system_prompt: str, user_prompt: str, schema: dict) -> dict:
        nonlocal client
        if client is None:
            client = anthropic.Anthropic(api_key=load_api_key())
        return call_claude(client, args.model, system_prompt, user_prompt, schema)

    common.run(parser, args, process_block)


if __name__ == "__main__":
    main()
