---
name: Roami model workspace
description: Compact model administration within Roami's existing neutral design system.
colors:
  accent: "var(--accent)"
  accent-solid: "var(--accent-solid)"
  accent-border: "var(--accent-border)"
  on-accent: "var(--on-accent)"
  ready: "var(--ok)"
  danger: "var(--danger)"
  warning: "var(--warn)"
  base: "var(--bg-base)"
  container: "var(--bg-container)"
  elevated: "var(--bg-elevated)"
  border: "var(--border)"
  border-subtle: "var(--border-subtle)"
  text: "var(--text-bright)"
  text-secondary: "var(--text-dim)"
  selected: "var(--sel-bg)"
typography:
  title:
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', Roboto, Helvetica, Arial, sans-serif"
    fontSize: "var(--fs-title)"
  section:
    fontSize: "var(--fs-lg)"
  body:
    fontSize: "var(--fs-body)"
    lineHeight: 1.6
  label:
    fontSize: "var(--fs-sm)"
    fontWeight: 500
  meta:
    fontSize: "var(--fs-meta)"
rounded:
  xs: "var(--r-xs)"
  sm: "var(--r-sm)"
  card: "var(--r-card)"
  pill: "var(--r-pill)"
spacing:
  sp-1: "var(--sp-1)"
  sp-2: "var(--sp-2)"
  sp-3: "var(--sp-3)"
  sp-4: "var(--sp-4)"
  sp-5: "var(--sp-5)"
components:
  button-primary:
    backgroundColor: "{colors.accent-solid}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.xs}"
    padding: "var(--sp-1) var(--sp-3)"
  button-outline:
    backgroundColor: "{colors.container}"
    textColor: "{colors.text}"
    rounded: "{rounded.xs}"
    padding: "var(--sp-1) var(--sp-3)"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.xs}"
    padding: "var(--sp-1) var(--sp-3)"
  input:
    backgroundColor: "{colors.container}"
    textColor: "{colors.text}"
    rounded: "{rounded.xs}"
    padding: "0 var(--sp-3)"
  navigation-tab:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.xs}"
    padding: "var(--sp-2) var(--sp-3)"
  badge:
    backgroundColor: "{colors.selected}"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.pill}"
    padding: "0 var(--sp-2)"
  strategy-card:
    backgroundColor: "{colors.container}"
    textColor: "{colors.text}"
    rounded: "{rounded.card}"
    padding: "var(--sp-4)"
  member-row:
    backgroundColor: "{colors.container}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: "var(--sp-4)"
---

# Design System: Roami model workspace

## Overview

**Creative North Star: "The model operations workbench"**

This is a code-led record of the shipped model-source and aggregation surfaces. The confirmed Linear/Vercel direction means restrained neutral surfaces, compact controls, aligned facts, and clear working hierarchy. It uses Roami's existing identity in both themes. The user pinned the direction (`seed: none`); no catalog world or new palette was introduced.

This topic record describes a local application of the [normative UI specification](../../development/ui-design-system.md). That specification, [theme source](../../../frontend/src/theme.tsx), and [base tokens](../../../frontend/src/index.css) remain authoritative. Frontmatter primitives deliberately reference live CSS variables, including the runtime-derived solid accent; they are bindings to that system, not replacement values. The document does not redesign other capability pages.

**Key Characteristics:**

- A full-canvas, flat application shell with independent content cards.
- Compact hierarchy using the existing sans family and type ladder.
- Neutral selection; blue actions and focus; green verified readiness.
- Equal functionality with mouse, keyboard, and touch.
- Source-backed facts with explicit unknown states.

## Colors

Quiet dark neutrals support long configuration sessions; the same semantic variables supply the existing light theme.

The sidecar's tonal ramps are panel-only interpolations of live tokens, not additional application colors. Its component snippets illustrate the existing controls without fixture metrics; production behavior stays in the React/Radix components.

### Primary

- **Action blue** (`--accent`): links, focus, insertion markers, and active drag feedback.
- **Solid action blue** (`--accent-solid`, `--on-accent`): primary buttons and simulation meters. Use the runtime-derived value rather than copying a seed color.
- **Accent boundary** (`--accent-border`): restrained drag and focus-related boundaries.

### Secondary

- **Readiness green** (`--ok`): readiness confirmed by saved routing-channel data. Neutral text still states the condition.
- **Danger red** (`--danger`): field errors and destructive actions, with the existing danger surface/border family.
- **Warning amber** (`--warn`): draft or caution states, with the existing warning surface/border family.

