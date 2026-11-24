from datasource_semantic_migration.reporting import (
    build_grouping_review,
    build_group_review,
    build_repair_review,
    build_workflow_review,
    render_grouping_review_html,
    render_repair_html,
    render_workflow_html,
)


def test_grouping_review_renders_membership_targets_and_approval_handoff():
    groups = [
        {
            "group_index": 0,
            "group_name": "Superstore",
            "status": "READY_FOR_PREFLIGHT",
            "will_migrate": True,
            "datasources": [
                {"name": "Orders", "file": "Superstore.tdsx", "role": "PRIMARY"},
                {"name": "Menu", "file": "Superstore.tdsx", "role": "SUPPORTING"},
            ],
            "target_tables": ["main.superstore.sales_order_line_bitemporal"],
            "candidate_metric_view": "main.bi_migration.bim_superstore_candidate",
        }
    ]
    review = build_grouping_review(
        workflow_run_id="123",
        groups_index_path="/Volumes/main/bi/runs/123/_internal/semantic-groups-index.json",
        grouping_proposal_path="/Volumes/main/bi/runs/123/_internal/semantic-grouping-proposal.json",
        groups=groups,
        excluded_helpers=[{"datasource_id": "helper-1", "reason": "Navigation only"}],
        migration_job_id="456",
        migration_job_url="https://workspace.example/jobs/456",
    )
    html = render_grouping_review_html(review)

    assert review["status"] == "AWAITING_APPROVAL"
    assert "Superstore" in html
    assert "sales_order_line_bitemporal" in html
    assert "Open migration Job" in html
    assert "Navigation only" in html
    assert "href='https://workspace.example/jobs/456'" in html
    assert review["handoff"]["proposal_run_id"] == "123"
    assert "proposal_run_id <code>123</code>" in html
    assert "Run now with different parameters" in html
    assert "databricks jobs run-now 456" in html
    assert "force_rerun=true" in html


def test_workflow_review_surfaces_actions_and_translation_evidence():
    group = {
        "group_id": "superstore",
        "group_path": "/Volumes/main/bi/runs/1/groups/superstore",
        "source_summary_path": "/Volumes/main/bi/runs/1/groups/superstore/source-summary.json",
    }
    final_result = {
        "status": "PARTIAL",
        "metric_view_fqn": "main.bi.bim_superstore_candidate",
        "evaluation_path": "/Volumes/main/bi/runs/1/groups/superstore/evaluation.json",
    }
    evaluation = {
        "agent_result": {
            "dimensions_created": ["Region"],
            "measures_created": ["Sales"],
            "parameters_created": [],
            "items_not_translated": [
                {"name": "Sales above Target?", "reason": "No approved mapping"},
                {"name": ":Measure Names", "reason": "Tableau generated UI field"},
            ],
            "approximations": [{"name": "Returned", "detail": "Boolean translated to Yes"}],
            "validation": {"totals_match": True},
        },
        "findings": [
            {
                "code": "EXTERNAL_DATASOURCE_REFERENCE",
                "severity": "ERROR",
                "calculation_name": "Sales above Target?",
            },
            {
                "code": "AGGREGATION_REQUIRES_COMPILATION",
                "severity": "WARNING",
                "calculation_name": "Sales Forecast",
            },
        ],
    }

    group_review = build_group_review(group=group, final_result=final_result, evaluation=evaluation)
    workflow_review = build_workflow_review(workflow_run_id="1", groups=[group_review])
    html = render_workflow_html(workflow_review)

    assert workflow_review["status"] == "ACTION_REQUIRED"
    assert workflow_review["totals"]["blocked"] == 1
    assert workflow_review["totals"]["business_items_not_translated"] == 1
    assert [item["action_id"] for item in group_review["recommended_actions"]] == [
        "map_external_datasource",
        "confirm_aggregations",
        "review_approximations",
    ]
    assert "Sales above Target?" in html
    assert "Validation evidence" in html


def test_repair_review_renders_coverage_and_blocking_metric():
    summary = {
        "workflow_run_id": "1",
        "group_id": "superstore",
        "repair_series_id": "2",
        "attempt": 1,
        "status": "BLOCKED_EVIDENCE",
        "readiness": "BLOCKED_EVIDENCE",
        "coverage_before": {"translation_coverage": 0.8, "governed_disposition_coverage": 0.8},
        "coverage_after": {"translation_coverage": 0.9, "governed_disposition_coverage": 0.9},
        "candidate_changed": True,
        "rolled_back": False,
        "regressions": [],
        "attempt_dir": "/Volumes/main/bi/runs/1/groups/superstore/_internal/repair/runs/2/attempt-01",
    }
    evaluation = {
        "blocking_findings": [
            {
                "source_name": "Sales above Target?",
                "failure_codes": ["EXTERNAL_DATASOURCE_UNMAPPED"],
                "repair_route": "MAPPING_REVISION",
            }
        ],
        "relationship_blockers": [],
        "scorecards": [],
    }

    review = build_repair_review(summary=summary, evaluation=evaluation)
    html = render_repair_html(review)

    assert "coverage gate(s) failed" in review["headline"]
    assert "Sales above Target?" in html
    assert "Metric View repair review" in html
    assert "Coverage gates" in html
    assert "Evidence artifacts" in html


