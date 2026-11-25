# Group Tableau Datasources — Genie Code Prompt

You are running unattended in a Lakeflow Job. Group Tableau TDS/TDSX datasources into coherent
business semantic domains. Do not create or modify dashboards, Metric Views, Genie Agents,
tables, mappings, or source files.

- Deterministic grouping request: `{{grouping_request_path}}`
- Required grouping proposal: `{{grouping_result_path}}`

Read the request, every referenced Datasource IR and Metric IR document, the approved mapping,
and the source TDS/TDSX packages when the parsed evidence is ambiguous. Deterministic similarity
scores are supporting evidence only; do not treat them as the grouping decision.

Group by shared business subject, entities, measures, relationships, source lineage, and approved
target schemas. Datasources may belong together when their target table sets differ, such as POS
and web transactions or several Superstore workbooks sharing the same business domain. Never use
internal Tableau identifiers such as `federated.*`, `Clipboard_*`, `DATA`, or `Menu` as group names.
Treat approved `business_domains` and `mapping_display_names` as authoritative business context.
Tableau datasource captions are technical identifiers and may be misleading; preserve them for
matching, but do not infer a business domain from the caption when approved context contradicts it.

For each business group provide a concise `display_name`, `domain`, primary
`member_datasource_ids`, optional `helper_datasource_ids`, a specific `rationale`, and confidence
from 0 to 1. Navigation, annotation, clipboard, menu, scaffold, and display-only datasources must
be attached as helpers when clearly associated with a business group or listed under
`ungrouped_datasources` with classification `UI_HELPER`. Never make a helper a primary member.

Write JSON atomically to `{{grouping_result_path}}` with exactly this top-level structure:

```json
{
  "schema_version": "1.0",
  "status": "COMPLETE",
  "groups": [
    {
      "display_name": "Readable business domain",
      "domain": "Business domain",
      "member_datasource_ids": ["..."],
      "helper_datasource_ids": ["..."],
      "rationale": "Why these sources belong together",
      "confidence": 0.95
    }
  ],
  "ungrouped_datasources": [
    {
      "datasource_id": "...",
      "classification": "UI_HELPER",
      "reason": "Why this source should not create a semantic asset"
    }
  ]
}
```

Every datasource ID in the request must appear exactly once as a primary member, attached helper,
or ungrouped UI helper. Every mapped business datasource must be a primary member. If evidence is
insufficient, fail the task rather than inventing a group.
