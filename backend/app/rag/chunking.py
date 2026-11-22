"""Heading-aware chunking.

Sections from the parser are split with a recursive character splitter. Each chunk keeps its section
heading, and the embedded text starts with "document title > heading" so a chunk like "15 days" is
still about returns when it is retrieved on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.language import detect_language
from app.rag.parsers import Section


@dataclass
class Chunk:
    index: int
    heading: str
    content: str
    language: str

    def embedding_text(self, title: str) -> str:
        context = f"{title} > {self.heading}" if self.heading else title
        return f"{context}\n{self.content}"


def chunk_sections(sections: list[Section], chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", "。", "؟ ", "? ", "! ", "، ", ", ", " ", ""],
        keep_separator="end",
    )
    chunks: list[Chunk] = []
    for section in sections:
        for piece in splitter.split_text(section.text):
            piece = piece.strip()
            if len(piece) < 20:
                continue
            language = detect_language(f"{section.heading} {piece}").code
            chunks.append(Chunk(len(chunks), section.heading[:300], piece, language))
    return chunks


def estimate_tokens(text: str) -> int:
    # Close enough for budgeting: ~4 characters per token for Latin text, ~2.5 for Arabic.
    arabic = sum(1 for ch in text if "؀" <= ch <= "ۿ")
    return int((len(text) - arabic) / 4 + arabic / 2.5) + 1