### Neutral

- **Canvas** (`--bg-base`): page shell, navigation, toolbars, and adjacent modules.
- **Content surface** (`--bg-container`): independent strategy card, member rows, and controls.
- **Popup surface** (`--bg-elevated`): Radix menus, selects, and confirmations.
- **Structural boundaries** (`--border`, `--border-subtle`): control strokes and one-sided module dividers.
- **Reading hierarchy** (`--text-bright`, `--text-dim`): identity and actions first; source and metadata second. The existing `--text-dimmer` is used for neutral status dots and disabled details.
- **Neutral selection** (`--sel-bg`): tabs, ordinal badges, simulation rounds, and a dragged row. Mouse feedback uses `--list-hover`.

**The Evidence Color Rule.** Green readiness comes from saved channel facts; unchecked, unavailable, and simulated rest remain distinct text states. A simulation is never proof of availability.

## Typography

**Body Font:** The existing Inter/system sans stack, with the project's Chinese system-font fallbacks. Labels and headings use the same family; this administrative surface has no separate display face.

**Character:** Compact and legible. Identity carries more weight than metadata; density comes from alignment and disclosure rather than small text.

### Hierarchy

- **Title** (`--fs-title`): inherited desktop page heading; the phone uses the established secondary-page bar.
- **Section** (`--fs-lg`): existing pane and dialog headings where present.
- **Body** (`--fs-body`): input text and member identity; member names use medium weight (500). The token grows in compact mode.
- **Label** (`--fs-sm`): buttons, tabs, field labels, and disclosure summaries; button/tab weight is medium (500).
- **Meta** (`--fs-meta`): source, readiness, context, latency, ordinals, and counts. These are secondary facts, not the sole labels for actions.

**The Existing Ladder Rule.** Reuse the live `--fs-*` roles. Do not create half-step sizes or shrink text to fit narrow screens; wrap metadata and move controls below identity.

## Layout

The workspace fills the available width and remaining shell height. Flex/grid children use zero minimum dimensions; the content container owns scrolling. The document never scrolls. Page and tab bars stay outside the editor's scroll area, and the save/cancel footer remains a separate layout item. Form and explanatory content may use `--content-form`; the workspace shell and member list do not inherit that cap.

One horizontal model-function navigation replaces the persistent model sidebar. It stays reachable while desktop details are open. Tabs scroll horizontally when needed. Back navigation precedes the title using the existing BackButton. On phones, content-heavy editors use MobileSubPage with one return bar and one content scroll container. URL-backed source details do not add a second overlay-history entry. Existing app navigation, safe areas, and keyboard handling remain owned by the shared shell.

For aggregation routing, one independent card combines strategy configuration and a compact simulation. The implemented wide layout divides that card into configuration and simulation columns (35%/65%). A full-width, ordered member list follows below it. This composition belongs to this model surface; it is not a universal composition requirement for Roami pages.

Compact and medium layouts stack the combined card, put metadata below identity, and move row controls below the identity column. They keep the full type scale and normal touch scrolling. Responsive decisions come only from `useLayout()` and the shared HTML `data-size`/`data-pointer` attributes; thresholds live in [layout.ts](../../../frontend/src/layout.ts). Phone page padding uses the existing [Material override](../../../frontend/src/mobile-material.css), not the smaller base fallback.

Spacing comes from `--sp-1` through `--sp-5`. Strategy cards and wide rows use `--sp-4` padding; narrow rows and the narrow strategy card use `--sp-3`. Row gaps use `--sp-2`; the member-order section follows the card at `--sp-5`. Control heights use `--ctl-h`, with independent touch targets of `--tap` (44 CSS px).

**The Canvas Rule.** Give free space to the actual workspace; close optional panes without leaving an empty column. Limit readable fields inside it, not the working canvas.

## Elevation & Depth

The implemented model surfaces are flat at rest. Tonal steps, fine boundaries, and space separate content; strategy cards and member rows have no decorative shadow. Popup placement uses the existing elevated surface and named popup layer. Drag feedback uses a neutral fill, accent boundary, and insertion line rather than lifting a row with a shadow. No new shadow vocabulary is introduced.

**The Single Boundary Rule.** Adjacent modules share the base surface and one subtle divider, owned by one side. Independent cards may have their own perimeter; an entire page is not a card.

## Shapes

The shared shell stays square and borderless around its perimeter. Controls and tab items use `--r-xs`; member rows and menus use `--r-sm`; the independent strategy card and short confirmation dialog use `--r-card`. Metadata chips use `--r-pill`, while member ordinals use the smaller control shape. These roles map directly to the existing radius ladder.

