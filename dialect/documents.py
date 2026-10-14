# Copyright 2026
# SPDX-License-Identifier: GPL-3.0-or-later

"""Structure-aware document import/export helpers for Dialect.

The module deliberately has no GTK dependency so parsers can be tested in
isolation.  Each loader exposes human text as mutable ``TextSegment`` objects;
translating a segment and applying it updates the parsed document while keeping
non-text structure in place.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
from bs4.element import NavigableString


class DocumentError(Exception):
    """Base error for document translation."""


class UnsupportedDocumentError(DocumentError):
    """Raised when a file is binary or its format is unsupported."""


class InvalidDocumentError(DocumentError):
    """Raised when a supported document cannot be parsed."""


@dataclass
class TextSegment:
    """A translatable piece of a structured document."""

    text: str
    _apply: Callable[[str], None]

    def apply(self, translation: str) -> None:
        self._apply(translation)


class StructuredDocument:
    """Parsed document with translatable segments and a same-format writer."""

    def __init__(
        self,
        source: Path,
        format_name: str,
        segments: list[TextSegment],
        writer: Callable[[Path], None],
    ):
        self.source = source
        self.format_name = format_name
        self.segments = segments
        self._writer = writer

    def save(self, path: str | Path) -> None:
        self._writer(Path(path))


_TEXT_EXTENSIONS = {
    ".txt",
    ".text",
    ".md",
    ".markdown",
    ".mdown",
    ".rst",
    ".log",
    ".nfo",
    ".readme",
    ".tex",
    ".org",
    ".adoc",
}
_KV_EXTENSIONS = {
    ".ini",
    ".cfg",
    ".conf",
    ".properties",
    ".desktop",
    ".toml",
    ".yaml",
    ".yml",
    ".env",
}
_HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}
_SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}


def supported_extensions() -> tuple[str, ...]:
    return tuple(
        sorted(
            _TEXT_EXTENSIONS
            | _KV_EXTENSIONS
            | _HTML_EXTENSIONS
            | _SUBTITLE_EXTENSIONS
            | {".json", ".csv", ".tsv", ".xml", ".docx", ".odt", ".epub"}
        )
    )


def is_translatable_text(text: str) -> bool:
    """Avoid sending punctuation, whitespace, timestamps and numeric data."""
    return bool(text and any(char.isalpha() for char in text))


def _preserving_segment(raw: str, setter: Callable[[str], None]) -> TextSegment | None:
    if not is_translatable_text(raw):
        return None
    match = re.match(r"^(\s*)(.*?)(\s*)$", raw, flags=re.DOTALL)
    if not match:
        return None
    prefix, core, suffix = match.groups()
    if not is_translatable_text(core):
        return None

    def apply(value: str) -> None:
        setter(f"{prefix}{value}{suffix}")

    return TextSegment(core, apply)


def _read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise UnsupportedDocumentError("The selected file appears to be binary, not a text document.")

    # UTF-8 is the normal path; BOM-aware UTF-16/32 is useful for Windows text
    # and subtitle files without adding another dependency.
    encodings = ["utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"]
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.insert(0, "utf-16")
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        encodings.insert(0, "utf-32")

    last_error: UnicodeDecodeError | None = None
    for encoding in encodings:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            last_error = exc

    raise UnsupportedDocumentError(
        "The selected file is not UTF text. Convert it to UTF-8/UTF-16 before translating."
    ) from last_error


def _plain_text_document(path: Path) -> StructuredDocument:
    text, encoding = _read_text(path)
    # Keep blank-line separators outside translatable units so paragraphs retain
    # the exact original spacing.
    pieces = re.split(r"(\r?\n[\t ]*\r?\n+)", text)
    segments: list[TextSegment] = []

    for index in range(0, len(pieces), 2):
        raw = pieces[index]

        def setter(value: str, i: int = index) -> None:
            pieces[i] = value

        if segment := _preserving_segment(raw, setter):
            segments.append(segment)

    def writer(output: Path) -> None:
        output.write_text("".join(pieces), encoding=encoding)

    return StructuredDocument(path, "Text", segments, writer)


def _json_document(path: Path) -> StructuredDocument:
    text, _encoding = _read_text(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidDocumentError(f"Invalid JSON: {exc}") from exc

    segments: list[TextSegment] = []

    def walk(value, parent=None, key=None):
        if isinstance(value, dict):
            for child_key, child in list(value.items()):
                walk(child, value, child_key)
        elif isinstance(value, list):
            for child_index, child in enumerate(list(value)):
                walk(child, value, child_index)
        elif isinstance(value, str) and parent is not None and is_translatable_text(value):
            def setter(new_value: str, container=parent, item_key=key) -> None:
                container[item_key] = new_value

            if segment := _preserving_segment(value, setter):
                segments.append(segment)

    walk(data)

    # Preserve the source's common indent style where possible.
    indent: int | str | None = 2
    match = re.search(r"\n([ \t]+)[\"}]", text)
    if match:
        whitespace = match.group(1)
        indent = "\t" if "\t" in whitespace else len(whitespace)
    compact = "\n" not in text

    def writer(output: Path) -> None:
        rendered = json.dumps(
            data,
            ensure_ascii=False,
            indent=None if compact else indent,
            separators=(",", ":") if compact else None,
        )
        if text.endswith("\n"):
            rendered += "\n"
        output.write_text(rendered, encoding="utf-8")

    return StructuredDocument(path, "JSON", segments, writer)


def _csv_document(path: Path, delimiter: str) -> StructuredDocument:
    text, _encoding = _read_text(path)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=delimiter)
    except csv.Error:
        class Dialect(csv.excel):
            pass

        dialect = Dialect()
        dialect.delimiter = delimiter

    rows = list(csv.reader(io.StringIO(text, newline=""), dialect))
    segments: list[TextSegment] = []
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            if not is_translatable_text(value):
                continue

            def setter(new_value: str, r=row_index, c=column_index) -> None:
                rows[r][c] = new_value

            if segment := _preserving_segment(value, setter):
                segments.append(segment)

    line_ending = "\r\n" if "\r\n" in text else "\n"

    def writer(output: Path) -> None:
        stream = io.StringIO(newline="")
        out_writer = csv.writer(stream, dialect, lineterminator=line_ending)
        out_writer.writerows(rows)
        output.write_text(stream.getvalue(), encoding="utf-8", newline="")

    return StructuredDocument(path, "CSV" if delimiter == "," else "TSV", segments, writer)


def _subtitle_document(path: Path) -> StructuredDocument:
    text, _encoding = _read_text(path)
    suffix = path.suffix.lower()
    lines = text.splitlines(keepends=True)
    segments: list[TextSegment] = []

    if suffix in {".ass", ".ssa"}:
        field_count = 10
        in_events = False
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.lower() == "[events]":
                in_events = True
                continue
            if stripped.startswith("[") and stripped.endswith("]") and stripped.lower() != "[events]":
                in_events = False
                continue
            if not in_events:
                continue
            if stripped.lower().startswith("format:"):
                fields = [item.strip().lower() for item in stripped.split(":", 1)[1].split(",")]
                field_count = max(1, len(fields))
                continue
            if not stripped.lower().startswith("dialogue:"):
                continue

            newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            body = line[len("Dialogue:") :].rstrip("\r\n")
            parts = body.split(",", field_count - 1)
            if len(parts) < field_count:
                continue
            dialogue = parts[-1]

            def setter(value: str, i=index, prefix=parts[:-1], nl=newline) -> None:
                lines[i] = "Dialogue:" + ",".join([*prefix, value]) + nl

            if segment := _preserving_segment(dialogue, setter):
                segments.append(segment)
    else:
        # SRT and WebVTT both identify cue timing with -->. Translate only the
        # text lines following that timing line inside each cue block.
        blocks: list[tuple[int, int]] = []
        start = 0
        for index, line in enumerate(lines + ["\n"]):
            if index == len(lines) or not line.strip():
                if index > start:
                    blocks.append((start, index))
                start = index + 1

        for start, end in blocks:
            timing_index = next((i for i in range(start, end) if "-->" in lines[i]), None)
            if timing_index is None or timing_index + 1 >= end:
                continue
            text_indexes = list(range(timing_index + 1, end))
            raw = "".join(lines[i] for i in text_indexes)

            def setter(value: str, indexes=text_indexes) -> None:
                original = [lines[i] for i in indexes]
                trailing_newline = ""
                if original and original[-1].endswith("\r\n"):
                    trailing_newline = "\r\n"
                elif original and original[-1].endswith("\n"):
                    trailing_newline = "\n"
                replacement = value.rstrip("\r\n") + trailing_newline
                lines[indexes[0]] = replacement
                for extra in indexes[1:]:
                    lines[extra] = ""

            if segment := _preserving_segment(raw, setter):
                segments.append(segment)

    def writer(output: Path) -> None:
        output.write_text("".join(lines), encoding="utf-8", newline="")

    return StructuredDocument(path, suffix[1:].upper(), segments, writer)


def _html_soup_segments(soup: BeautifulSoup) -> list[TextSegment]:
    segments: list[TextSegment] = []
    skip_parents = {"script", "style", "code", "pre", "kbd", "samp", "svg", "math"}
    for node in list(soup.find_all(string=True)):
        if not isinstance(node, NavigableString):
            continue
        parent_name = getattr(node.parent, "name", None)
        if parent_name and str(parent_name).lower() in skip_parents:
            continue
        raw = str(node)
        if not is_translatable_text(raw):
            continue

        def setter(value: str, target=node) -> None:
            target.replace_with(value)

        if segment := _preserving_segment(raw, setter):
            segments.append(segment)
    return segments


def _html_document(path: Path) -> StructuredDocument:
    text, _encoding = _read_text(path)
    soup = BeautifulSoup(text, "html.parser")
    segments = _html_soup_segments(soup)

    def writer(output: Path) -> None:
        output.write_text(str(soup), encoding="utf-8")

    return StructuredDocument(path, "HTML", segments, writer)


def _register_namespaces(xml_bytes: bytes) -> None:
    try:
        for _event, item in ET.iterparse(io.BytesIO(xml_bytes), events=("start-ns",)):
            prefix, uri = item
            try:
                ET.register_namespace(prefix or "", uri)
            except ValueError:
                # Reserved prefixes are already handled by ElementTree.
                pass
    except ET.ParseError:
        pass


def _xml_slots(element: ET.Element) -> list[tuple[ET.Element, str, str]]:
    slots: list[tuple[ET.Element, str, str]] = []

    def walk(node: ET.Element) -> None:
        if node.text:
            slots.append((node, "text", node.text))
        for child in list(node):
            walk(child)
            if child.tail:
                slots.append((child, "tail", child.tail))

    walk(element)
    return slots


def _distribute_translation(value: str, slots: list[tuple[ET.Element, str, str]]) -> None:
    if not slots:
        return
    lengths = [max(1, len(original)) for _node, _attr, original in slots]
    total = sum(lengths)
    cursor = 0
    for index, (node, attr, _original) in enumerate(slots):
        if index == len(slots) - 1:
            chunk = value[cursor:]
        else:
            target = round(len(value) * sum(lengths[: index + 1]) / total)
            chunk = value[cursor:target]
            cursor = target
        setattr(node, attr, chunk)


def _xml_document(path: Path) -> StructuredDocument:
    raw = path.read_bytes()
    _register_namespaces(raw)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise InvalidDocumentError(f"Invalid XML: {exc}") from exc

    segments: list[TextSegment] = []
    skip = {"script", "style", "code", "pre"}

    for element in root.iter():
        local = element.tag.rsplit("}", 1)[-1].lower() if isinstance(element.tag, str) else ""
        if local in skip:
            continue

        if element.text:
            def text_setter(value: str, target=element) -> None:
                target.text = value

            if segment := _preserving_segment(element.text, text_setter):
                segments.append(segment)

        # Tails belong to the parent flow, but storing them on the child is how
        # ElementTree represents mixed XML such as: Hello <b>world</b> !
        if element.tail:
            def tail_setter(value: str, target=element) -> None:
                target.tail = value

            if segment := _preserving_segment(element.tail, tail_setter):
                segments.append(segment)

    def writer(output: Path) -> None:
        output.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))

    return StructuredDocument(path, "XML", segments, writer)


def _key_value_document(path: Path) -> StructuredDocument:
    text, _encoding = _read_text(path)
    lines = text.splitlines(keepends=True)
    segments: list[TextSegment] = []

    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        newline = line[len(body) :]
        stripped = body.lstrip()
        if not stripped or stripped.startswith(("#", ";", "//", "[")):
            continue

        match = re.match(r"^(\s*(?:[-]\s+)?(?:[^:=\n]+?)\s*[:=]\s*)(.*)$", body)
        if not match:
            # YAML list item without an explicit key.
            match = re.match(r"^(\s*-\s+)(.*)$", body)
        if not match:
            continue

        prefix, value = match.groups()
        value = value.strip()
        if not is_translatable_text(value):
            continue
        if value.lower() in {"true", "false", "null", "none", "yes", "no", "on", "off"}:
            continue
        if "://" in value or value.startswith(("/", "./", "../", "${", "$", "~")):
            continue

        quote = ""
        inner = value
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            quote = value[0]
            inner = value[1:-1]
        if not is_translatable_text(inner):
            continue

        def setter(new_value: str, i=index, p=prefix, q=quote, nl=newline) -> None:
            escaped = new_value
            if q:
                escaped = escaped.replace("\\", "\\\\").replace(q, f"\\{q}")
            lines[i] = f"{p}{q}{escaped}{q}{nl}"

        if segment := _preserving_segment(inner, setter):
            segments.append(segment)

    def writer(output: Path) -> None:
        output.write_text("".join(lines), encoding="utf-8", newline="")

    return StructuredDocument(path, "Structured text", segments, writer)


def _zip_entries(path: Path) -> tuple[list[zipfile.ZipInfo], dict[str, bytes]]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            return infos, {info.filename: archive.read(info.filename) for info in infos}
    except (zipfile.BadZipFile, OSError) as exc:
        raise InvalidDocumentError(f"Invalid ZIP-based document: {exc}") from exc


def _write_zip(output: Path, infos: Iterable[zipfile.ZipInfo], data: dict[str, bytes]) -> None:
    with zipfile.ZipFile(output, "w") as archive:
        for info in infos:
            archive.writestr(info, data[info.filename])


def _docx_document(path: Path) -> StructuredDocument:
    infos, data = _zip_entries(path)
    xml_names = [
        name
        for name in data
        if name == "word/document.xml"
        or re.fullmatch(r"word/(?:header|footer)\d+\.xml", name)
        or name in {"word/footnotes.xml", "word/endnotes.xml", "word/comments.xml"}
    ]
    if "word/document.xml" not in data:
        raise InvalidDocumentError("This DOCX has no word/document.xml.")

    segments: list[TextSegment] = []
    trees: dict[str, ET.Element] = {}
    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ET.register_namespace("w", w_ns)
    paragraph_tag = f"{{{w_ns}}}p"
    text_tag = f"{{{w_ns}}}t"

    for name in xml_names:
        raw = data[name]
        _register_namespaces(raw)
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue
        trees[name] = root
        for paragraph in root.iter(paragraph_tag):
            nodes = [node for node in paragraph.iter(text_tag) if node.text is not None]
            if not nodes:
                continue
            raw_text = "".join(node.text or "" for node in nodes)
            slots = [(node, "text", node.text or "") for node in nodes]

            def setter(value: str, target_slots=slots) -> None:
                _distribute_translation(value, target_slots)
                xml_space = "{http://www.w3.org/XML/1998/namespace}space"
                for node, _attr, _old in target_slots:
                    if (node.text or "").startswith(" ") or (node.text or "").endswith(" "):
                        node.set(xml_space, "preserve")

            if segment := _preserving_segment(raw_text, setter):
                segments.append(segment)

    def writer(output: Path) -> None:
        for name, root in trees.items():
            data[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        _write_zip(output, infos, data)

    return StructuredDocument(path, "DOCX", segments, writer)


def _odt_document(path: Path) -> StructuredDocument:
    infos, data = _zip_entries(path)
    raw = data.get("content.xml")
    if raw is None:
        raise InvalidDocumentError("This ODT has no content.xml.")
    _register_namespaces(raw)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise InvalidDocumentError(f"Invalid ODT content.xml: {exc}") from exc

    text_ns = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    paragraph_tags = {f"{{{text_ns}}}p", f"{{{text_ns}}}h"}
    segments: list[TextSegment] = []
    for paragraph in root.iter():
        if paragraph.tag not in paragraph_tags:
            continue
        slots = _xml_slots(paragraph)
        raw_text = "".join(value for _node, _attr, value in slots)

        def setter(value: str, target_slots=slots) -> None:
            _distribute_translation(value, target_slots)

        if segment := _preserving_segment(raw_text, setter):
            segments.append(segment)

    def writer(output: Path) -> None:
        data["content.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        _write_zip(output, infos, data)

    return StructuredDocument(path, "ODT", segments, writer)


def _epub_document(path: Path) -> StructuredDocument:
    infos, data = _zip_entries(path)
    pages: dict[str, BeautifulSoup] = {}
    segments: list[TextSegment] = []

    for name, raw in list(data.items()):
        if Path(name).suffix.lower() not in _HTML_EXTENSIONS:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        soup = BeautifulSoup(text, "html.parser")
        page_segments = _html_soup_segments(soup)
        if page_segments:
            pages[name] = soup
            segments.extend(page_segments)

    if not pages:
        raise InvalidDocumentError("This EPUB contains no readable HTML/XHTML text pages.")

    def writer(output: Path) -> None:
        for name, soup in pages.items():
            data[name] = str(soup).encode("utf-8")
        _write_zip(output, infos, data)

    return StructuredDocument(path, "EPUB", segments, writer)


def load_document(path: str | Path) -> StructuredDocument:
    """Load a supported document, with UTF-text fallback for unknown extensions."""
    source = Path(path)
    suffix = source.suffix.lower()

    if suffix == ".docx":
        return _docx_document(source)
    if suffix == ".odt":
        return _odt_document(source)
    if suffix == ".epub":
        return _epub_document(source)
    if suffix == ".json":
        return _json_document(source)
    if suffix == ".csv":
        return _csv_document(source, ",")
    if suffix == ".tsv":
        return _csv_document(source, "\t")
    if suffix in _SUBTITLE_EXTENSIONS:
        return _subtitle_document(source)
    if suffix in _HTML_EXTENSIONS:
        return _html_document(source)
    if suffix == ".xml":
        return _xml_document(source)
    if suffix in _KV_EXTENSIONS:
        return _key_value_document(source)

    # Known prose formats and any unknown file that is genuinely text-decodable
    # share the generic paragraph-preserving path. This is what lets Dialect
    # handle arbitrary project-specific text formats without an extension list.
    return _plain_text_document(source)


def translated_filename(source: str | Path, dest_lang: str) -> str:
    path = Path(source)
    suffix = path.suffix
    return f"{path.stem}.{dest_lang}{suffix}" if suffix else f"{path.name}.{dest_lang}"


def split_for_translation(text: str, max_chars: int) -> list[tuple[str, str]]:
    """Split a very large segment while preserving separators for reconstruction.

    Returns ``(body, separator_after_body)`` pairs. In normal documents segments
    are much smaller than ``max_chars``; this is a safety net for giant paragraphs.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return [(text, "")]

    result: list[tuple[str, str]] = []
    remaining = text
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        candidates: list[tuple[int, int]] = []
        for pattern in ("\n\n", "\r\n\r\n", "\n", ". ", "! ", "? ", "; ", ", ", " "):
            pos = window.rfind(pattern, max_chars // 2)
            if pos >= 0:
                candidates.append((pos, len(pattern)))
        if candidates:
            pos, sep_len = max(candidates, key=lambda item: item[0])
            body = remaining[:pos + (0 if remaining[pos:pos + sep_len].isspace() else sep_len - 1)]
            separator_start = len(body)
            separator_match = re.match(r"\s+", remaining[separator_start:])
            separator = separator_match.group(0) if separator_match else " "
            consumed = separator_start + len(separator)
            if not body:
                body = remaining[:max_chars]
                separator = ""
                consumed = max_chars
        else:
            body = remaining[:max_chars]
            separator = ""
            consumed = max_chars
        result.append((body, separator))
        remaining = remaining[consumed:]
    if remaining:
        result.append((remaining, ""))
    return result
