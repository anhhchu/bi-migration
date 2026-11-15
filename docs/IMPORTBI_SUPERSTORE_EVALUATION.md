# `/importBI` Superstore Evaluation

## Test

- Job: `140496257977237`
- Run: `73596449116752`
- Task run: `255532498070816`
- Result: successful
- Duration: 31 minutes 54 seconds
- Dashboard: `01f1df96f76a18088faab19453a3c196`
- Dashboard name: `Super Sample Superstore - Migration Evaluation 2026-11-13T19-18-11`
- State: active draft, not published

## Verified Output

The dashboard definition contains:

- 4 pages: global filters, descriptive, prescriptive, and annotations.
- 71 widgets.
- 9 datasets: 2 dashboard-local metric views and 7 parameter-option datasets.
- 2 date filters, 10 single-select filters, and 3 text-entry filters.
- 6 counters, 6 maps, 6 bars, 3 lines, 1 scatter plot, 24 tables, and 10 text widgets.

### Local Metric Views

| Metric view | Source | Measures | Dimensions | Parameters |
|---|---|---:|---:|---:|
| Superstore Orders | `superstore_orders` through a local SQL source | 37 | 32 | 6 |
| TOC & Annotations | `superstore_toc_annotations` | 1 | 8 | 6 |

The orders metric view includes core measures, current/comparison-period measures, differences, date-shift logic, filters, Tableau parameter equivalents, map switchers, and FIXED-record-count behavior.

## Capability Assessment

### Strong

- Parsed a complex Tableau workbook with 41 worksheets and many calculations.
- Remapped the workbook to supplied Databricks tables.
- Kept the orders and annotations sources separate as instructed.
- Generated dashboard-local metric views with parameters and derived measures.
- Reproduced pages, global controls, maps, KPIs, trends, comparison periods, and a configurable scatter plot.
- Produced an explicit migrated, degraded, and skipped worksheet inventory.
- Preserved workbook-specific behavior such as the four-year order-date shift.

### Partial

- Bullet charts became bars with comparison lines.
- Regional comparison dots became bars and lost letter labels.
- Tableau clustering and point labels were dropped from the scatter plot.
- Navigation buttons became tables and do not change pages.
- Indicator icons became colored cells.
- Click filtering is similar but not identical to Tableau actions.
- Dynamic tooltip prefixes and suffixes were omitted.

### Not Validated

- Pixel-level layout and formatting parity because screenshots were not supplied.
- Full KPI parity against Tableau reference values.
- Cross-page behavior of annotation parameters.
- Concurrency, cost, and behavior across heterogeneous workbooks.

## Project Implications

1. **Use `/importBI` as the conversion and local-semantic-generation engine.** Rebuilding its parser or metric translation logic would duplicate substantial product capability.
2. **Keep deterministic pre-import inventory.** It is still needed for grouping, prioritization, source readiness, compatibility decisions, and prompt generation.
3. **Shift KPI consolidation after import.** Extract embedded local metric-view configs from dashboard JSON, compare definitions across dashboards, validate them, and select promotion candidates.
4. **Separate reusable and dashboard-specific semantics.** Core measures such as sales, profit, quantity, discount, returns, and profit ratio are likely promotion candidates. Page navigation, annotation parameters, date-shift demo logic, and visualization switchers should normally remain local.
5. **Require screenshots for priority assets.** The agent cannot complete visual parity review without references.
6. **Add programmatic observability.** The Jobs API reported success but did not expose the final Genie response. The solution must capture run IDs, session links, dashboard IDs, serialized dashboard definitions, and validation results separately.
7. **Plan for long runtimes.** One complex workbook took nearly 32 minutes. Portfolio estimates must use complexity tiers, bounded concurrency, retry policy, and reviewer capacity rather than workbook count alone.
8. **Treat degradation as a business decision.** Compatibility rules must distinguish acceptable approximation, redesign, defer, and block.

## Next Build

1. Add a dashboard-artifact extractor that reads serialized AI/BI dashboard JSON.
2. Export local metric views, parameters, measures, dimensions, and source expressions into normalized Delta/JSON records.
3. Compare local metric definitions across dashboards using deterministic normalization plus LLM-assisted semantic review.
4. Generate promotion candidates with evidence and keep dashboard-only logic local.
5. Add SQL reconciliation tests for promoted measures.
6. Add screenshot-based visual review for high-priority dashboards.
7. Track runtime, degradation categories, exceptions, and human-review effort for every import.
