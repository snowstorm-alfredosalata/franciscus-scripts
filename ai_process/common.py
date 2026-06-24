"""Shared logic for the Franciscus AI processing tools.

Both `process.py` (Claude Code CLI) and `process_api.py` (Anthropic API) parse a
FORMAT.md source into blocks, send each block to Claude for translation and/or
annotation, save results incrementally to a `.progress.jsonl` file for resume, and
recompile the outputs. Everything except the actual Claude invocation lives here;
each tool supplies a `process_block` callable.
"""

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# process_block(system_prompt, user_prompt, schema) -> parsed JSON dict (or {} on failure)
ProcessBlock = Callable[[str, str, dict], dict]


@dataclass
class Block:
    kind: str  # "title", "chapter", "aside", "paragraph"
    raw: str
    chapter_id: str | None = None
    paragraph_id: str | None = None
    aside_id: str | None = None
    chapter_title: str | None = None


def parse_blocks(text: str) -> list[Block]:
    """Parse a FORMAT.md-conforming file into ordered blocks."""
    blocks: list[Block] = []
    lines = text.split("\n")

    # Skip frontmatter
    i = 0
    if lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            i += 1
        i += 1  # past closing ---

    current_chapter_id: str | None = None
    aside_count = 0  # per-chapter aside counter, mirrors server-side ingestion

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # H1 title
        if re.match(r"^# ", stripped):
            blocks.append(Block(kind="title", raw=stripped))
            i += 1
            continue

        # H2 chapter
        m = re.match(r"^## (.+)", stripped)
        if m:
            anchor = re.search(r'<a id="([^"]+)">', stripped)
            current_chapter_id = anchor.group(1) if anchor else None
            aside_count = 0
            title_text = re.sub(r'\s*<a id="[^"]+"></a>\s*', "", m.group(1)).strip()
            blocks.append(Block(
                kind="chapter",
                raw=stripped,
                chapter_id=current_chapter_id,
                chapter_title=title_text,
            ))
            i += 1
            continue

        # Aside block
        if stripped == "<aside>":
            aside_lines = []
            i += 1
            while i < len(lines) and lines[i].strip() != "</aside>":
                aside_lines.append(lines[i])
                i += 1
            i += 1  # past </aside>
            aside_count += 1
            aside_id = f"{current_chapter_id}-aside-{aside_count}" if current_chapter_id else None
            blocks.append(Block(
                kind="aside",
                raw="\n".join(aside_lines).strip(),
                chapter_id=current_chapter_id,
                aside_id=aside_id,
            ))
            continue

        # Paragraph block
        pm = re.match(r'^<p id="([^"]+)"', stripped)
        if pm:
            p_id = pm.group(1)
            p_lines = []
            # first line might have content after the tag
            first_content = re.sub(r'^<p[^>]*>\s*', "", stripped)
            if first_content:
                p_lines.append(first_content)
            i += 1
            while i < len(lines) and lines[i].strip() != "</p>":
                p_lines.append(lines[i])
                i += 1
            i += 1  # past </p>
            blocks.append(Block(
                kind="paragraph",
                raw="\n".join(p_lines).strip(),
                paragraph_id=p_id,
                chapter_id=current_chapter_id,
            ))
            continue

        # HTML comments or other lines — skip
        i += 1

    return blocks


def block_key(index: int, block: Block) -> str:
    label = block.paragraph_id or block.aside_id or block.chapter_id or block.kind
    return f"{index}:{block.kind}:{label}"


def progress_path(output_dir: Path, stem: str, lang: str | None) -> Path:
    suffix = f".{lang}" if lang else ""
    return output_dir / f"{stem}{suffix}.progress.jsonl"


def load_progress(path: Path) -> dict[str, dict]:
    """Load completed block results from a progress file, keyed by block_key."""
    done: dict[str, dict] = {}
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        done[entry["key"]] = entry.get("result", {})
    return done


