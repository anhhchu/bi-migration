import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def deploy(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("workflow_deploy", ROOT / "deploy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "prompts" / "tableau").mkdir(parents=True)
    (tmp_path / "prompts" / "tableau" / "import_metric_view.md").write_text("current prompt", encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


def _fake_cli(remote_prompts, calls):
    def run_cli(arguments, *, profile, target=None):
        calls.append(arguments[:2])
        if arguments[:2] == ["api", "get"]:
            name = arguments[2].split("name=", 1)[1].replace("%2F", "/")
            if name not in remote_prompts:
                raise subprocess.CalledProcessError(1, arguments, stderr="Error: scheduled insight not found")
            return {"name": name, "user_prompt": remote_prompts[name]}
        if arguments[:2] == ["current-user", "me"]:
            return {"id": "1"}
        return {"name": "automations/new"}

    return run_cli


def _save_state(deploy, name):
    state_path = deploy.ROOT / ".databricks" / "genie-code-dev.json"
    state_path.parent.mkdir()
    state_path.write_text(json.dumps({"import_metric_view": name}), encoding="utf-8")
    return state_path


def test_deploy_reuses_automation_whose_prompt_matches_file(deploy, monkeypatch):
    _save_state(deploy, "automations/old")
    calls = []
    monkeypatch.setattr(deploy, "run_cli", _fake_cli({"automations/old": "current prompt"}, calls))
    assert deploy.automation_id(profile="DEFAULT", target="dev", automation_name="import_metric_view") == "automations/old"
    assert ["api", "post"] not in calls


@pytest.mark.parametrize("remote_prompts", [{"automations/old": "edited earlier"}, {}])
def test_deploy_creates_automation_when_prompt_changed_or_missing(deploy, monkeypatch, remote_prompts):
    state_path = _save_state(deploy, "automations/old")
    monkeypatch.setattr(deploy, "run_cli", _fake_cli(remote_prompts, []))
    assert deploy.automation_id(profile="DEFAULT", target="dev", automation_name="import_metric_view") == "automations/new"
    assert json.loads(state_path.read_text(encoding="utf-8"))["import_metric_view"] == "automations/new"


def test_deploy_stops_on_unexpected_automation_read_error(deploy, monkeypatch):
    _save_state(deploy, "automations/old")

    def run_cli(arguments, *, profile, target=None):
        raise subprocess.CalledProcessError(1, arguments, stderr="Error: PERMISSION_DENIED")

    monkeypatch.setattr(deploy, "run_cli", run_cli)
    with pytest.raises(subprocess.CalledProcessError):
        deploy.automation_id(profile="DEFAULT", target="dev", automation_name="import_metric_view")
