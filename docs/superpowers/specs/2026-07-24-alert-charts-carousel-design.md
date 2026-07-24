# Alert Charts Carousel Design

## Goal

Make the alert chart experience mobile-first by showing exactly one chart in a
swipeable card at a time, instead of a long vertical list of charts.

## Scope

- Keep the existing ten chart components and their data unchanged.
- Replace the vertically stacked chart layout in `AlertChartsPage` with a
  single active chart card.
- Support both horizontal swipe gestures and previous/next tap controls.
- Show a compact progress indicator (`Chart 3 of 10`) and disabled edge controls
  on the first and final cards.
- Preserve vertical scrolling inside the active chart area for charts taller
  than the available viewport.
- Keep the Normal / Drilldown mode selection available in the page header.
- Change the header return action to explicitly navigate to the alert's
  Affected Companies page, rather than relying on browser-history back.

## Interaction design

The page header retains article context and the Normal / Drilldown selector.
Its leading action reads `Affected companies` and routes to
`/alerts/:id`, providing a predictable exit from the charts experience.

The chart region is a mobile-width carousel with one full-width card. A user
can drag horizontally past the existing swipe threshold to move to the next or
previous chart. The same transitions are available through labelled previous
and next buttons, so the flow does not depend on gesture discovery.

The active position is exposed as `Chart N of 10`; navigation buttons are
disabled when no adjacent card exists. The card list remains mounted only for
the selected chart, preventing the original page-long scroll while keeping the
individual chart's own content and vertical scrolling intact.

## Implementation boundaries

- Add a local ordered chart registry in `AlertChartsPage` so rendering,
  progress, and controls share one source of truth.
- Reuse `useHorizontalSwipe`; no new gesture dependency is needed.
- Add focused page tests for the initial card, next/previous controls, swipe
  navigation, and the explicit affected-companies route.
- Do not alter chart calculations, API shapes, or server behaviour.

## Error handling and accessibility

Loading and error states remain unchanged. Navigation controls use descriptive
accessible labels, are keyboard-operable, and use the native `disabled` state
at carousel boundaries. Horizontal gestures only trigger when horizontal motion
dominates vertical motion, preserving normal vertical reading of tall charts.

## Verification

- Run the AlertChartsPage test file after adding its test-first coverage.
- Run the complete frontend test suite and production build.
- Confirm the route and interactions manually in the mobile viewport if the
  local browser test environment is available.