def test_repair_review_explains_gate_math_query_skip_and_repair_action():
    summary = {
        "workflow_run_id": "1",
        "group_id": "finance",
        "status": "NO_PROGRESS",
        "readiness": "NEEDS_REPAIR",
        "coverage_before": {
            "source_business_metric_count": 10,
            "translated_metric_count": 6,
            "governed_metric_count": 6,
            "evidenced_metric_count": 5,
            "query_candidate_count": 6,
            "query_pass_count": 5,
            "translation_coverage": 0.6,
            "governed_disposition_coverage": 0.6,
            "evidence_coverage": 0.5,
            "measure_queryability": 5 / 6,
        },
        "coverage_after": {
            "source_business_metric_count": 10,
            "translated_metric_count": 6,
            "governed_metric_count": 6,
            "evidenced_metric_count": 5,
            "query_candidate_count": 6,
            "query_pass_count": 5,
            "query_fail_count": 0,
            "query_not_run_count": 1,
            "translation_coverage": 0.6,
            "governed_disposition_coverage": 0.6,
            "evidence_coverage": 0.5,
            "measure_queryability": 5 / 6,
        },
        "policy": {
            "overall_metric_translation_coverage": 0.95,
            "governed_disposition_coverage": 1.0,
            "retained_metric_evidence_coverage": 1.0,
            "measure_queryability": 1.0,
        },
        "rolled_back": True,
        "rollback_reason": "NO_MEASURABLE_PROGRESS",
        "progress": {"measurable_improvement": False, "reason": "No metric count improved."},
        "attempt_dir": "/Volumes/main/bi/runs/1/groups/finance/_internal/repair/attempt-01",
    }
    missing = {
        "metric_id": "m1",
        "source_name": "Profit Ratio",
        "target_name": None,
        "status": "FAILED_SEMANTICS",
        "queryability": "NOT_APPLICABLE",
        "query": {"status": "NOT_APPLICABLE", "reason": "No target measure exists."},
        "failure_codes": ["MISSING_TARGET_MEASURE", "NEEDS_SEMANTIC_TRANSLATION"],
        "repair_route": "GENIE_PATCH",
    }
    review = build_repair_review(
        summary=summary,
        evaluation={"scorecards": [missing], "blocking_findings": [missing], "relationship_blockers": []},
    )
    html = render_repair_html(review)

    assert review["coverage_gates"][0]["after_formula"] == "6/10"
    assert review["coverage_gates"][0]["gap_count"] == 4
    assert review["query_execution"]["not_applicable_metrics"] == ["Profit Ratio"]
    assert review["blocking_findings"][0]["recommended_action"].startswith("Automatic repair asks Genie to add it")
    assert "No target measure exists" in html
    assert "NO_MEASURABLE_PROGRESS" in html


def test_default_sum_aggregation_is_handled_automatically():
    group = {
        "group_id": "cards",
        "group_path": "/Volumes/main/bi/runs/1/groups/cards",
        "source_summary_path": "/Volumes/main/bi/runs/1/groups/cards/_internal/source-summary.json",
    }
    evaluation = {
        "agent_result": {"measures_created": ["Current Value", "% MOM Value Color"]},
        "findings": [
            {"code": "AGGREGATION_REQUIRES_COMPILATION", "severity": "WARNING", "calculation_name": name}
            for name in ("Current Value", "% MOM Value Color")
        ],
    }
    metric_view = {
        "measures": [
            {"name": "Current Value", "expr": "SUM(trxn_amount_major) FILTER (WHERE `Current Period T/F`)"},
            {"name": "% MOM Value Color", "expr": "CASE WHEN MEASURE(`% MOM Value`) > 0 THEN 'Up' END"},
        ]
    }
    review = build_group_review(
        group=group,
        final_result={"status": "PARTIAL", "metric_view_fqn": "main.bi.cards"},
        evaluation=evaluation,
        metric_view=metric_view,
    )
    html = render_workflow_html(build_workflow_review(workflow_run_id="1", groups=[review]))
    automatic = {name: item["detail"] for item in review["action_groups"]["automatic"] for name in item["names"]}

    # SUM matches Tableau's default; the MEASURE()-based label inherits its aggregation. Neither needs a person.
    assert not any(item["action_id"] == "confirm_aggregations" for item in review["recommended_actions"])
    assert "Aggregated explicitly" in automatic["Current Value"]
    assert "% MOM Value Color" not in automatic
    assert "Handled automatically" in html and "Why a person is needed" in html
    assert review["gate"]["stages"][3]["key"] == "parity"
    # Reading order: next step, stage strip, action items, then collapsed evidence.
    assert html.index("class='next") < html.index("class='stages'") < html.index("<h3>Action items</h3>")
    assert html.index("<h3>Action items</h3>") < html.index("Stage evidence")
    assert "Not run" in html


def test_report_links_the_metric_view_to_catalog_explorer():
    from datasource_semantic_migration.report_html import catalog_explorer_url

    assert (
        catalog_explorer_url("https://w.example/", "main.bi_migration.bim_sales_candidate")
        == "https://w.example/explore/data/main/bi_migration/bim_sales_candidate"
    )
    assert catalog_explorer_url(None, "main.bi.x") is None
    review = build_group_review(
        group={"group_id": "sales", "group_path": "/Volumes/main/bi/runs/1/groups/sales"},
        final_result={"status": "PARTIAL", "metric_view_fqn": "main.bi.bim_sales_candidate"},
        evaluation={"agent_result": {}, "findings": []},
    )
    html = render_workflow_html({"workspace_url": "https://w.example", **build_workflow_review(workflow_run_id="1", groups=[review])})
    assert "href='https://w.example/explore/data/main/bi/bim_sales_candidate'" in html
