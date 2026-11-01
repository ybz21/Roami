# Claims from market-price snapshots

Read this when a report turns daily price and volume data into business or trading conclusions.

Keep three levels distinct in charts, slide titles, notes, and the final summary:

- **Observed:** describe the supplied fields, dates, units, and computed changes. Preserve the definition and period of each metric.
- **Interpretation:** say what the observed change may suggest, with its assumptions and competing explanations. A proxy remains a proxy in every place it is mentioned.
- **Decision:** identify the additional evidence needed for an operational recommendation; do not assert it was established by the snapshot.

Daily close multiplied by share volume is a closing-price dollar-volume proxy. It is not observed transaction value, executable order size, cash available to the company, or evidence that a treasury operation can be absorbed. A change in that proxy establishes a change in the proxy. Liquidity also depends on spreads, available depth, and price impact. Without those observations, report activity and the limits of the available data rather than declaring capacity or execution quality.

A daily price extreme or return extreme describes the supplied daily series. It does not identify an actual trade, the worst attainable fill, or the price for a proposed order. Execution analysis needs the relevant quotes, trades, order size and timing. If the task asks for a practical implication without these inputs, give a conditional next step and name the missing evidence; do not invent a fill or a business event.

Name the two variables and their time alignment when interpreting a correlation. A same-row price/return correlation is contemporaneous; it does not measure next-day returns or establish predictability. Future-return claims require an explicitly shifted series and separate predictive validation. A near-zero linear coefficient does not establish independence or randomness.

Distinguish return direction from movement size. Volume correlated with signed returns does not show whether larger moves occur on heavier or lighter volume. Examine an explicitly defined magnitude measure, such as absolute or squared returns, before making that claim; keep the same definition in the chart and narrative. Otherwise omit the magnitude claim.

Before publishing, trace each headline and recommendation back to a computed result or an identified external source. Check speaker notes as well as visible slide text. Remove stronger claims that the evidence cannot support; preserve useful descriptive comparisons and explicit uncertainty.

Sources for these distinctions:

- [Federal Reserve: dimensions of market liquidity](https://www.federalreserve.gov/publications/2022-may-financial-stability-report-asset-valuation.htm) discusses spreads and quoted depth.
- [SEC: Trading Basics](https://www.sec.gov/files/investor/alerts/trading101basics.pdf) explains that the last-traded price need not be an order's execution price.
- [NIST: Scatter Plot](https://www.itl.nist.gov/div898/handbook/eda/section3/eda33q.htm) distinguishes linear and nonlinear associations between the actual paired variables.
- [NIST: Autocorrelation](https://www.itl.nist.gov/div898/software/dataplot/refman2/ch2/autocorr.pdf) defines lagged pairing and warns that one lag's zero coefficient does not establish zero correlation at other lags.
