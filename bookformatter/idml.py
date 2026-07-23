"""InDesign document (IDML) writer.

An .idml file is a UCF zip package InDesign 2020+ opens directly: a
designmap that binds spreads, stories, and resources together, one XML file
per spread and story, and Resources/ files holding styles, fonts, swatches,
and preferences. This writer produces a complete facing-pages book at the
requested trim size: page 1 stands alone as a recto in the first spread,
subsequent spreads carry a verso/recto pair, an A-Master supplies
bottom-centered folio frames (the auto page number travels as the
<?ACE 18?> processing instruction), and the whole book flows as one story
through explicitly threaded per-page text frames.

InDesign does not reflow text when opening an IDML file — it composes into
exactly the frames provided — so the page count is estimated from the word
count and deliberately overshot; trailing empty pages are benign and Smart
Text Reflow (enabled in preferences) deletes them after the first edit. If
the estimate falls short, the last frame shows the red overset badge and
shift-clicking it autoflows the rest.

The package follows the geometry rules of real InDesign exports: everything
in points, y increasing downward, spread origin at the spread center so a
recto page sits at transform "1 0 0 1 0 -H/2" and a verso at "-W -H/2".
Master pages hold margin guides mirrored per side; the frames carry the real
geometry. XML is assembled from strings, never ElementTree, so the ACE
processing instructions survive.
"""

from __future__ import annotations

import math
import os
import zipfile

from . import themes
from .indesign import (IdGen, book_to_story_items, build_styles, esc, fmt,
                       render_story_text)
from .models import Book

MIMETYPE = b"application/vnd.adobe.indesign-idml-package"

_PLAIN_CHAR = "CharacterStyle/$ID/[No character style]"

_XML_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

_PKG_NS = "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"

_AID_PI = ('<?aid style="50" type="document" readerVersion="6.0"'
           ' featureSet="257" product="7.5(142)" ?>\n')

_CONTAINER = _XML_HEADER + """<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
\t<rootfiles>
\t\t<rootfile full-path="designmap.xml" media-type="text/xml"/>
\t</rootfiles>
</container>
"""

_TAGS_BODY = """\t<XMLTag Self="XMLTag/Root" Name="Root">
\t\t<Properties>
\t\t\t<TagColor type="enumeration">LightBlue</TagColor>
\t\t</Properties>
\t</XMLTag>"""

_BACKING_BODY = """\t<XmlStory Self="uae" AppliedTOCStyle="n" TrackChanges="false" StoryTitle="$ID/" AppliedNamedGrid="n">
\t\t<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/$ID/NormalParagraphStyle">
\t\t\t<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
\t\t\t\t<XMLElement Self="di2" MarkupTag="XMLTag/Root"/>
\t\t\t\t<Content>﻿</Content>
\t\t\t</CharacterStyleRange>
\t\t</ParagraphStyleRange>
\t</XmlStory>"""

_GRAPHIC_BODY = """\t<Color Self="Color/Black" Model="Process" Space="CMYK" ColorValue="0 0 0 100" ColorOverride="Specialblack" AlternateSpace="NoAlternateColor" AlternateColorValue="" Name="Black" ColorEditable="false" ColorRemovable="false" Visible="true" SwatchCreatorID="7937"/>
\t<Color Self="Color/Paper" Model="Process" Space="CMYK" ColorValue="0 0 0 0" ColorOverride="Specialpaper" AlternateSpace="NoAlternateColor" AlternateColorValue="" Name="Paper" ColorEditable="true" ColorRemovable="false" Visible="true" SwatchCreatorID="7937"/>
\t<Color Self="Color/Registration" Model="Registration" Space="CMYK" ColorValue="100 100 100 100" ColorOverride="Specialregistration" AlternateSpace="NoAlternateColor" AlternateColorValue="" Name="Registration" ColorEditable="false" ColorRemovable="false" Visible="true" SwatchCreatorID="7937"/>
\t<Ink Self="Ink/$ID/Process Cyan" Name="$ID/Process Cyan" Angle="75" ConvertToProcess="false" Frequency="70" NeutralDensity="0.61" PrintInk="true" TrapOrder="1" InkType="Normal"/>
\t<Ink Self="Ink/$ID/Process Magenta" Name="$ID/Process Magenta" Angle="15" ConvertToProcess="false" Frequency="70" NeutralDensity="0.76" PrintInk="true" TrapOrder="2" InkType="Normal"/>
\t<Ink Self="Ink/$ID/Process Yellow" Name="$ID/Process Yellow" Angle="0" ConvertToProcess="false" Frequency="70" NeutralDensity="0.16" PrintInk="true" TrapOrder="3" InkType="Normal"/>
\t<Ink Self="Ink/$ID/Process Black" Name="$ID/Process Black" Angle="45" ConvertToProcess="false" Frequency="70" NeutralDensity="1.7" PrintInk="true" TrapOrder="4" InkType="Normal"/>
\t<Swatch Self="Swatch/None" Name="None" ColorEditable="false" ColorRemovable="false" Visible="true" SwatchCreatorID="7937"/>
\t<StrokeStyle Self="StrokeStyle/$ID/Solid" Name="$ID/Solid"/>"""

