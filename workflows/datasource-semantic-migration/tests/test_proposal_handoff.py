import json
from pathlib import Path

import pytest

from datasource_semantic_migration.proposal_handoff import (
    ProposalHandoffError,
    build_handoff,
    list_proposals,
    resolve_proposal,
)


def make_run(
    output: Path,
    run_id: str,
    *,
    created_at: str,
    input_path: str = "/Volumes/main/bi/inputs/project-a",
    status: str = "GROUPING_REVIEW_REQUIRED",
    groups: tuple[str, ...] = ("Superstore",),
    with_index: bool = True,
) -> Path:
    run_root = output / "runs" / f"{run_id}--{created_at.replace(':', '-')}"
    (run_root / "_internal").mkdir(parents=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "workflow_run_id": run_id,
                "status": status,
                "created_at": created_at,
                "input": {"input_volume_path": input_path},
            }
        ),
        encoding="utf-8",
    )
    if with_index:
        (run_root / "_internal" / "semantic-groups-index.json").write_text(
            json.dumps({"workflow_run_id": run_id, "groups": [{"display_name": name} for name in groups]}),
            encoding="utf-8",
        )
    return run_root


def test_single_pending_proposal_resolves_without_a_run_id(tmp_path):
    make_run(tmp_path, "100", created_at="2026-11-20T10:00:00Z", status="PASS_SEMANTIC_ONLY")
    pending = make_run(tmp_path, "200", created_at="2026-11-21T10:00:00Z")

    resolved = resolve_proposal(tmp_path)

    assert resolved.resolution == "automatic"
    assert resolved.candidate.run_root == pending


def test_newer_proposal_for_same_input_supersedes_older_one(tmp_path):
    make_run(tmp_path, "100", created_at="2026-11-20T10:00:00Z")
    newest = make_run(tmp_path, "200", created_at="2026-11-21T10:00:00Z")

    proposals = list_proposals(tmp_path)

    assert [item.workflow_run_id for item in proposals] == ["200", "100"]
    assert proposals[1].superseded_by == newest.name
    assert resolve_proposal(tmp_path).candidate.run_root == newest


def test_pending_proposals_for_different_inputs_require_an_explicit_choice(tmp_path):
    make_run(tmp_path, "100", created_at="2026-11-20T10:00:00Z", input_path="/Volumes/main/bi/inputs/a")
    make_run(tmp_path, "200", created_at="2026-11-21T10:00:00Z", input_path="/Volumes/main/bi/inputs/b")

    with pytest.raises(ProposalHandoffError) as error:
        resolve_proposal(tmp_path, migration_job_id="268")

    message = str(error.value)
    assert "will not guess" in message
    assert "databricks jobs run-now 268" in message
    assert '"proposal_run_id": "100"' in message and '"proposal_run_id": "200"' in message


def test_explicit_run_id_or_folder_selects_that_proposal(tmp_path):
    older = make_run(tmp_path, "100", created_at="2026-11-20T10:00:00Z", input_path="/Volumes/main/bi/inputs/a")
    make_run(tmp_path, "200", created_at="2026-11-21T10:00:00Z", input_path="/Volumes/main/bi/inputs/b")

    assert resolve_proposal(tmp_path, "100").candidate.run_root == older
    assert resolve_proposal(tmp_path, older.name).resolution == "explicit"


def test_already_migrated_proposal_is_rejected_unless_forced(tmp_path):
    make_run(tmp_path, "100", created_at="2026-11-20T10:00:00Z", status="MIGRATION_RUNNING")

    with pytest.raises(ProposalHandoffError, match="force_rerun=true"):
        resolve_proposal(tmp_path, "100")

    forced = resolve_proposal(tmp_path, "100", force_rerun=True)
    assert forced.forced is True


def test_missing_or_incomplete_proposals_explain_the_next_step(tmp_path):
    with pytest.raises(ProposalHandoffError, match="Run Propose semantic groups first"):
        resolve_proposal(tmp_path)
    make_run(tmp_path, "100", created_at="2026-11-20T10:00:00Z", with_index=False)
    with pytest.raises(ProposalHandoffError, match="no completed semantic-group proposal"):
        resolve_proposal(tmp_path, "100")
    with pytest.raises(ProposalHandoffError, match="not found"):
        resolve_proposal(tmp_path, "999")


def test_handoff_names_the_exact_run_and_command():
    handoff = build_handoff(
        workflow_run_id="200",
        run_folder="200--2026-11-21T10-00-00Z",
        migration_job_id="268",
        migration_job_url="https://workspace.example/jobs/268",
    )

    assert handoff["proposal_run_id"] == "200"
    assert handoff["cli_command"].startswith("databricks jobs run-now 268 --json")
    assert '"proposal_run_id": "200"' in handoff["cli_command"]
    assert "Set proposal_run_id to 200" in handoff["jobs_ui_steps"][-1]
