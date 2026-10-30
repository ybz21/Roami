"""Minimal OOXML ZIP fixture for structural parsing, not an editable slide deck."""

import io
import zipfile


def presentation_bytes():
    ns = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    ns += 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    ns += (
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    )
    parts = {
        "ppt/presentation.xml": f'<p:presentation {ns}><p:sldIdLst><p:sldId r:id="slide"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": '<Relationships><Relationship Id="slide" Target="slides/slide1.xml"/></Relationships>',
        "ppt/slides/slide1.xml": f"""<p:sld {ns}><p:cSld><p:spTree>
          <p:sp><p:nvSpPr><p:cNvPr id="1" name="decoration"/></p:nvSpPr><p:txBody><a:p/></p:txBody></p:sp>
          <p:grpSp><p:nvGrpSpPr/><p:grpSpPr/>
            <p:sp><p:nvSpPr><p:cNvPr id="3" name="body"/></p:nvSpPr>
              <p:txBody><a:p><a:pPr algn="ctr"/><a:r><a:t>正文</a:t></a:r></a:p></p:txBody></p:sp>
          </p:grpSp>
          <p:sp><p:nvSpPr><p:cNvPr id="4" name="heading"/></p:nvSpPr>
            <p:txBody><a:p><a:r><a:t>Heading</a:t></a:r></a:p></p:txBody></p:sp>
        </p:spTree></p:cSld></p:sld>""",
    }
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as bundle:
        for name, text in parts.items():
            bundle.writestr(name, text)
    return body.getvalue()