_LANGUAGE = ('\t<Language Self="Language/$ID/English%3a USA"'
             ' Name="$ID/English: USA" SingleQuotes="‘’"'
             ' DoubleQuotes="“”" PrimaryLanguageName="$ID/English"'
             ' SublanguageName="$ID/USA" Id="269"'
             ' HyphenationVendor="Proximity" SpellingVendor="Proximity"/>')

_LAYER = """\t<Layer Self="ua4" Name="Layer 1" Visible="true" Locked="false" IgnoreWrap="false" ShowGuides="true" LockGuides="false" UI="true" Expendable="true" Printable="true">
\t\t<Properties>
\t\t\t<LayerColor type="enumeration">LightBlue</LayerColor>
\t\t</Properties>
\t</Layer>"""

_STYLE_TAIL = """\t<TOCStyle Self="TOCStyle/$ID/DefaultTOCStyleName" TitleStyle="ParagraphStyle/$ID/[No paragraph style]" Title="Contents" Name="$ID/DefaultTOCStyleName" RunIn="false" IncludeHidden="false" IncludeBookDocuments="false" CreateBookmarks="true" NumberedParagraphs="IncludeFullParagraph"/>
\t<RootCellStyleGroup Self="u7a">
\t\t<CellStyle Self="CellStyle/$ID/[None]" AppliedParagraphStyle="ParagraphStyle/$ID/[No paragraph style]" Name="$ID/[None]"/>
\t</RootCellStyleGroup>
\t<RootTableStyleGroup Self="u7c">
\t\t<TableStyle Self="TableStyle/$ID/[No table style]" Name="$ID/[No table style]"/>
\t</RootTableStyleGroup>
\t<RootObjectStyleGroup Self="u85">
\t\t<ObjectStyle Self="ObjectStyle/$ID/[None]" Name="$ID/[None]" AppliedParagraphStyle="ParagraphStyle/$ID/[No paragraph style]" FillColor="Swatch/None" FillTint="-1" StrokeWeight="0" MiterLimit="4" EndCap="ButtEndCap" EndJoin="MiterEndJoin" StrokeType="StrokeStyle/$ID/Solid" LeftLineEnd="None" RightLineEnd="None" StrokeColor="Swatch/None" StrokeTint="-1" GapColor="Swatch/None" GapTint="-1" StrokeAlignment="CenterAlignment" Nonprinting="false" GradientFillAngle="0" GradientStrokeAngle="0" AppliedNamedGrid="n">
\t\t\t<Properties>
\t\t\t\t<BasedOn type="string">n</BasedOn>
\t\t\t</Properties>
\t\t</ObjectStyle>
\t</RootObjectStyleGroup>
\t<TrapPreset Self="TrapPreset/$ID/kDefaultTrapStyleName" Name="$ID/kDefaultTrapStyleName" DefaultTrapWidth="0.25" BlackWidth="0.5" TrapJoin="MiterEndJoin" TrapEnd="MiterTrapEnds" ObjectsToImages="true" ImagesToImages="true" InternalImages="false" OneBitImages="true" ImagePlacement="CenterEdges" StepThreshold="10" BlackColorThreshold="100" BlackDensity="1.6" SlidingTrapThreshold="70" ColorReduction="100"/>"""

