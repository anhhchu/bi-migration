"""Resolve which semantic-group proposal the migration Job should approve.

The proposal Job and the migration Job are separate Lakeflow Jobs. A reviewer
approves a proposal by starting the migration Job, either from the App (which
always passes ``proposal_run_id``) or directly in the Jobs UI/CLI. This module
makes that handoff explicit and safe:

* An explicit ``proposal_run_id`` (run ID or run folder name) always wins.
* With no ID, the Job resolves the proposal automatically only when exactly one
  current proposal is awaiting approval. A newer proposal for the same input
  folder supersedes older ones, so re-running a proposal does not create
  ambiguity. Several pending proposals for different inputs fail fast with a
  list of copy-paste commands instead of guessing.
* A proposal can be migrated once. Re-migrating requires ``force_rerun``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any

from .manifest import resolve_run_root


AWAITING_APPROVAL_STATUS = "GROUPING_REVIEW_REQUIRED"
GROUPS_INDEX_RELATIVE_PATH = Path("_internal") / "semantic-groups-index.json"


class ProposalHandoffError(ValueError):
    """Raised when the migration Job cannot safely pick a proposal."""


@dataclass(frozen=True)
class ProposalCandidate:
    run_root: Path
    workflow_run_id: str
    status: str
    created_at: str
    input_volume_path: str
    group_names: tuple[str, ...]
    superseded_by: str | None = None

    @property
    def run_folder(self) -> str:
        return self.run_root.name

    @property
    def manifest_path(self) -> Path:
        return self.run_root / "manifest.json"

    @property
    def groups_index_path(self) -> Path:
        return self.run_root / GROUPS_INDEX_RELATIVE_PATH


@dataclass(frozen=True)
class ResolvedProposal:
    candidate: ProposalCandidate
    resolution: str  # "explicit" or "automatic"
    forced: bool = False


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_candidate(run_root: Path) -> ProposalCandidate | None:
    manifest = _read_json(run_root / "manifest.json")
    if manifest is None:
        return None
    groups_index = _read_json(run_root / GROUPS_INDEX_RELATIVE_PATH) or {}
    return ProposalCandidate(
        run_root=run_root,
        workflow_run_id=str(manifest.get("workflow_run_id") or run_root.name.split("--")[0]),
        status=str(manifest.get("status") or "UNKNOWN"),
        created_at=str(manifest.get("created_at") or ""),
        input_volume_path=str((manifest.get("input") or {}).get("input_volume_path") or ""),
        group_names=tuple(
            str(group.get("display_name") or group.get("group_id"))
            for group in groups_index.get("groups", [])
        ),
    )


def list_proposals(output_volume_path: str | Path) -> list[ProposalCandidate]:
    """Return every run awaiting approval, newest first, marking superseded ones."""
    runs_root = Path(output_volume_path) / "runs"
    if not runs_root.is_dir():
        return []
    awaiting = [
        candidate
        for run_root in runs_root.iterdir()
        if run_root.is_dir()
        and (run_root / GROUPS_INDEX_RELATIVE_PATH).is_file()
        and (candidate := load_candidate(run_root)) is not None
        and candidate.status == AWAITING_APPROVAL_STATUS
    ]
    awaiting.sort(key=lambda item: (item.created_at, item.run_folder), reverse=True)
    newest_by_input: dict[str, ProposalCandidate] = {}
    result = []
    for candidate in awaiting:
        newest = newest_by_input.setdefault(candidate.input_volume_path, candidate)
        if newest is not candidate:
            candidate = replace(candidate, superseded_by=newest.run_folder)
        result.append(candidate)
    return result


def migration_command(migration_job_id: str | int | None, proposal_run_id: str) -> str:
    job = str(migration_job_id) if migration_job_id else "<migration-job-id>"
    payload = json.dumps({"job_parameters": {"proposal_run_id": proposal_run_id}})
    return f"databricks jobs run-now {job} --json '{payload}' --no-wait --profile <profile>"


def _describe(candidate: ProposalCandidate, migration_job_id: str | int | None) -> str:
    groups = ", ".join(candidate.group_names) or "no groups recorded"
    return (
        f"  - {candidate.run_folder} (input {candidate.input_volume_path or 'unknown'}; groups: {groups})\n"
        f"      {migration_command(migration_job_id, candidate.workflow_run_id)}"
    )


def resolve_proposal(
    output_volume_path: str | Path,
    proposal_run_id: str = "",
    *,
    force_rerun: bool = False,
    migration_job_id: str | int | None = None,
) -> ResolvedProposal:
    reference = proposal_run_id.strip()
    if reference:
        try:
            run_root = resolve_run_root(output_volume_path, reference)
        except (FileNotFoundError, ValueError) as error:
            raise ProposalHandoffError(str(error)) from error
        candidate = load_candidate(run_root)
        if candidate is None or not candidate.groups_index_path.is_file():
            raise ProposalHandoffError(
                f"Run {run_root.name} has no completed semantic-group proposal. "
                "Wait for Propose semantic groups to finish, or choose another run."
            )
        if candidate.status != AWAITING_APPROVAL_STATUS and not force_rerun:
            raise ProposalHandoffError(
                f"Proposal {candidate.run_folder} is not awaiting approval (status {candidate.status}); "
                "it has already been sent to migration. To migrate it again deliberately, "
                "rerun with force_rerun=true."
            )
        return ResolvedProposal(candidate, "explicit", forced=candidate.status != AWAITING_APPROVAL_STATUS)

    proposals = list_proposals(output_volume_path)
    current = [item for item in proposals if item.superseded_by is None]
    if not current:
        raise ProposalHandoffError(
            "No semantic-group proposal is awaiting approval. Run Propose semantic groups first, "
            "or pass proposal_run_id to choose a specific run."
        )
    if len(current) > 1:
        listing = "\n".join(_describe(item, migration_job_id) for item in current)
        raise ProposalHandoffError(
            f"{len(current)} proposals for different inputs are awaiting approval, so the Job will not guess. "
            "Rerun with proposal_run_id set to the run you reviewed:\n" + listing
        )
    return ResolvedProposal(current[0], "automatic")


def build_handoff(
    *,
    workflow_run_id: str,
    run_folder: str,
    migration_job_id: str | int | None,
    migration_job_url: str | None,
) -> dict[str, Any]:
    """Instructions shown in the grouping review for approving this exact proposal."""
    return {
        "proposal_run_id": workflow_run_id,
        "run_folder": run_folder,
        "migration_job_id": str(migration_job_id) if migration_job_id else None,
        "migration_job_url": migration_job_url,
        "cli_command": migration_command(migration_job_id, workflow_run_id),
        "jobs_ui_steps": [
            "Open the migration Job.",
            "Select Run now with different parameters.",
            f"Set proposal_run_id to {workflow_run_id} and select Run.",
        ],
        "automatic_resolution": (
            "Run now with no parameters also works while this is the only current proposal awaiting "
            "approval. If several are pending, the Job stops in seconds and lists them."
        ),
    }