def save_progress_entry(path: Path, key: str, block_kind: str, result: dict) -> None:
    """Append one completed block to the progress file."""
    entry = {"key": key, "kind": block_kind, "result": result}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_topics_toml(path: Path) -> str:
    """Load the topics TOML and format as context for Claude.

    Each category is rendered as the literal ``type:value`` pairs the model is
    allowed to emit, so the closed vocabulary can be copied character-for-character.
    The TOML nests values under a ``values`` key (``[virtue]\\nvalues = [...]``);
    that key is unwrapped so the type is the category name, not ``virtue.values``.
    """

    def value_lists(category: str, node) -> list[tuple[str, list]]:
        """Yield (type, values) pairs, unwrapping the conventional `values` key."""
        if isinstance(node, list):
            return [(category, node)]
        if isinstance(node, dict):
            if isinstance(node.get("values"), list):
                return [(category, node["values"])]
            pairs = []
            for sub, vals in node.items():
                pairs.extend(value_lists(f"{category}.{sub}", vals))
            return pairs
        return []

    with open(path, "rb") as f:
        data = tomllib.load(f)

    parts = []
    for category, node in data.items():
        for type_name, values in value_lists(category, node):
            parts.append("\n".join(f"{type_name}:{v}" for v in values))
    return "\n\n".join(parts)


def build_prompt(block: Block, *, translate: str | None, annotate_context: str | None) -> str:
    """Build the user prompt for a single block.

    Kept deliberately minimal: this is the only part that varies per block, so the
    constant instructions live in the system prompt (which is cached). The output
    fields are enforced by the JSON schema, not restated here.
    """
    if block.kind == "title":
        return f"Document title (H1 heading):\n\n{block.raw.lstrip('# ')}"
    if block.kind == "chapter":
        return f"Chapter heading:\n\n{block.chapter_title}"
    if block.kind == "aside":
        return f"Rubric / aside (non-numbered text):\n\n{block.raw}"
    return f"Paragraph [{block.paragraph_id}] of a medieval Latin Franciscan text:\n\n{block.raw}"


# BCP-47 base codes → full language names, so the prompt reads "into Italian"
# rather than "into it" (which the model misreads as the English pronoun).
_LANG_NAMES = {
    "it": "Italian",
    "en": "English",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "la": "Latin",
    "nl": "Dutch",
    "pl": "Polish",
    "ca": "Catalan",
}


def language_name(tag: str) -> str:
    """Resolve a BCP-47 tag (e.g. 'it', 'pt-BR') to a full language name for the prompt."""
    base = tag.split("-")[0].lower()
    return _LANG_NAMES.get(base, tag)


def build_system_prompt(*, translate: str | None, annotate_context: str | None) -> str:
    """Build the system prompt — constant across every block in a run, so it can be cached.

    All standing instructions (translation style, annotation standards, the
    topic list) belong here rather than in the per-block user prompt: that keeps
    the cacheable prefix large and the volatile per-call payload small.
    """
    lines = [
        "You are a scholar of medieval Latin Franciscan hagiography.",
        "You process one text block at a time and return ONLY a JSON object matching the requested schema — no markdown fences, no commentary.",
    ]
    if translate:
        lines.append(
            f"\nTRANSLATION (the 'translated' field): render the Latin into {language_name(translate)} as polished literary "
            "prose — elegant and idiomatic for a modern reader, faithful to the meaning, register, and "
            "rhetorical movement of the original. Lean toward literary quality over word-for-word literalism, "
            "but never so free that sense or tone is lost, nor so literal that it reads as a crib. "
            "Preserve every [n] verse marker and every <ref to=\"...\">...</ref> tag verbatim and in its "
            "original position; translate only the text around and inside them."
        )
    if annotate_context:
        lines.append(
            "\nANNOTATION (the 'topics' field, paragraphs only): a comma-separated string of type:value "
            "pairs, e.g. \"person:st_francis_of_assisi, place:assisi, event:conversion_of_francis, "
            "virtue:poverty\".\n"
            "CLOSED VOCABULARY — you may use ONLY the exact type:value pairs listed below. Never invent, coin, "
            "modify, pluralize, or rephrase a value, and never introduce a new type. If a person, place, event, "
            "theme, or virtue is present but not in the list, do not annotate it at all. Every pair you output "
            "must match an entry below character-for-character.\n"
            "Apply these standards:\n"
            "- person, place: annotate every listed person and place that the passage clearly refers to. Omit "
            "one only when its identification is genuinely uncertain.\n"
            "- event: annotate a listed event only when you are confident the passage genuinely depicts it.\n"
            "- theme: annotate only listed themes that are clearly central to the passage. Be strict — typically "
            "0 to 2 themes per paragraph, and never more than 2. Skip themes that are merely touched on or "
            "implied.\n"
            "- virtue: annotate a listed virtue only when the passage is especially significant or exemplary "
            "for it, not for incidental mentions. Be strict — typically 0 to 2 virtues per paragraph, and never "
            "more than 2.\n"
            "If nothing meets these standards, return an empty string."
        )
        lines.append(f"\nAllowed topic values (the ONLY values you may use):\n{annotate_context}")
    return "\n".join(lines)