## Components

The new model-source and aggregation controls use local shadcn-style components with Radix behavior. Prefixed Tailwind utilities expand from Roami tokens and load once without global Preflight. [Model controls](../../../frontend/src/components/capabilities/model-controls.css) own visual states; [UI primitives](../../../frontend/src/components/ui/) own reusable semantics. Existing Ant Design surfaces elsewhere are not a prescription for new controls in this scope.

### Buttons

Compact, familiar actions. Primary uses the solid accent; outline uses the content surface and normal boundary; ghost uses neutral text and transparent fill. All use the small control radius, token padding, and medium label type. Focus has an accent outline. Disabled actions are visibly subdued and noninteractive; saving reflects busy state.

Mouse hover is gated to fine pointers. Coarse-pointer buttons preserve compact visuals and expand their hit area to the touch token. Icon-only actions carry localized accessible names; visible instructions do not depend on tooltips.

### Inputs / Fields

Labelled, neutral, and field-specific. Inputs use the content surface, normal border, small radius, and body type. Focus changes the border to the accent; invalid fields use the danger boundary and nearby localized error text. Validation preserves the draft and focuses the invalid field after a failed submission. Select and checkbox behavior comes from Radix; popup content uses the elevated surface and named popup layer.

### Navigation

Horizontal, quiet, and persistent. Radix tabs use neutral text at rest and neutral selected fill with bright text. Keyboard focus remains visible. Member selection, routing, and saved runtime are distinct contexts; changing tabs keeps the draft. Source connection, pricing, and routing retain their existing destination semantics.

### Chips

Small neutral facts, not colorful decoration. Context, latency, and ordinal chips use meta type and subtle boundaries. Status dots are drawn shapes paired with text. Context and latency explicitly say when unavailable; missing values are never rendered as invented zeroes or capabilities.

### Cards / Containers

Independent strategy card and member rows use content surfaces with subtle perimeter borders. The strategy card uses the card radius; rows use the standard row radius. Their token padding reduces one spacing step in compact/medium layouts. No outer rounded wrapper encloses the entire workspace.

### Sortable members

The full-width ordered rows show ordinal, model identity, source, readiness, context, and source latency. Quick move-to-top and remove actions appear on fine-pointer hover or keyboard focus and stay visible for coarse pointers. Weight controls appear when the selected strategy needs them.

Only the grab handle starts pointer sorting; ordinary row swipes keep scrolling. The handle supports ArrowUp/ArrowDown and Home/End ordering, Escape cancellation, disabled states, and a polite position announcement. Reordering preserves weights; removal also removes the corresponding weight. Feedback marks the dragged row and target insertion edge. The handle and quick actions meet the touch target independently of their visible size.

Facts come from [member-fact collection](../../../frontend/src/components/capabilities/model-member-facts.ts): readiness is based on matching saved route channels; context comes from the source directory; latency is the source's first-token P95 over the existing rolling 24-hour monitor, not an individual model benchmark. Missing source/directory/monitor data remains unknown. Preview counts and rest choices are explicitly simulated. No fixture measurements belong in the visual system.

### Disclosures

Policy details and request options use native details/summary semantics with a shared SVG chevron. The chevron rotates when open and the summary remains touch-sized. Keep both the visible expansion cue and keyboard affordance; a bare text label does not communicate disclosure clearly enough.

## Do's and Don'ts

### Do:

- **Do** reference the existing CSS variables and let both themes resolve them.
- **Do** fill the working canvas and keep scrolling inside the active content region.
- **Do** retain localized labels, visible focus, explicit unknown states, and field-level recovery.
- **Do** keep quick actions visible on touch and preserve the 44 CSS px hit target.
- **Do** support handle-only dragging, keyboard ordering, and ordinary phone scrolling together.
- **Do** keep disclosure chevrons and save/cancel actions discoverable.

### Don't:

- **Don't** introduce a competing palette, type ladder, radius scale, or global Tailwind reset.
- **Don't** turn adjacent modules or whole pages into enclosing rounded cards.
- **Don't** treat simulation, source-level latency, or unchecked data as verified model quality.
- **Don't** hide touch actions behind hover or rely on tooltip-only names.
- **Don't** replace existing SVG icons with emoji, text glyphs, or new component-local SVG drawings.
- **Don't** repeat page titles, explanatory copy, or implementation details in the main flow.
