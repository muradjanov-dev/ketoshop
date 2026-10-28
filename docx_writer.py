"""
A small .docx writer — enough for the legal agent's documents (yurist.py):
headings, paragraphs, bullet lists, bordered tables and signature lines, on
A4 with Times New Roman 12, the way Uzbek business papers are set.

No dependency: a .docx is a zip of a few XML parts, and python-docx would be
one more package in the image for what fits in this file.
"""
from io import BytesIO
from xml.sax.saxutils import escape
import zipfile

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman" w:eastAsia="Times New Roman"/>
<w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="uz-Latn-UZ"/>
</w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:jc w:val="both"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>
<w:pPr><w:jc w:val="center"/><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
<w:pPr><w:keepNext/><w:spacing w:before="200" w:after="80"/><w:jc w:val="left"/></w:pPr><w:rPr><w:b/></w:rPr></w:style>
</w:styles>"""

_CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>{title}</dc:title><dc:creator>Ketoshop</dc:creator>
</cp:coreProperties>"""

_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
# A4: 3 cm left (binding), 1.5 cm right, 2 cm top and bottom — the usual
# setting for Uzbek office papers.
_SECTION = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1134" w:right="851" w:bottom="1134" w:left="1701" '
            'w:header="709" w:footer="709" w:gutter="0"/></w:sectPr>')


def _runs(text: str, bold: bool = False) -> str:
    """Text as runs; a newline inside it is a line break, not a paragraph."""
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    parts = str(text or "").split("\n")
    out = []
    for i, part in enumerate(parts):
        if i:
            out.append(f"<w:r>{rpr}<w:br/></w:r>")
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
    return "".join(out)


def _para(text: str, style: str = "", bold: bool = False, align: str = "") -> str:
    ppr = ""
    if style or align:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + \
              (f'<w:jc w:val="{align}"/>' if align else "") + "</w:pPr>"
    return f"<w:p>{ppr}{_runs(text, bold)}</w:p>"


def _table(rows: list[list[str]]) -> str:
    rows = [[str(c or "") for c in row] for row in rows if row]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    border = '<w:{side} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
    borders = "".join(border.format(side=s) for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{borders}</w:tblBorders>'
           '<w:tblLayout w:type="autofit"/></w:tblPr><w:tblGrid>']
    out.append("".join(f'<w:gridCol w:w="{9000 // width}"/>' for _ in range(width)))
    out.append("</w:tblGrid>")
    for r, row in enumerate(rows):
        out.append("<w:tr>")
        for c in range(width):
            cell = row[c] if c < len(row) else ""
            out.append(f'<w:tc><w:tcPr><w:tcW w:w="{9000 // width}" w:type="dxa"/></w:tcPr>'
                       f"{_para(cell, bold=(r == 0), align='left')}</w:tc>")
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out) + "<w:p/>"


def build(title: str, blocks: list[dict]) -> bytes:
    """A .docx from a title and blocks. Each block is a dict with `kind`:
    "heading", "paragraph", "bullets" (`items`), "table" (`rows`, first row
    bold as the header) or "signature" (`items`: one line per signer)."""
    body = [_para(title, style="Title")]
    for block in blocks or []:
        kind = (block.get("kind") or "paragraph").lower()
        if kind == "heading":
            body.append(_para(block.get("text"), style="Heading1"))
        elif kind == "bullets":
            for item in block.get("items") or []:
                body.append(_para(f"•  {item}"))
        elif kind == "table":
            body.append(_table(block.get("rows") or []))
        elif kind == "signature":
            for item in block.get("items") or []:
                body.append(_para(f"{item}\n\n______________________   (imzo)        M.O.", align="left"))
        else:
            if block.get("text"):
                body.append(_para(block.get("text")))
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_NS}><w:body>'
                + "".join(body) + _SECTION + "</w:body></w:document>")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/document.xml", document)
        z.writestr("docProps/core.xml", _CORE.format(title=escape(title or "")))
    return buf.getvalue()


def extract_text(data: bytes, limit: int = 40_000) -> str:
    """The plain text of a .docx someone sent — for the agent to read."""
    import re
    with zipfile.ZipFile(BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    xml = re.sub(r"<w:br/>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    from xml.sax.saxutils import unescape
    text = unescape(text, {"&quot;": '"', "&apos;": "'"})
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:limit]