def build_json_schema(*, translate: bool, annotate: bool, is_paragraph: bool) -> dict:
    """Build a JSON schema for Claude's structured output."""
    props = {}
    required = []

    if translate:
        props["translated"] = {"type": "string", "description": "Translated text"}
        required.append("translated")

    if annotate and is_paragraph:
        props["topics"] = {
            "type": "string",
            "description": "Comma-separated type:value pairs",
        }
        required.append("topics")

    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


def compile_translation(source_text: str, blocks: list[Block], results: list[dict], lang: str) -> str:
    """Recompose a translated .md file from block results."""
    # Extract frontmatter
    fm_end = source_text.find("\n---\n", 4)
    frontmatter = source_text[: fm_end + 5]

    output_lines = [frontmatter.strip(), ""]

    for block, res in zip(blocks, results):
        translated = res.get("translated", "")
        if not translated:
            continue

        if block.kind == "title":
            output_lines.append(f"# {translated}")
            output_lines.append("")

        elif block.kind == "chapter":
            anchor = f' <a id="{block.chapter_id}"></a>' if block.chapter_id else ""
            output_lines.append(f"## {translated}{anchor}")
            output_lines.append("")

        elif block.kind == "aside":
            output_lines.append("<aside>")
            output_lines.append(translated)
            output_lines.append("</aside>")
            output_lines.append("")

        elif block.kind == "paragraph":
            output_lines.append(f'<p id="{block.paragraph_id}">')
            output_lines.append(translated)
            output_lines.append("</p>")
            output_lines.append("")

    return "\n".join(output_lines) + "\n"


def compile_annotations(blocks: list[Block], results: list[dict], work_id: str) -> list[dict]:
    """Compile annotation entries from block results."""
    annotations = []
    for block, res in zip(blocks, results):
        if block.kind != "paragraph":
            continue
        topics = res.get("topics", "")
        if not topics:
            continue
        annotations.append({
            "paragraph": block.paragraph_id,
            "topics": topics,
            "by": "Claude <noreply@anthropic.com>",
            "by_type": "ai",
            "verified": False,
        })
    return annotations


