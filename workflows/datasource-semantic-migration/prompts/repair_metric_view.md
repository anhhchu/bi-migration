# Repair Candidate Metric View — Genie Code Prompt

You are running unattended inside a bounded Metric View repair attempt.

- Repair request: `{{genie_request_path}}`
- Structured patch output: `{{genie_patch_path}}`
- Candidate YAML output: `{{genie_candidate_path}}`

Read the repair request, source and target Metric IR, scorecards, approved group mapping, target profile, and deterministic candidate paths referenced by that request.

Translate only findings routed as `GENIE_PATCH`. Do not modify Unity Catalog, mappings, dashboards, Genie Agents, source files, or any asset other than the two required output artifacts. Use only physical target tables already declared by the approved group mapping. Preserve every previously passing measure and dimension.

Write `{{genie_patch_path}}` as JSON containing: `schema_version`, `patch_id`, `status`, `failure_ids`, `operations`, `notes`, and `confidence`. Status must be `APPLIED`, `NOOP`, or `UNRESOLVABLE`.

When status is `APPLIED`, write the complete proposed Metric View YAML to `{{genie_candidate_path}}`. Start from the deterministic candidate, apply only the structured operations, and preserve the requested candidate FQN. When evidence cannot establish one correct translation, write `UNRESOLVABLE` and do not write candidate YAML. Deterministic downstream code validates lineage, deploys the candidate, runs regressions, and decides acceptance.
