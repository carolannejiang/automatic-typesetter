"""InCopy story (ICML) writer.

An .icml file is a single-story InCopy interchange document: one XML file a
designer places into an existing InDesign layout with File > Place. The
named paragraph and character styles defined here travel with the story and
merge by name with the target document's styles, so a designer restyles the
whole book by editing style definitions — the pandoc workflow. The wire
format follows pandoc's battle-tested ICML writer: its exact prolog
processing instructions, <Br /> separators between paragraph ranges, real
<Footnote> elements with the <?ACE 4?> auto-number marker, and minimal
anchored Rectangle+Image page items whose links resolve relative to the
.icml's folder (see indesign.extract_link_assets).
"""

from __future__ import annotations

import os

from .indesign import (ICML_MEASURE_PT, IdGen, book_to_story_items,
                       build_styles, esc, fmt, render_story_text)
from .models import Book

_PROLOG = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<?aid style="50" type="snippet" readerVersion="6.0" featureSet="513" product="8.0(370)" ?>
<?aid SnippetType="InCopyInterchange"?>
"""


def _character_group(catalog, used) -> list:
    lines = [
        '\t<RootCharacterStyleGroup Self="bookformatter_character_styles">',
        '\t\t<CharacterStyle Self="$ID/NormalCharacterStyle" Name="Default" />',
    ]
    for style in catalog.character.values():
        if style.name not in used:
            continue
        attrs = "".join(f' {k}="{esc(v, True)}"' for k, v in style.attrs.items())
        name = esc(style.name, True)
        lines.append(f'\t\t<CharacterStyle Self="CharacterStyle/{name}"'
                     f' Name="{name}"{attrs}>')
        lines.append("\t\t\t<Properties>")
        lines.append('\t\t\t\t<BasedOn type="object">$ID/NormalCharacterStyle</BasedOn>')
        if style.font:
            lines.append(f'\t\t\t\t<AppliedFont type="string">{esc(style.font)}</AppliedFont>')
        lines.append("\t\t\t</Properties>")
        lines.append("\t\t</CharacterStyle>")
    lines.append("\t</RootCharacterStyleGroup>")
    return lines


def _paragraph_group(catalog, used) -> list:
    lines = [
        '\t<RootParagraphStyleGroup Self="bookformatter_paragraph_styles">',
        '\t\t<ParagraphStyle Self="$ID/NormalParagraphStyle"'
        ' Name="$ID/NormalParagraphStyle" />',
    ]
    for style in catalog.paragraph_closure(used):
        attrs = "".join(f' {k}="{esc(v, True)}"' for k, v in style.attrs.items())
        name = esc(style.name, True)
        based = (f"ParagraphStyle/{style.based}" if style.based
                 else "$ID/NormalParagraphStyle")
        lines.append(f'\t\t<ParagraphStyle Self="ParagraphStyle/{name}"'
                     f' Name="{name}"{attrs}>')
        lines.append("\t\t\t<Properties>")
        lines.append(f'\t\t\t\t<BasedOn type="object">{esc(based)}</BasedOn>')
        if style.font:
            lines.append(f'\t\t\t\t<AppliedFont type="string">{esc(style.font)}</AppliedFont>')
        if style.leading == "Auto":
            lines.append('\t\t\t\t<Leading type="enumeration">Auto</Leading>')
        elif style.leading is not None:
            lines.append(f'\t\t\t\t<Leading type="unit">{fmt(style.leading)}</Leading>')
        lines.append("\t\t\t</Properties>")
        lines.append("\t\t</ParagraphStyle>")
    lines.append("\t</RootParagraphStyleGroup>")
    return lines


def write_icml(book: Book, path: str, theme: str = "classic",
               font_size: str = "11pt", line_height: str = "1.45",
               chapter_numbers: bool = True) -> None:
    catalog = build_styles(theme, font_size, line_height)
    items = book_to_story_items(book, theme, chapter_numbers)
    ids = IdGen()
    used_p: set = set()
    used_c: set = set()
    story_xml = render_story_text(items, "$ID/NormalCharacterStyle",
                                  ICML_MEASURE_PT, ids, False, used_p, used_c)

    lines = [_PROLOG + '<Document DOMVersion="8.0" Self="bookformatter_doc">']
    lines.extend(_character_group(catalog, used_c))
    lines.extend(_paragraph_group(catalog, used_p))
    title = esc(book.meta.title or "Untitled", True)
    lines.append('\t<Story Self="bookformatter_story" TrackChanges="false"'
                 f' StoryTitle="{title}" AppliedTOCStyle="n"'
                 ' AppliedNamedGrid="n">')
    lines.append('\t\t<StoryPreference OpticalMarginAlignment="true"'
                 ' OpticalMarginSize="12" />')
    lines.append(story_xml)
    lines.append("\t</Story>")
    lines.append("</Document>")

    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