_FLATTENER = """\t\t<FlattenerPreference LineArtAndTextResolution="300" GradientAndMeshResolution="150" ClipComplexRegions="false" ConvertAllStrokesToOutlines="false" ConvertAllTextToOutlines="false">
\t\t\t<Properties>
\t\t\t\t<RasterVectorBalance type="double">50</RasterVectorBalance>
\t\t\t</Properties>
\t\t</FlattenerPreference>"""

_STORY_HEAD = ('\t\t<StoryPreference OpticalMarginAlignment="false"'
               ' OpticalMarginSize="12" FrameType="TextFrameType"'
               ' StoryOrientation="Horizontal"'
               ' StoryDirection="LeftToRightDirection"/>\n'
               '\t\t<InCopyExportOption IncludeGraphicProxies="true"'
               ' IncludeAllResources="false"/>')

_FONT_FACES = {
    "Minion Pro": ("OpenTypeCFF", (
        ("Regular", "MinionPro-Regular"), ("Italic", "MinionPro-It"),
        ("Bold", "MinionPro-Bold"), ("Bold Italic", "MinionPro-BoldIt"),
    )),
    "Myriad Pro": ("OpenTypeCFF", (
        ("Regular", "MyriadPro-Regular"), ("Italic", "MyriadPro-It"),
        ("Bold", "MyriadPro-Bold"), ("Bold Italic", "MyriadPro-BoldIt"),
    )),
    "Courier New": ("TrueType", (
        ("Regular", "CourierNewPSMT"), ("Italic", "CourierNewPS-ItalicMT"),
        ("Bold", "CourierNewPS-BoldMT"),
        ("Bold Italic", "CourierNewPS-BoldItalicMT"),
    )),
}


def _pkg(kind: str, body: str) -> str:
    return (f'{_XML_HEADER}<idPkg:{kind} xmlns:idPkg="{_PKG_NS}"'
            f' DOMVersion="7.5">\n{body}\n</idPkg:{kind}>\n')


class _Geometry:
    """Page and frame geometry for one trim/theme choice, in points."""

    def __init__(self, trim: str, theme: str):
        width_in, height_in = themes.TRIM_SIZES.get(
            trim, themes.TRIM_SIZES["6x9"])
        margins = themes.theme_margins(theme, width_in, height_in)
        self.width = round(width_in * 72, 2)
        self.height = round(height_in * 72, 2)
        self.top = round(float(margins["M_TOP"]) * 72, 2)
        self.bottom = round(float(margins["M_BOTTOM"]) * 72, 2)
        self.inner = round(float(margins["M_IN"]) * 72, 2)
        self.outer = round(float(margins["M_OUT"]) * 72, 2)
        self.measure = round(self.width - self.inner - self.outer, 2)
        self.text_height = round(self.height - self.top - self.bottom, 2)
        self.text_bottom = round(self.height - self.bottom, 2)

    def page_transform(self, recto: bool) -> str:
        x = 0.0 if recto else -self.width
        return f"1 0 0 1 {fmt(x)} {fmt(-self.height / 2)}"

    def text_box(self, recto: bool):
        left = self.inner if recto else self.outer
        right = self.width - (self.outer if recto else self.inner)
        return left, self.top, right, self.text_bottom


