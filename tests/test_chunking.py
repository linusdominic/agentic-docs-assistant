from docs_agent.chunking import chunk_markdown


def test_short_document_is_one_chunk():
    assert chunk_markdown("# Title\n\nOne paragraph.") == ["# Title\n\nOne paragraph."]


def test_each_heading_starts_a_new_chunk():
    chunks = chunk_markdown("# A\n\nalpha\n\n## B\n\nbeta")
    assert chunks == ["# A\n\nalpha", "## B\n\nbeta"]


def test_long_section_is_split_and_keeps_its_heading():
    paragraphs = "\n\n".join(f"Paragraph {i} " + "word " * 40 for i in range(6))
    chunks = chunk_markdown(f"## Limits\n\n{paragraphs}", max_chars=500)

    assert len(chunks) > 1
    assert all(chunk.startswith("## Limits") for chunk in chunks)
    assert all(f"Paragraph {i}" in "".join(chunks) for i in range(6))


def test_oversized_paragraph_is_split_on_sentences():
    text = " ".join(f"Sentence number {i} is here." for i in range(60))
    chunks = chunk_markdown(text, max_chars=300)

    assert len(chunks) > 1
    assert all(len(chunk) <= 300 for chunk in chunks)
    assert all(chunk.endswith(".") for chunk in chunks)


def test_run_on_text_without_sentence_breaks_is_hard_cut():
    chunks = chunk_markdown("x" * 1000, max_chars=300)
    assert [len(chunk) for chunk in chunks] == [300, 300, 300, 100]


def test_heading_with_no_body_is_dropped():
    assert chunk_markdown("# Title\n\n## Section\n\nbody") == ["## Section\n\nbody"]


def test_empty_input():
    assert chunk_markdown("  \n\n ") == []
