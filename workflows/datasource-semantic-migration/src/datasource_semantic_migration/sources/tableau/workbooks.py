"""Read the datasources embedded in a Tableau workbook (.twb, or the .twb inside a .twbx)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from xml.etree import ElementTree

# Packaged data files a datasource can reference; only their names are read, never their contents.
PACKAGED_DATA_SUFFIXES = {".csv", ".hyper", ".json", ".parquet", ".tde", ".txt", ".xls", ".xlsx"}
# A workbook connected to a datasource published on Tableau Server holds only a proxy to it.
PUBLISHED_CONNECTION_CLASSES = {"sqlproxy"}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_workbook_xml(document: bytes, *, name: str) -> ElementTree.Element:
    """Parse workbook XML, refusing DTD and entity declarations."""
    prefix = document[:8192].upper()
    if b"<!DOCTYPE" in prefix or b"<!ENTITY" in prefix:
        raise ValueError(f"{name} contains a prohibited XML declaration")
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as error:
        raise ValueError(f"Invalid Tableau workbook XML in {name}: {error}") from error
    if local_name(root.tag) != "workbook":
        raise ValueError(f"{name} does not have a workbook root element")
    return root


def datasource_display_name(datasource: ElementTree.Element, position: int) -> str:
    caption = datasource.attrib.get("caption")
    internal_name = datasource.attrib.get("name")
    if caption:
        return caption
    if internal_name and not internal_name.casefold().startswith("federated."):
        return internal_name
    return f"Datasource {position}"


def _connection_classes(datasource: ElementTree.Element) -> set[str]:
    return {
        element.attrib.get("class", "").casefold()
        for element in datasource.iter()
        if local_name(element.tag) == "connection"
    }


def workbook_datasources(
    root: ElementTree.Element,
) -> tuple[list[tuple[str, ElementTree.Element]], list[str]]:
    """Datasources defined in the workbook, and names of published datasources it only references.

    Parameters and other datasources without a connection are not datasources.
    """
    container = next((child for child in root if local_name(child.tag) == "datasources"), None)
    embedded: list[tuple[str, ElementTree.Element]] = []
    published: list[str] = []
    for position, datasource in enumerate(container if container is not None else [], start=1):
        if local_name(datasource.tag) != "datasource":
            continue
        classes = _connection_classes(datasource)
        if not classes:
            continue
        name = datasource_display_name(datasource, position)
        if classes & PUBLISHED_CONNECTION_CLASSES:
            published.append(name)
        else:
            embedded.append((name, datasource))
    return embedded, published


def datasource_document(datasource: ElementTree.Element) -> bytes:
    """The datasource element as a standalone .tds document."""
    return ElementTree.tostring(datasource, encoding="utf-8", xml_declaration=True)


def document_slug(workbook_stem: str, datasource_name: str, document: bytes, used: set[str]) -> str:
    """Readable, unique file name for a datasource taken out of a workbook."""
    base = re.sub(r"[^a-z0-9]+", "-", f"{workbook_stem}--{datasource_name}".casefold()).strip("-")[:100] or "datasource"
    slug = base if base not in used else f"{base}-{hashlib.sha256(document).hexdigest()[:8]}"
    used.add(slug)
    return slug


def extract_references(datasource: ElementTree.Element, member_names: list[str]) -> list[str]:
    """Packaged data files (for example the .hyper extract) the datasource's connections name."""
    candidates = {
        name.casefold(): name for name in member_names if Path(name).suffix.casefold() in PACKAGED_DATA_SUFFIXES
    }
    by_file_name: dict[str, list[str]] = {}
    for key, name in candidates.items():
        by_file_name.setdefault(PurePosixPath(key).name, []).append(name)
    references: set[str] = set()
    for element in datasource.iter():
        for raw_value in element.attrib.values():
            value = unquote(raw_value).replace("\\", "/").removeprefix("./").casefold()
            if value in candidates:
                references.add(candidates[value])
                continue
            references.update(name for key, name in candidates.items() if key in value)
        # Text connections name the file separately from a directory that is often the author's local path.
        file_name = unquote(element.attrib.get("filename", "")).replace("\\", "/").rsplit("/", 1)[-1].casefold()
        if file_name and len(by_file_name.get(file_name, [])) == 1:
            references.add(by_file_name[file_name][0])
    return sorted(references, key=str.casefold)


def has_extract_connection(datasource: ElementTree.Element) -> bool:
    return bool(_connection_classes(datasource) & {"hyper", "dataengine"})
