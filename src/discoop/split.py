"""Split a `messages.md` export into parts of a limited estimated size, without ever splitting a message.

A part is a run of whole "blocks". A block starts at a message, at a channel heading or at a thread heading, as
`render/text.py` lays them out in Markdown, and goes on to the line before the next block starts:

    # server / #channel                                  channel heading, ...
    range: 2026-11-02 12:00 .. 2026-11-03 12:00 (UTC+01:00) | messages: 2 | files: 0   ... its summary line
                                                          a blank line
    [2026-11-02 14:03] Student A (@student_a)             a message: head line, text (may have blank lines), details
    text of the message

    ## thread "name"                                      a thread heading and its header line
    created: ... | last activity: ... | messages: 1 | files: 0

Message texts are Markdown too, so a line that looks like a boundary may be part of a message. A boundary therefore
needs more than its first characters: a message starts with `[YYYY-MM-DD HH:MM] ` after a blank line (or at the start
of the text), a heading after a blank line and followed by its exact summary line (`range: ...` for a channel, the
header line for a thread). A message that has a line `# Heading` (even followed by `range: foo`) stays whole.

Known limitation: a line in the body of a message that looks exactly like a message head (`[2026-01-01 10:00] x`) right
after a blank line of the body cannot be told apart from a real message, and a body that has a blank line followed by a
channel or thread heading and its exact summary line cannot either. Such a message is split there.
"""

import logging
import re
from collections.abc import Callable

from discoop import tokens

logger = logging.getLogger("discoop.split")
logger.addHandler(logging.NullHandler())  # no handler of ours: do not let `lastResort` print it to stderr

_MESSAGE_HEAD = re.compile(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] ")
_TIME = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"
_CHANNEL_SUMMARY = re.compile(rf"range: (?:all|{_TIME}) \.\. {_TIME} \(UTC")
_THREAD_SUMMARY = re.compile(rf"(?:created: {_TIME} \| last activity: {_TIME} \| )?messages: \d+ \| files: \d+")


def _is_boundary(lines: list[str], index: int) -> bool:
    """True if the line at `index` starts a new block (see the module docstring)."""
    if index and lines[index - 1] != "\n":
        return False  # only a blank line ends a block
    line = lines[index]
    if _MESSAGE_HEAD.match(line):
        return True
    following = lines[index + 1] if index + 1 < len(lines) else ""
    if line.startswith("## thread "):
        return _THREAD_SUMMARY.match(following) is not None
    if line.startswith("# "):
        return _CHANNEL_SUMMARY.match(following) is not None
    return False


def split_markdown(
    text: str,
    max_tokens: int,
    *,
    on_warning: Callable[[str], None] | None = None,
) -> list[str]:
    """Split `messages.md` into token-bounded parts without splitting any message.

    Each part starts with `<!-- discoop part {i} of {total} -->\\n`.
    If an atomic message or block exceeds `max_tokens`, it is placed alone in its own part
    and a warning is issued (to the log and, if given, to `on_warning`).
    """
    if max_tokens < 1:
        raise ValueError(f"max_tokens must be at least 1, got {max_tokens}")

    normalized = text.replace("\r\n", "\n")
    if not normalized.strip():
        return []

    lines = normalized.splitlines(keepends=True)
    blocks: list[str] = []
    current_block: list[str] = []

    for index, line in enumerate(lines):
        if current_block and _is_boundary(lines, index):
            blocks.append("".join(current_block))
            current_block = []
        current_block.append(line)

    if current_block:
        blocks.append("".join(current_block))

    if not blocks:
        return []

    def _pack(assumed_total: int) -> list[list[str]]:
        parts: list[list[str]] = []
        current_part: list[str] = []

        for block in blocks:
            part_num = len(parts) + 1
            hdr = f"<!-- discoop part {part_num} of {assumed_total} -->\n"
            block_tokens = tokens.estimate_tokens(hdr + block)

            if not current_part:
                current_part.append(block)
                if block_tokens > max_tokens:
                    # Oversized atomic block alone in part
                    parts.append(current_part)
                    current_part = []
            else:
                candidate = hdr + "".join(current_part) + block
                if tokens.estimate_tokens(candidate) <= max_tokens:
                    current_part.append(block)
                else:
                    parts.append(current_part)
                    current_part = [block]
                    part_num = len(parts) + 1
                    hdr = f"<!-- discoop part {part_num} of {assumed_total} -->\n"
                    if tokens.estimate_tokens(hdr + block) > max_tokens:
                        parts.append(current_part)
                        current_part = []

        if current_part:
            parts.append(current_part)

        return parts

    assumed_total = 1
    for _ in range(10):
        partition = _pack(assumed_total)
        if len(partition) == assumed_total:
            break
        assumed_total = len(partition)

    total = len(partition)
    result_parts: list[str] = []

    for idx, p_blocks in enumerate(partition, 1):
        hdr = f"<!-- discoop part {idx} of {total} -->\n"
        content = "".join(p_blocks)
        part_text = hdr + content
        est = tokens.estimate_tokens(part_text)
        if est > max_tokens:
            msg = (
                f"Message or block exceeds max_tokens ({est} > {max_tokens}) "
                f"and was placed in its own part ({idx} of {total})."
            )
            logger.warning(msg)
            if on_warning is not None:
                on_warning(msg)
        result_parts.append(part_text)

    return result_parts
