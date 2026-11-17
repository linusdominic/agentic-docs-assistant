"""Split markdown into retrieval-sized chunks that keep their section heading."""

import re

_BLANK_LINE = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _split_long(block: str, max_chars: int) -> list[str]:
    """Break a block that is too big for one chunk, on sentence boundaries where possible."""
    if len(block) <= max_chars:
        return [block]

    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(block):
        while len(sentence) > max_chars:  # a single run-on sentence: hard cut
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if current and len(current) + 1 + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def chunk_markdown(text: str, max_chars: int = 900) -> list[str]:
    """Pack paragraphs into chunks of at most ``max_chars`` (plus a heading line).

    A heading always starts a new chunk, and a chunk that continues a long section is
    prefixed with that section's heading, so every chunk says what it is about.
    """
    chunks: list[str] = []
    heading = ""
    buffer: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal buffer, size
        only_headings = all(b.startswith("#") and "\n" not in b for b in buffer)
        if buffer and not only_headings:
            body = "\n\n".join(buffer)
            if heading and not body.startswith("#"):
                body = f"{heading}\n\n{body}"
            chunks.append(body)
        buffer, size = [], 0

    for block in _BLANK_LINE.split(text):
        block = block.strip()
        if not block:
            continue
        if block.startswith("#"):
            flush()
            heading = block.partition("\n")[0].strip()
            buffer, size = [block], len(block)
            continue
        for piece in _split_long(block, max_chars):
            if buffer and size + len(piece) > max_chars:
                flush()
            buffer.append(piece)
            size += len(piece) + 2
    flush()
    return chunks
