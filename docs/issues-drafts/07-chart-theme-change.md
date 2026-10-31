# fix(dashboard): re-colour the equity chart when the OS theme changes

Labels: good first issue,bug

## Context

The dashboard follows `prefers-color-scheme` through CSS. The equity chart in
`services/conductor/src/conductor/infrastructure/dashboard/static/dashboard.js` reads the
scheme **once**, at load. If the OS switches between light and dark (e.g. automatic at
sunset), the page changes but the chart keeps the old colours until a reload.

## What to do

1. Listen for `matchMedia("(prefers-color-scheme: dark)")` `change` events.
2. On change, update the dataset and scale colours and call `chart.update()`. Don't rebuild
   the chart or refetch data.
3. Keep the script dependency-free and same-origin: the dashboard's CSP is
   `script-src 'self'`, and `test_no_external_resources_are_referenced` must keep passing.

## Done when

- [ ] Toggling the OS theme (or DevTools → Rendering → *Emulate prefers-color-scheme*)
      re-colours the chart without a reload.
- [ ] `make conductor-test` passes.

## Out of scope

The dashboard is read-only by design (ADR-0017). Don't add controls, forms or write calls.
`test_templates_contain_no_forms_or_write_triggers` enforces that.
