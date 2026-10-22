"""Small Word, Excel and PowerPoint files for the tests, written by hand as the
zip of XML parts such a file is — no library of those formats is needed to
make them. Each returns the bytes of the file."""

from __future__ import annotations

import html
import io
import zipfile

_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _zip(parts: dict[str, str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(name, _HEAD + text if text.startswith("<") and not text.startswith("<html") else text)
    return out.getvalue()


def _relationships(*items: tuple[str, str, str, bool]) -> str:
    rows = "".join(
        f'<Relationship Id="{ident}" Type="{kind}" Target="{target}"' + (' TargetMode="External"' if external else "") + "/>"
        for ident, kind, target, external in items
    )
    return f'<Relationships xmlns="{_RELS}">{rows}</Relationships>'


def _types(defaults: dict[str, str], overrides: dict[str, str]) -> str:
    rows = "".join(f'<Default Extension="{e}" ContentType="{c}"/>' for e, c in defaults.items())
    rows += "".join(f'<Override PartName="{p}" ContentType="{c}"/>' for p, c in overrides.items())
    return f'<Types xmlns="{_TYPES}">{rows}</Types>'


RELS_TYPE = "application/vnd.openxmlformats-package.relationships+xml"

# A run of text that reads as a tag: the text of a file, never a tag of the page.
MARKUP = '<img src=x onerror="window.hacked = 1">'

# What the Word file carries beyond its text: a link a script runs from, a web
# link, and a chunk of HTML of its own that a reader must not draw.
WORD_TEXT = "Hello from Word"
WORD_SCRIPT_LINK = "script link"
WORD_WEB_LINK = "web link"
WORD_CHUNK_TEXT = "EMBEDDED HTML"


def docx() -> bytes:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    r = _DOC
    body = (
        f"<w:p><w:r><w:t>{WORD_TEXT}</w:t></w:r></w:p>"
        f"<w:p><w:r><w:t>{html.escape(MARKUP)}</w:t></w:r></w:p>"
        f'<w:p><w:hyperlink r:id="rId2"><w:r><w:t>{WORD_SCRIPT_LINK}</w:t></w:r></w:hyperlink></w:p>'
        f'<w:p><w:hyperlink r:id="rId3"><w:r><w:t>{WORD_WEB_LINK}</w:t></w:r></w:hyperlink></w:p>'
        '<w:altChunk r:id="rId4"/>'
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
    )
    return _zip({
        "[Content_Types].xml": _types(
            {"rels": RELS_TYPE, "xml": "application/xml", "html": "text/html"},
            {"/word/document.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"},
        ),
        "_rels/.rels": _relationships(("rId1", f"{_DOC}/officeDocument", "word/document.xml", False)),
        "word/document.xml": f'<w:document xmlns:w="{w}" xmlns:r="{r}"><w:body>{body}</w:body></w:document>',
        "word/_rels/document.xml.rels": _relationships(
            ("rId2", f"{_DOC}/hyperlink", "javascript:window.hacked=1", True),
            ("rId3", f"{_DOC}/hyperlink", "https://example.com/page", True),
            ("rId4", f"{_DOC}/aFChunk", "afchunk.html", False),
        ),
        "word/afchunk.html": f'<html><body><p id="smuggled">{WORD_CHUNK_TEXT}</p><script>window.hacked=1</script></body></html>',
    })


# Two sheets; a cell that holds markup is text and stays text.
SHEET_ONE = ("Sales", [["Item", "Amount"], ["Apples", "12"], ["<b>Pears</b>", "7"]])
SHEET_TWO = ("Costs", [["Cost", "Value"], ["Rent", "900"]])


def xlsx() -> bytes:
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    def sheet(rows: list[list[str]]) -> str:
        def cell(column: int, number: int, value: str) -> str:
            escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            ref = f"{'AB'[column]}{number}"
            if value.isdigit():
                return f'<c r="{ref}"><v>{value}</v></c>'
            return f'<c r="{ref}" t="inlineStr"><is><t>{escaped}</t></is></c>'

        body = "".join(
            f'<row r="{n}">' + "".join(cell(c, n, v) for c, v in enumerate(row)) + "</row>"
            for n, row in enumerate(rows, 1)
        )
        return f'<worksheet xmlns="{main}"><sheetData>{body}</sheetData></worksheet>'

    sheet_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
    return _zip({
        "[Content_Types].xml": _types(
            {"rels": RELS_TYPE, "xml": "application/xml"},
            {
                "/xl/workbook.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
                "/xl/worksheets/sheet1.xml": sheet_type,
                "/xl/worksheets/sheet2.xml": sheet_type,
            },
        ),
        "_rels/.rels": _relationships(("rId1", f"{_DOC}/officeDocument", "xl/workbook.xml", False)),
        "xl/workbook.xml": (
            f'<workbook xmlns="{main}" xmlns:r="{_DOC}"><sheets>'
            f'<sheet name="{SHEET_ONE[0]}" sheetId="1" r:id="rId1"/><sheet name="{SHEET_TWO[0]}" sheetId="2" r:id="rId2"/>'
            "</sheets></workbook>"
        ),
        "xl/_rels/workbook.xml.rels": _relationships(
            ("rId1", f"{_DOC}/worksheet", "worksheets/sheet1.xml", False),
            ("rId2", f"{_DOC}/worksheet", "worksheets/sheet2.xml", False),
        ),
        "xl/worksheets/sheet1.xml": sheet(SHEET_ONE[1]),
        "xl/worksheets/sheet2.xml": sheet(SHEET_TWO[1]),
    })


SLIDE_ONE = "First slide"
SLIDE_TWO = "Second slide"


def pptx() -> bytes:
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    r = _DOC
    tree = (
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
    )

    def slide(text: str) -> str:
        shape = (
            '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            '<p:spPr><a:xfrm><a:off x="457200" y="457200"/><a:ext cx="8229600" cy="914400"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" sz="3200"><a:solidFill><a:srgbClr val="1F1F1F"/></a:solidFill></a:rPr><a:t>{text}</a:t></a:r></a:p>'
            f'<a:p><a:r><a:rPr lang="en-US" sz="1400"/><a:t>{html.escape(MARKUP)}</a:t></a:r></a:p>'
            # The same run written as a CDATA section, which a reader of the XML hands on raw.
            f'<a:p><a:r><a:rPr lang="en-US" sz="1400"/><a:t><![CDATA[{MARKUP}]]></a:t></a:r></a:p></p:txBody></p:sp>'
        )
        return f'<p:sld xmlns:a="{a}" xmlns:r="{r}" xmlns:p="{p}"><p:cSld><p:spTree>{tree}{shape}</p:spTree></p:cSld></p:sld>'

    colours = "".join(
        f'<a:{name}><a:srgbClr val="{value}"/></a:{name}>'
        for name, value in [
            ("dk1", "000000"), ("lt1", "FFFFFF"), ("dk2", "1F497D"), ("lt2", "EEECE1"),
            ("accent1", "4F81BD"), ("accent2", "C0504D"), ("accent3", "9BBB59"), ("accent4", "8064A2"),
            ("accent5", "4BACC6"), ("accent6", "F79646"), ("hlink", "0000FF"), ("folHlink", "800080"),
        ]
    )
    font = '<a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/>'
    line = '<a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
    fill = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    theme = (
        f'<a:theme xmlns:a="{a}" name="Plain"><a:themeElements>'
        f'<a:clrScheme name="Plain">{colours}</a:clrScheme>'
        f'<a:fontScheme name="Plain"><a:majorFont>{font}</a:majorFont><a:minorFont>{font}</a:minorFont></a:fontScheme>'
        f'<a:fmtScheme name="Plain"><a:fillStyleLst>{fill}{fill}{fill}</a:fillStyleLst>'
        f"<a:lnStyleLst>{line}{line}{line}</a:lnStyleLst>"
        "<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle>"
        "<a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>"
        f"<a:bgFillStyleLst>{fill}{fill}{fill}</a:bgFillStyleLst></a:fmtScheme>"
        "</a:themeElements></a:theme>"
    )
    overrides = {
        "/ppt/presentation.xml": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
        "/ppt/slideMasters/slideMaster1.xml": "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml",
        "/ppt/slideLayouts/slideLayout1.xml": "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml",
        "/ppt/theme/theme1.xml": "application/vnd.openxmlformats-officedocument.theme+xml",
        "/ppt/slides/slide1.xml": "application/vnd.openxmlformats-officedocument.presentationml.slide+xml",
        "/ppt/slides/slide2.xml": "application/vnd.openxmlformats-officedocument.presentationml.slide+xml",
    }
    return _zip({
        "[Content_Types].xml": _types({"rels": RELS_TYPE, "xml": "application/xml"}, overrides),
        "_rels/.rels": _relationships(("rId1", f"{_DOC}/officeDocument", "ppt/presentation.xml", False)),
        "ppt/presentation.xml": (
            f'<p:presentation xmlns:a="{a}" xmlns:r="{r}" xmlns:p="{p}">'
            '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
            '<p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId3"/></p:sldIdLst>'
            '<p:sldSz cx="9144000" cy="5143500"/><p:notesSz cx="6858000" cy="9144000"/>'
            '<p:defaultTextStyle><a:defPPr><a:defRPr lang="en-US"/></a:defPPr>'
            '<a:lvl1pPr marL="0" algn="l"><a:defRPr sz="1800"/></a:lvl1pPr></p:defaultTextStyle></p:presentation>'
        ),
        "ppt/_rels/presentation.xml.rels": _relationships(
            ("rId1", f"{_DOC}/slideMaster", "slideMasters/slideMaster1.xml", False),
            ("rId2", f"{_DOC}/slide", "slides/slide1.xml", False),
            ("rId3", f"{_DOC}/slide", "slides/slide2.xml", False),
            ("rId4", f"{_DOC}/theme", "theme/theme1.xml", False),
        ),
        "ppt/slideMasters/slideMaster1.xml": (
            f'<p:sldMaster xmlns:a="{a}" xmlns:r="{r}" xmlns:p="{p}"><p:cSld><p:spTree>{tree}</p:spTree></p:cSld>'
            '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
            'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
            '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst></p:sldMaster>'
        ),
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": _relationships(
            ("rId1", f"{_DOC}/slideLayout", "../slideLayouts/slideLayout1.xml", False),
            ("rId2", f"{_DOC}/theme", "../theme/theme1.xml", False),
        ),
        "ppt/slideLayouts/slideLayout1.xml": (
            f'<p:sldLayout xmlns:a="{a}" xmlns:r="{r}" xmlns:p="{p}" type="blank"><p:cSld name="Blank">'
            f"<p:spTree>{tree}</p:spTree></p:cSld></p:sldLayout>"
        ),
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": _relationships(
            ("rId1", f"{_DOC}/slideMaster", "../slideMasters/slideMaster1.xml", False)
        ),
        "ppt/theme/theme1.xml": theme,
        "ppt/slides/slide1.xml": slide(SLIDE_ONE),
        "ppt/slides/slide2.xml": slide(SLIDE_TWO),
        "ppt/slides/_rels/slide1.xml.rels": _relationships(("rId1", f"{_DOC}/slideLayout", "../slideLayouts/slideLayout1.xml", False)),
        "ppt/slides/_rels/slide2.xml.rels": _relationships(("rId1", f"{_DOC}/slideLayout", "../slideLayouts/slideLayout1.xml", False)),
    })