def _estimate_pages(book: Book, catalog, geometry: _Geometry) -> int:
    """Pages needed for the story, overshot: InDesign will not add pages at
    open time, and empty trailing pages are cheaper than overset text."""
    lines = max(1.0, geometry.text_height // max(catalog.leading, 1.0))
    chars_per_line = max(10.0, geometry.measure / (0.52 * catalog.body_pt))
    words_per_page = max(40.0, lines * chars_per_line / 5.8)
    pages = (math.ceil(book.word_count() / words_per_page * 1.3)
             + 2 + math.ceil(1.5 * len(book.chapters)) + 2)
    return max(pages + pages % 2, 4)


def _path_points(x0, y0, x1, y1, ind: str) -> str:
    corners = ((x0, y0), (x0, y1), (x1, y1), (x1, y0))
    return "\n".join(
        f'{ind}<PathPointType Anchor="{fmt(x)} {fmt(y)}"'
        f' LeftDirection="{fmt(x)} {fmt(y)}"'
        f' RightDirection="{fmt(x)} {fmt(y)}"/>'
        for x, y in corners
    )


def _text_frame(self_id, story, prev, nxt, transform, box, measure,
                wrap: bool) -> str:
    x0, y0, x1, y1 = box
    lines = [
        f'\t\t<TextFrame Self="{self_id}" ParentStory="{story}"'
        f' PreviousTextFrame="{prev}" NextTextFrame="{nxt}"'
        f' ContentType="TextType" ItemLayer="ua4" Locked="false"'
        f' AppliedObjectStyle="ObjectStyle/$ID/[None]" Visible="true"'
        f' Name="$ID/" ItemTransform="{transform}">',
        "\t\t\t<Properties>",
        "\t\t\t\t<PathGeometry>",
        '\t\t\t\t\t<GeometryPathType PathOpen="false">',
        "\t\t\t\t\t\t<PathPointArray>",
        _path_points(x0, y0, x1, y1, "\t" * 7),
        "\t\t\t\t\t\t</PathPointArray>",
        "\t\t\t\t\t</GeometryPathType>",
        "\t\t\t\t</PathGeometry>",
        "\t\t\t</Properties>",
        f'\t\t\t<TextFramePreference TextColumnCount="1"'
        f' TextColumnFixedWidth="{fmt(measure)}"'
        f' VerticalJustification="TopAlign"/>',
    ]
    if wrap:
        lines += [
            '\t\t\t<TextWrapPreference Inverse="false"'
            ' ApplyToMasterPageOnly="false" TextWrapSide="BothSides"'
            ' TextWrapMode="None">',
            "\t\t\t\t<Properties>",
            '\t\t\t\t\t<TextWrapOffset Top="0" Left="0" Bottom="0" Right="0"/>',
            "\t\t\t\t</Properties>",
            "\t\t\t</TextWrapPreference>",
        ]
    lines.append("\t\t</TextFrame>")
    return "\n".join(lines)


def _page(self_id, name, geometry: _Geometry, recto: bool,
          applied_master: str) -> str:
    left = geometry.inner if recto else geometry.outer
    right = geometry.outer if recto else geometry.inner
    return "\n".join([
        f'\t\t<Page Self="{self_id}"'
        f' GeometricBounds="0 0 {fmt(geometry.height)} {fmt(geometry.width)}"'
        f' ItemTransform="{geometry.page_transform(recto)}" Name="{name}"'
        f' AppliedTrapPreset="TrapPreset/$ID/kDefaultTrapStyleName"'
        f' OverrideList="" AppliedMaster="{applied_master}"'
        f' MasterPageTransform="1 0 0 1 0 0" TabOrder=""'
        f' GridStartingPoint="TopOutside" UseMasterGrid="true">',
        "\t\t\t<Properties>",
        '\t\t\t\t<PageColor type="enumeration">UseMasterColor</PageColor>',
        "\t\t\t</Properties>",
        f'\t\t\t<MarginPreference ColumnCount="1" ColumnGutter="12"'
        f' Top="{fmt(geometry.top)}" Bottom="{fmt(geometry.bottom)}"'
        f' Left="{fmt(left)}" Right="{fmt(right)}"'
        f' ColumnDirection="Horizontal"'
        f' ColumnsPositions="0 {fmt(geometry.measure)}"/>',
        "\t\t</Page>",
    ])


def _master_xml(geometry: _Geometry) -> str:
    folio_top = round(geometry.text_bottom + 18, 2)
    folio_bottom = round(geometry.text_bottom + 36, 2)
    frames = []
    for frame_id, story, recto in (("u113", "u111", False),
                                   ("u114", "u112", True)):
        x0, _, x1, _ = geometry.text_box(recto)
        frames.append(_text_frame(
            frame_id, story, "n", "n", geometry.page_transform(recto),
            (x0, folio_top, x1, folio_bottom), geometry.measure, wrap=False))
    body = "\n".join([
        '\t<MasterSpread Self="ub8" ItemTransform="1 0 0 1 0 0"'
        ' Name="A-Master" NamePrefix="A" BaseName="Master"'
        ' ShowMasterItems="true" PageCount="2" OverriddenPageItemProps="">',
        "\t\t<Properties>",
        '\t\t\t<PageColor type="enumeration">UseMasterColor</PageColor>',
        "\t\t</Properties>",
        _page("ub9", "A", geometry, recto=False, applied_master="n"),
        _page("uba", "A", geometry, recto=True, applied_master="n"),
        "\n".join(frames),
        "\t</MasterSpread>",
    ])
    return _pkg("MasterSpread", body)


def _spread_xml(spread_id, index, page_numbers, frame_ids, total_frames,
                geometry: _Geometry) -> str:
    offset = round(index * (geometry.height + 180), 2)
    lines = [
        f'\t<Spread Self="{spread_id}" FlattenerOverride="Default"'
        f' AllowPageShuffle="true" ItemTransform="1 0 0 1 0 {fmt(offset)}"'
        f' ShowMasterItems="true" PageCount="{len(page_numbers)}"'
        f' BindingLocation="{0 if index == 0 else 1}"'
        f' PageTransitionType="None" PageTransitionDirection="NotApplicable"'
        f' PageTransitionDuration="Medium">',
        _FLATTENER,
    ]
    for number in page_numbers:
        lines.append(_page(f"uc{number}", str(number), geometry,
                           recto=number % 2 == 1, applied_master="ub8"))
    for number, frame_id in zip(page_numbers, frame_ids):
        recto = number % 2 == 1
        ordinal = int(frame_id[2:])
        prev = "n" if ordinal == 1 else f"uf{ordinal - 1}"
        nxt = "n" if ordinal == total_frames else f"uf{ordinal + 1}"
        lines.append(_text_frame(
            frame_id, "u100", prev, nxt, geometry.page_transform(recto),
            geometry.text_box(recto), geometry.measure, wrap=True))
    lines.append("\t</Spread>")
    return _pkg("Spread", "\n".join(lines))


def _style_properties(based, font, leading, ind: str) -> list:
    lines = [f"{ind}<Properties>",
             f'{ind}\t<BasedOn type="string">{esc(based)}</BasedOn>',
             f'{ind}\t<PreviewColor type="enumeration">Nothing</PreviewColor>']
    if font:
        lines.append(f'{ind}\t<AppliedFont type="string">{esc(font)}</AppliedFont>')
    if leading == "Auto":
        lines.append(f'{ind}\t<Leading type="enumeration">Auto</Leading>')
    elif leading is not None:
        lines.append(f'{ind}\t<Leading type="unit">{fmt(leading)}</Leading>')
    lines.append(f"{ind}</Properties>")
    return lines


def _styles_xml(catalog) -> str:
    body_font = catalog.fonts[0]
    lines = ['\t<RootCharacterStyleGroup Self="u6b">',
             '\t\t<CharacterStyle Self="CharacterStyle/$ID/[No character style]"'
             ' Imported="false" Name="$ID/[No character style]"/>']
    for style in catalog.character.values():
        attrs = "".join(f' {k}="{esc(v, True)}"' for k, v in style.attrs.items())
        name = esc(style.name, True)
        lines.append(f'\t\t<CharacterStyle Self="CharacterStyle/{name}"'
                     f' Imported="false" Name="{name}"{attrs}>')
        lines.extend(_style_properties("$ID/[No character style]", style.font,
                                       None, "\t\t\t"))
        lines.append("\t\t</CharacterStyle>")
    lines.append("\t</RootCharacterStyleGroup>")

    lines.append('\t<RootParagraphStyleGroup Self="u6a">')
    lines.append(
        '\t\t<ParagraphStyle Self="ParagraphStyle/$ID/[No paragraph style]"'
        ' Name="$ID/[No paragraph style]" Imported="false"'
        ' NextStyle="ParagraphStyle/$ID/[No paragraph style]"'
        f' FillColor="Color/Black" FontStyle="Regular"'
        f' PointSize="{fmt(catalog.body_pt)}" HorizontalScale="100"'
        ' KerningMethod="$ID/Metrics" Ligatures="true" Tracking="0"'
        ' Composer="HL Composer" Capitalization="Normal"'
        ' StrokeColor="Swatch/None" Hyphenation="true" AutoLeading="120"'
        ' AppliedLanguage="$ID/English: USA" LeftIndent="0" RightIndent="0"'
        ' FirstLineIndent="0" SpaceBefore="0" SpaceAfter="0"'
        ' StartParagraph="Anywhere" Justification="LeftAlign">')
    lines.append("\t\t\t<Properties>")
    lines.append(f'\t\t\t\t<AppliedFont type="string">{esc(body_font)}</AppliedFont>')
    lines.append("\t\t\t</Properties>")
    lines.append("\t\t</ParagraphStyle>")
    lines.append(
        '\t\t<ParagraphStyle Self="ParagraphStyle/$ID/NormalParagraphStyle"'
        ' Name="$ID/NormalParagraphStyle" Imported="false"'
        ' NextStyle="ParagraphStyle/$ID/NormalParagraphStyle">')
    lines.extend(_style_properties("$ID/[No paragraph style]", None, None,
                                   "\t\t\t"))
    lines.append("\t\t</ParagraphStyle>")
    for style in catalog.paragraph.values():
        attrs = "".join(f' {k}="{esc(v, True)}"' for k, v in style.attrs.items())
        name = esc(style.name, True)
        based = (f"ParagraphStyle/{style.based}" if style.based
                 else "ParagraphStyle/$ID/[No paragraph style]")
        lines.append(f'\t\t<ParagraphStyle Self="ParagraphStyle/{name}"'
                     f' Name="{name}" Imported="false"{attrs}>')
        lines.extend(_style_properties(based, style.font, style.leading,
                                       "\t\t\t"))
        lines.append("\t\t</ParagraphStyle>")
    lines.append("\t</RootParagraphStyleGroup>")
    lines.append(_STYLE_TAIL)
    return _pkg("Styles", "\n".join(lines))


def _fonts_xml(catalog) -> str:
    lines = []
    for i, family in enumerate(catalog.fonts):
        family_id = f"dif{i}"
        font_type, faces = _FONT_FACES.get(
            family, ("OpenTypeCFF", (("Regular", family.replace(" ", "")),)))
        lines.append(f'\t<FontFamily Self="{family_id}" Name="{esc(family, True)}">')
        for face, postscript in faces:
            full = family if face == "Regular" else f"{family} {face}"
            lines.append(
                f'\t\t<Font Self="{family_id}Fontn{esc(family, True)} {face}"'
                f' FontFamily="{esc(family, True)}" Name="{esc(family, True)} {face}"'
                f' PostScriptName="{postscript}" Status="Installed"'
                f' FontStyleName="{face}" FontType="{font_type}"'
                f' WritingScript="0" FullName="{esc(full, True)}"'
                f' FullNameNative="{esc(full, True)}"'
                f' FontStyleNameNative="{face}" PlatformName="$ID/"/>')
        lines.append("\t</FontFamily>")
    return _pkg("Fonts", "\n".join(lines))


def _preferences_xml(geometry: _Geometry, pages: int) -> str:
    body = "\n".join([
        '\t<TextPreference TypographersQuotes="true" SuperscriptSize="58.3"'
        ' SuperscriptPosition="33.3" SubscriptSize="58.3"'
        ' SubscriptPosition="33.3" SmallCap="70" UseOpticalSize="true"'
        ' SmartTextReflow="true" AddPages="EndOfStory"'
        ' LimitToMasterTextFrames="false" PreserveFacingPageSpreads="false"'
        ' DeleteEmptyPages="true"/>',
        '\t<StoryPreference OpticalMarginAlignment="false"'
        ' OpticalMarginSize="12" FrameType="TextFrameType"'
        ' StoryOrientation="Horizontal" StoryDirection="LeftToRightDirection"/>',
        f'\t<DocumentPreference PageHeight="{fmt(geometry.height)}"'
        f' PageWidth="{fmt(geometry.width)}" PagesPerDocument="{pages}"'
        ' FacingPages="true" DocumentBleedTopOffset="0"'
        ' DocumentBleedBottomOffset="0" DocumentBleedInsideOrLeftOffset="0"'
        ' DocumentBleedOutsideOrRightOffset="0"'
        ' DocumentBleedUniformSize="true" SlugTopOffset="0"'
        ' SlugBottomOffset="0" SlugInsideOrLeftOffset="0"'
        ' SlugRightOrOutsideOffset="0" DocumentSlugUniformSize="false"'
        ' PreserveLayoutWhenShuffling="true" AllowPageShuffle="true"'
        ' OverprintBlack="true" ColumnGuideLocked="true" Intent="PrintIntent"'
        ' PageBinding="LeftToRight" ColumnDirection="Horizontal"'
        ' MasterTextFrame="false" SnippetImportUsesOriginalLocation="false">',
        "\t\t<Properties>",
        '\t\t\t<ColumnGuideColor type="enumeration">Violet</ColumnGuideColor>',
        '\t\t\t<MarginGuideColor type="enumeration">Magenta</MarginGuideColor>',
        "\t\t</Properties>",
        "\t</DocumentPreference>",
        f'\t<MarginPreference ColumnCount="1" ColumnGutter="12"'
        f' Top="{fmt(geometry.top)}" Bottom="{fmt(geometry.bottom)}"'
        f' Left="{fmt(geometry.inner)}" Right="{fmt(geometry.outer)}"'
        f' ColumnDirection="Horizontal"'
        f' ColumnsPositions="0 {fmt(geometry.measure)}"/>',
        '\t<ViewPreference PointsPerInch="72"'
        ' HorizontalMeasurementUnits="Inches"'
        ' VerticalMeasurementUnits="Inches" HorizontalCustomPoints="12"'
        ' VerticalCustomPoints="12" StrokeMeasurementUnits="Points"'
        ' LineMeasurementUnits="Points" TypographicMeasurementUnits="Points"'
        ' TextSizeMeasurementUnits="Points"'
        ' PrintDialogMeasurementUnits="Inches" RulerOrigin="SpreadOrigin"'
        ' ShowRulers="true" ShowFrameEdges="true" GuideSnaptoZone="4"'
        ' CursorKeyIncrement="1" ShowNotes="true"/>',
    ])
    return _pkg("Preferences", body)


def _folio_story_xml(story_id: str) -> str:
    body = "\n".join([
        f'\t<Story Self="{story_id}" AppliedTOCStyle="n" TrackChanges="false"'
        ' StoryTitle="$ID/" AppliedNamedGrid="n">',
        _STORY_HEAD,
        '\t\t<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Folio">',
        f'\t\t\t<CharacterStyleRange AppliedCharacterStyle="{_PLAIN_CHAR}">',
        "\t\t\t\t<Content><?ACE 18?></Content>",
        "\t\t\t</CharacterStyleRange>",
        "\t\t</ParagraphStyleRange>",
        "\t</Story>",
    ])
    return _pkg("Story", body)


def _designmap_xml(spread_srcs, pages: int) -> str:
    lines = [
        _XML_HEADER + _AID_PI +
        f'<Document xmlns:idPkg="{_PKG_NS}" DOMVersion="7.5" Self="d"'
        ' StoryList="u111 u112 u100 uae" ZeroPoint="0 0" ActiveLayer="ua4">',
        _LANGUAGE,
        '\t<idPkg:Graphic src="Resources/Graphic.xml"/>',
        '\t<idPkg:Fonts src="Resources/Fonts.xml"/>',
        '\t<idPkg:Styles src="Resources/Styles.xml"/>',
        '\t<idPkg:Preferences src="Resources/Preferences.xml"/>',
        '\t<idPkg:Tags src="XML/Tags.xml"/>',
        _LAYER,
        '\t<idPkg:MasterSpread src="MasterSpreads/MasterSpread_ub8.xml"/>',
    ]
    lines.extend(f'\t<idPkg:Spread src="{src}"/>' for src in spread_srcs)
    lines += [
        f'\t<Section Self="u11c" Length="{pages}" Name=""'
        ' ContinueNumbering="true" IncludeSectionPrefix="false" Marker=""'
        ' PageStart="uc1" SectionPrefix="">',
        "\t\t<Properties>",
        '\t\t\t<PageNumberStyle type="enumeration">Arabic</PageNumberStyle>',
        "\t\t</Properties>",
        "\t</Section>",
        '\t<idPkg:BackingStory src="XML/BackingStory.xml"/>',
        '\t<idPkg:Story src="Stories/Story_u100.xml"/>',
        '\t<idPkg:Story src="Stories/Story_u111.xml"/>',
        '\t<idPkg:Story src="Stories/Story_u112.xml"/>',
        "</Document>",
    ]
    return "\n".join(lines) + "\n"


def write_idml(book: Book, path: str, theme: str = "classic",
               trim: str = "6x9", font_size: str = "11pt",
               line_height: str = "1.45", chapter_start: str = "right",
               chapter_numbers: bool = True) -> None:
    catalog = build_styles(theme, font_size, line_height)
    geometry = _Geometry(trim, theme)

    items = book_to_story_items(book, theme, chapter_numbers)
    if chapter_start != "right":
        for para in items:
            if para.start == "NextOddPage":
                para.start = "NextPage"

    used_p: set = set()
    used_c: set = set()
    story_body = render_story_text(items, _PLAIN_CHAR, geometry.measure,
                                   IdGen(), True, used_p, used_c)
    story_xml = _pkg("Story", "\n".join([
        '\t<Story Self="u100" AppliedTOCStyle="n" TrackChanges="false"'
        ' StoryTitle="$ID/" AppliedNamedGrid="n">',
        _STORY_HEAD,
        story_body,
        "\t</Story>",
    ]))

    pages = _estimate_pages(book, catalog, geometry)
    # Spreads: lone recto first, verso/recto pairs, lone verso last.
    groups = [[1]] + [[n, n + 1] for n in range(2, pages, 2)]
    if pages > 1:
        groups.append([pages])
    spreads = []
    for index, numbers in enumerate(groups):
        spread_id = f"us{index}"
        src = f"Spreads/Spread_{spread_id}.xml"
        frame_ids = [f"uf{n}" for n in numbers]
        spreads.append((src, _spread_xml(spread_id, index, numbers,
                                         frame_ids, pages, geometry)))

    files = [
        ("designmap.xml", _designmap_xml([src for src, _ in spreads], pages)),
        ("META-INF/container.xml", _CONTAINER),
        ("Resources/Graphic.xml", _pkg("Graphic", _GRAPHIC_BODY)),
        ("Resources/Fonts.xml", _fonts_xml(catalog)),
        ("Resources/Styles.xml", _styles_xml(catalog)),
        ("Resources/Preferences.xml", _preferences_xml(geometry, pages)),
        ("XML/Tags.xml", _pkg("Tags", _TAGS_BODY)),
        ("XML/BackingStory.xml", _pkg("BackingStory", _BACKING_BODY)),
        ("MasterSpreads/MasterSpread_ub8.xml", _master_xml(geometry)),
    ]
    files.extend(spreads)
    files += [
        ("Stories/Story_u100.xml", story_xml),
        ("Stories/Story_u111.xml", _folio_story_xml("u111")),
        ("Stories/Story_u112.xml", _folio_story_xml("u112")),
    ]

    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        info = zipfile.ZipInfo("mimetype", date_time=(1980, 1, 1, 0, 0, 0))
        zf.writestr(info, MIMETYPE, compress_type=zipfile.ZIP_STORED)
        for name, text in files:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, text.encode("utf-8"))
