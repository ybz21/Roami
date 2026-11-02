"""Editable slide copy generated from the same facts used by the charts."""

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

NAVY, BLUE, TEAL, GREY, LIGHT = "15334F", "2168A6", "168D86", "627487", "EDF3F7"


def number(value, digits=1):
    return "n/a" if value is None else f"{value:,.{digits}f}"


def percent(value, digits=1):
    return "n/a" if value is None else f"{value * 100:+,.{digits}f}%"


def magnitude_percent(value, digits=1):
    return "n/a" if value is None else f"{value * 100:,.{digits}f}%"


def text(slide, value, x, y, width, height, font, size=16, bold=False, color=NAVY):
    shape = slide.shapes.add_textbox(
        Inches(x), Inches(y), Inches(width), Inches(height)
    )
    frame = shape.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    for index, line in enumerate(value.split("\n")):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.space_after = Pt(10)
        paragraph.line_spacing = 1.12
        run = paragraph.add_run()
        run.text = line
        run.font.name = font
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = RGBColor.from_string(color)
    return shape


def rectangle(slide, x, y, width, height, color):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(width), Inches(height)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(color)
    shape.line.fill.background()
    for effect in shape._element.xpath("p:style/a:effectRef"):
        effect.set("idx", "0")


def build(folder, facts, images, args, font):
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333333), Inches(7.5)
    notes = []
    period = facts["from"] + " to " + facts["to"]
    source = Path(args.path).name
    footer = f"{source[:48]} | {facts['rows']:,} observations | SHA-256 {facts['sourceSha256'][:12]}"

    def slide(title, paragraphs, *, image=None, cover=False):
        page = deck.slides.add_slide(deck.slide_layouts[6])
        if cover:
            page.background.fill.solid()
            page.background.fill.fore_color.rgb = RGBColor.from_string(NAVY)
            rectangle(page, 0.55, 1.7, 0.06, 3.8, TEAL)
            text(
                page,
                "DESCRIPTIVE MARKET SERIES REVIEW",
                0.85,
                1.65,
                11.5,
                0.4,
                font,
                12,
                True,
                "B5D5E6",
            )
            text(page, title, 0.85, 2.4, 11.4, 1.6, font, 34, True, "FFFFFF")
            text(
                page,
                period
                + f"\n{facts['rows']:,} observations; {facts['columns']['price']} and {facts['columns']['volume']}",
                0.85,
                4.45,
                11.4,
                1.2,
                font,
                18,
                color="D7E6F1",
            )
        else:
            text(page, title, 0.55, 0.42, 12.2, 0.85, font, 27, True)
            rectangle(page, 0.55, 1.23, 0.75, 0.04, TEAL)
            if image:
                page.shapes.add_picture(
                    str(image), Inches(0.35), Inches(1.6), width=Inches(8.35)
                )
                rectangle(page, 8.95, 1.65, 0.025, 4.65, "D5E1E9")
                text(page, "\n".join(paragraphs), 9.2, 1.65, 3.55, 4.95, font, 16)
            else:
                for index, (heading, copy) in enumerate(paragraphs):
                    y = 1.65 + index * 1.45
                    text(page, heading, 0.65, y, 3.35, 1.05, font, 20, True, BLUE)
                    text(page, copy, 4.3, y, 8.25, 1.1, font, 17)
            text(page, footer, 0.55, 6.93, 11.6, 0.3, font, 10, color=GREY)
            text(
                page, str(len(deck.slides)), 12.3, 6.93, 0.5, 0.3, font, 10, color=GREY
            )
        prose = (
            [f"{heading}: {copy}" for heading, copy in paragraphs]
            if not image and not cover
            else paragraphs
        )
        note = (
            title
            + "\n\n"
            + "\n\n".join(prose)
            + "\n\nSource: "
            + source
            + "; SHA-256 "
            + facts["sourceSha256"]
            + ". Observed period: "
            + period
        )
        page.notes_slide.notes_text_frame.text = note
        notes.append(f"## Slide {len(deck.slides)} - {title}\n\n" + note)

    price, moving, returns, volume, drawdown = (
        facts[key]
        for key in ("price", "movingAverages", "returns", "volume", "drawdown")
    )
    slide(
        args.title,
        [
            "A descriptive review of the selected daily price and volume series. No valuation or forecast is implied."
        ],
        cover=True,
    )
    slide(
        "Executive summary",
        [
            (
                "Observed price path",
                f"Price change {percent(price['change'])}; calendar-time CAGR {percent(price['cagr'])}. Period: {period}. A total-return interpretation requires adjustment metadata.",
            ),
            (
                "Historical risk",
                f"Annualized sample volatility {magnitude_percent(returns['annualVolatility'])} ({args.sessions} sessions/year); running-peak drawdown {percent(drawdown['minimum'])} on {drawdown['date']}. These are historical observations.",
            ),
            (
                "Trading activity",
                f"Overall median {number(volume['median'], 0)} {args.volume_unit} across {facts['rows']:,} observations. Volume establishes neither ownership composition nor liquidity depth; calendar cohorts accompany the volume chart.",
            ),
        ],
    )
    slide(
        "Price-series change: " + percent(price["change"]),
        [
            f"{number(price['first'], 2)} to {number(price['last'], 2)} {args.price_unit}.",
            f"End/start ratio: {number(price['factor'], 2)} times. Calendar-time CAGR: {percent(price['cagr'])}.",
            f"Observed minimum: {number(price['minimum'], 2)} on {price['minimumDate']}; maximum: {number(price['maximum'], 2)} on {price['maximumDate']}.",
            "The selected series is used as supplied. A total-return interpretation requires documented dividend and adjustment methods.",
        ],
        image=images[0],
    )
    if moving["shortLast"] is not None and moving["longLast"] is not None:
        relation = (
            "below"
            if moving["shortLast"] < moving["longLast"]
            else "above"
            if moving["shortLast"] > moving["longLast"]
            else "equal to"
        )
        moving_copy = [
            f"{args.short}-observation average: {number(moving['shortLast'], 2)}. {args.long}-observation average: {number(moving['longLast'], 2)}.",
            f"The short average is {relation} the long average on {facts['to']}.",
            f"Latest price relative to the long average: {percent(moving['priceVsLong'])}.",
            "Backward-looking averages describe the selected observations; they do not establish future returns.",
        ]
        if moving["crossings"]:
            latest = moving["crossings"][-1]
            moving_copy.insert(
                2,
                f"Latest full-window crossing: {latest['direction']} on {latest['date']}.",
            )
    else:
        moving_copy = [
            f"The requested windows are {args.short} and {args.long} observations.",
            f"This sample contains {facts['rows']} observations. A window without enough data is not estimated.",
            "No future-return conclusion is inferred.",
        ]
    slide(
        f"{args.short}- and {args.long}-observation averages",
        moving_copy,
        image=images[1],
    )
    slide(
        "Same-observation correlation",
        [
            f"{args.price} versus {args.volume}: Pearson r = {number(facts['correlation']['values'][0][1], 2)} over {facts['correlation']['pairCounts'][0][1]:,} paired observations.",
            f"Successive price changes versus {args.volume}: r = {number(facts['correlation']['values'][-1][1], 2)} over {facts['correlation']['pairCounts'][-1][1]:,} pairs.",
            "Trending levels and price changes are different measures. These contemporaneous associations establish neither causation nor next-period predictability. Undefined coefficients are n/a.",
        ],
        image=images[2],
    )
    slide(
        "Distribution of observed price changes",
        [
            f"Mean: {percent(returns['mean'], 3)}. Sample standard deviation: {magnitude_percent(returns['std'], 2)}.",
            f"Annualized volatility: {magnitude_percent(returns['annualVolatility'])} using {args.sessions} observations per year.",
            f"5th/95th percentiles: {percent(returns['p05'])} / {percent(returns['p95'])}. Excess kurtosis: {number(returns['excessKurtosis'], 2)}.",
            f"Absolute-change lag-1 correlation: {number(returns['absoluteLag1Correlation'], 3)}. This ordered statistic is separate from distribution shape; no forecast follows.",
        ],
        image=images[3],
    )
    cohort_copy = [
        f"{cohort['label']}: median {number(cohort['value'], 0)} over {cohort['rows']} observations ({cohort['from']} to {cohort['to']})."
        for cohort in volume["calendarCohorts"]
    ]
    slide(
        "Distribution of observed daily volume",
        [
            f"Overall median: {number(volume['median'], 0)} {args.volume_unit}.",
            *cohort_copy,
            "These are observed calendar-year cohorts, not quarterly or rolling-year statistics. Volume alone does not measure float turnover, shareholder composition or liquidity depth.",
        ],
        image=images[4],
    )
    slide(
        "Historical peak-to-trough price decline",
        [
            f"Maximum observed drawdown: {percent(drawdown['minimum'])} on {drawdown['date']}.",
            "Computed from price divided by its running historical peak, minus one.",
            "This measures the observed path of this series, not an estimate of future downside or a guarantee of recovery.",
        ],
        image=images[5],
    )
    slide(
        "What these observations support",
        [
            (
                "Price and risk",
                f"Price change {percent(price['change'])}; annualized observed volatility {magnitude_percent(returns['annualVolatility'])}; maximum historical drawdown {percent(drawdown['minimum'])}.",
            ),
            (
                "Observed distribution",
                f"The 5th/95th percentiles of successive price changes are {percent(returns['p05'])} / {percent(returns['p95'])}. The largest observed peak-to-trough decline occurred on {drawdown['date']}. These are historical observations, not future bounds.",
            ),
            (
                "Evidence still needed",
                "Share counts and trading microstructure data are needed for turnover ratios or liquidity-depth analysis. Dividend and adjustment metadata are needed to interpret total return.",
            ),
        ],
    )
    deck.save(folder / "report.pptx")
    (folder / "presenter-notes.md").write_text(
        "# Presenter notes\n\n"
        + "\n\n".join(notes)
        + f"\n\nAnnualization assumptions: {args.sessions} observed sessions/year for volatility, 365.25 calendar days/year for CAGR. Calendar timezone: {args.calendar_timezone}; naive dates/timestamps use that calendar.\n",
        encoding="utf-8",
    )
    return len(deck.slides)
