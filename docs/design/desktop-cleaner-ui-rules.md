# Desktop Cleaner UI Rules

## Settings Center

- Use a dashboard layout: left navigation, right-side cards, clear section groups.
- Use real translucent panel previews for panel management, panel history, and panel appearance. Do not create page-specific schematic previews.
- Preview cards show the panel title, active tab, tab strip, background color, and opacity.
- When tab count exceeds the available width, show the first visible tabs and a `+N` overflow badge.
- Buttons use one visual language: icon-only for compact repeated actions, text buttons for irreversible or explicit commands.
- Chips use a wrapping flow area with fixed height and scrolling. They must not resize the whole settings window.

## Panel Properties

- Layout state: screen, geometry, collapse, lock, tab order.
- Appearance state: background color, background opacity, item icon size.
- Content state: item tab, widget tab, widget settings.
- Interaction state: selected group, selected tab, preview drag state. Interaction state is not persisted.

All mutable settings changes should flow through application commands or Qt signals. UI pages should not directly duplicate business behavior.

## Desktop Panel Display

- Panel background transparency affects only the panel background. Icons, thumbnails, and text remain opaque.
- Item grids use fixed spacing and left alignment. Extra width stays as right-side empty space instead of stretching item gaps.
- Widget panel content should have bounded preview/content size and remain centered.

## History

- History is for layout-related changes only: panel position, size, add/delete, merge/split, tab order, and appearance.
- History cards use the same panel preview renderer as panel management.
- Show a human-readable Chinese reason. Do not expose raw internal reason strings.
- Do not save or require desktop screenshots for normal history display.
