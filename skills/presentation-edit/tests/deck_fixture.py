import io

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches


def deck_bytes(*, same_position=False):
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    body = slide.shapes.add_textbox(Inches(1), Inches(4), Inches(5), Inches(1))
    body.text = "Body"
    heading = slide.shapes.add_textbox(
        Inches(1), Inches(4 if same_position else 1), Inches(5), Inches(1)
    )
    heading.text = "Heading"
    for shape in [body, heading]:
        shape.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT
        shape.text_frame.paragraphs[0].runs[0].font.size = Inches(0.3)
    stream = io.BytesIO()
    deck.save(stream)
    return stream.getvalue()


def text_deck_bytes(runs):
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    frame = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(2))
    paragraph = frame.text_frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.RIGHT
    for spec in runs:
        run = paragraph.add_run()
        run.text = spec["text"]
        run.font.name = "Liberation Sans"
        run.font.size = Inches(0.3)
        run.font.bold = spec.get("bold", False)
        run.font.italic = spec.get("italic", False)
        run.font.color.rgb = RGBColor.from_string(spec.get("rgb", "224466"))
    slide.shapes.add_textbox(
        Inches(1), Inches(4), Inches(8), Inches(1)
    ).text = "Keep this object"
    other = deck.slides.add_slide(deck.slide_layouts[6])
    other.shapes.add_textbox(
        Inches(1), Inches(1), Inches(8), Inches(1)
    ).text = "Keep this slide"
    stream = io.BytesIO()
    deck.save(stream)
    return stream.getvalue()