def build_arg_parser(description: str) -> argparse.ArgumentParser:
    """Build the argument parser shared by both processing tools.

    Tools may add tool-specific arguments to the returned parser before parsing.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("source", help="Path to source .md file (e.g. books/1Cel.md)")
    parser.add_argument("--translate", metavar="LANG", help="Target language BCP-47 tag (e.g. it, en, fr)")
    parser.add_argument("--annotate", metavar="TOML", help="Path to topics TOML file")
    parser.add_argument("--output-dir", metavar="DIR", help="Output directory (default: same as source)")
    parser.add_argument("--compile", action="store_true", help="Recompile outputs from existing .progress.jsonl without calling Claude")
    parser.add_argument("--dry-run", action="store_true", help="Parse and show blocks without calling Claude")
    return parser


def run(parser: argparse.ArgumentParser, args: argparse.Namespace, process_block: ProcessBlock) -> None:
    """Run the full processing flow, delegating each Claude call to `process_block`.

    `process_block` is only invoked for blocks that need work (not in --compile or
    --dry-run mode, and not already present in the progress file), so callers may
    defer expensive setup (e.g. building an API client) until first invocation.
    """
    if not args.translate and not args.annotate:
        parser.error("At least one of --translate or --annotate is required")

    source_path = Path(args.source)
    if not source_path.exists():
        print(f"Error: source file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    source_text = source_path.read_text(encoding="utf-8")

    # Extract work id from frontmatter
    m = re.search(r"^id:\s*(.+)$", source_text, re.MULTILINE)
    work_id = m.group(1).strip() if m else source_path.stem

    # Parse into blocks
    blocks = parse_blocks(source_text)
    print(f"Parsed {len(blocks)} blocks from {source_path.name}", file=sys.stderr)

    if args.dry_run:
        for i, b in enumerate(blocks):
            label = b.paragraph_id or b.aside_id or b.chapter_id or b.kind
            print(f"  [{i:3d}] {b.kind:10s} | {label:15s} | {b.raw[:60]}...")
        sys.exit(0)

    # Load topics context
    annotate_context = None
    if args.annotate:
        toml_path = Path(args.annotate)
        if not toml_path.exists():
            print(f"Error: topics TOML not found: {toml_path}", file=sys.stderr)
            sys.exit(1)
        annotate_context = load_topics_toml(toml_path)

    # Build system prompt (shared across all calls)
    system_prompt = build_system_prompt(
        translate=args.translate,
        annotate_context=annotate_context,
    )

    # Determine output dir
    output_dir = Path(args.output_dir) if args.output_dir else source_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # Progress file for incremental save / resume
    prog_path = progress_path(output_dir, source_path.stem, args.translate)
    done = load_progress(prog_path)

    if done:
        print(f"Found progress file with {len(done)} completed blocks: {prog_path.name}", file=sys.stderr)

    if args.compile:
        if not done:
            print("Error: no progress file found to compile from", file=sys.stderr)
            sys.exit(1)
        results = [done.get(block_key(i, b), {}) for i, b in enumerate(blocks)]
        filled = sum(1 for r in results if r)
        print(f"Compiling from {filled}/{len(blocks)} completed blocks", file=sys.stderr)
    else:
        # Process blocks, skipping already-done ones
        results = []
        total = len(blocks)
        skipped = 0

        for i, block in enumerate(blocks):
            key = block_key(i, block)

            # Already in progress file — reuse
            if key in done:
                results.append(done[key])
                skipped += 1
                continue

            do_annotate = bool(annotate_context) and block.kind == "paragraph"
            do_translate = bool(args.translate)

            if not do_translate and not do_annotate:
                results.append({})
                continue

            label = block.paragraph_id or block.aside_id or block.chapter_id or block.kind
            print(f"  [{i + 1}/{total}] {block.kind} {label}...", file=sys.stderr, end=" ", flush=True)

            user_prompt = build_prompt(block, translate=args.translate, annotate_context=annotate_context)
            schema = build_json_schema(
                translate=do_translate,
                annotate=do_annotate,
                is_paragraph=(block.kind == "paragraph"),
            )

            res = process_block(system_prompt, user_prompt, schema)
            results.append(res)

            if res:
                save_progress_entry(prog_path, key, block.kind, res)
                print("OK", file=sys.stderr)
            else:
                print("FAILED", file=sys.stderr)

        if skipped:
            print(f"  (skipped {skipped} already-completed blocks)", file=sys.stderr)

    # Write outputs
    if args.translate:
        lang = args.translate
        out_name = f"{source_path.stem}.{lang}.md"
        out_path = output_dir / out_name
        translated_text = compile_translation(source_text, blocks, results, lang)
        out_path.write_text(translated_text, encoding="utf-8")
        print(f"\nTranslation written to: {out_path}", file=sys.stderr)

    if args.annotate:
        out_name = f"{work_id}.json"
        out_path = output_dir / out_name
        annotations = compile_annotations(blocks, results, work_id)

        # Merge with existing annotations if file exists
        if out_path.exists():
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            existing_ids = {a["paragraph"] for a in existing}
            for ann in annotations:
                if ann["paragraph"] not in existing_ids:
                    existing.append(ann)
            annotations = existing

        out_path.write_text(json.dumps(annotations, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
