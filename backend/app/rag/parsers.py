"""Turn uploaded files (PDF, DOCX, TXT, Markdown) into titled text sections."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import PurePath

from app.errors import AppError, UnsupportedMedia

SUPPORTED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}

_MAGIC = {".pdf": b"%PDF-", ".docx": b"PK\x03\x04"}


@dataclass
class Section:
    heading: str
    text: str


class ParseError(AppError):
    code = "document_parse_error"


def detect_type(filename: str, data: bytes) -> str:
    ext = PurePath(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedMedia("Only PDF, DOCX, TXT and Markdown files are supported.")
    magic = _MAGIC.get(ext)
    # Check the content, not just the name: a renamed executable is rejected here.
    if magic and not data.startswith(magic):
        raise UnsupportedMedia("The file content does not match its extension.")
    if ext in {".txt", ".md", ".markdown"}:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnsupportedMedia("Text files must be UTF-8 encoded.") from exc
    return ext


def parse(filename: str, data: bytes) -> list[Section]:
    ext = detect_type(filename, data)
    try:
        if ext == ".pdf":
            sections = _parse_pdf(data)
        elif ext == ".docx":
            sections = _parse_docx(data)
        elif ext in {".md", ".markdown"}:
            sections = _parse_markdown(data.decode("utf-8"))
        else:
            sections = _parse_text(data.decode("utf-8"))
    except AppError:
        raise
    except Exception as exc:
        raise ParseError("The document could not be read.") from exc
    sections = [s for s in sections if s.text.strip()]
    if not sections:
        raise ParseError("The document contains no extractable text.")
    return sections


def _parse_markdown(text: str) -> list[Section]:
    sections: list[Section] = []
    path: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            sections.append(Section(" > ".join(path), "\n".join(buffer).strip()))
            buffer.clear()

    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            flush()
            level = len(match.group(1))
            path[:] = [*path[: level - 1], match.group(2).strip()]
        else:
            buffer.append(line)
    flush()
    return sections


def _parse_text(text: str) -> list[Section]:
    """Plain text: an all-caps line followed by a paragraph is treated as a heading."""
    sections: list[Section] = []
    heading = ""
    buffer: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        is_heading = 3 < len(stripped) < 90 and stripped.upper() == stripped and re.search(r"[A-Z]", stripped)
        if is_heading:
            if buffer:
                sections.append(Section(heading, "\n".join(buffer).strip()))
                buffer = []
            heading = stripped.title()
        else:
            buffer.append(line)
    if buffer:
        sections.append(Section(heading, "\n".join(buffer).strip()))
    return sections


def _parse_docx(data: bytes) -> list[Section]:
    from docx import Document

    doc = Document(io.BytesIO(data))
    sections: list[Section] = []
    heading, buffer = "", []
    for para in doc.paragraphs:
        style = (para.style.name if para.style is not None else "").lower()
        if style.startswith("heading") or style == "title":
            if buffer:
                sections.append(Section(heading, "\n".join(buffer)))
                buffer = []
            heading = para.text.strip()
        elif para.text.strip():
            buffer.append(para.text.strip())
    for table in doc.tables:
        for row in table.rows:
            buffer.append(" | ".join(cell.text.strip() for cell in row.cells))
    if buffer:
        sections.append(Section(heading, "\n".join(buffer)))
    return sections


def _parse_pdf(data: bytes) -> list[Section]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ParseError("Encrypted PDF files are not supported.")
    if len(reader.pages) > 300:
        raise ParseError("PDF files are limited to 300 pages.")
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    # PDFs lose heading styles; numbered lines like "2. What the warranty covers" become headings.
    sections: list[Section] = []
    heading, buffer = "", []
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^\d{1,2}\.\s+[A-Z][^.]{2,80}$", stripped):
            if buffer:
                sections.append(Section(heading, "\n".join(buffer)))
                buffer = []
            heading = stripped
        elif stripped:
            buffer.append(stripped)
    if buffer:
        sections.append(Section(heading, "\n".join(buffer)))
    return sections
