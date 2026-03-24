from pathlib import Path


def test_temporal_worker_no_rust_services_dependency():
    worker_path = Path("backend/agent-workflow/src/kardcraft/temporal/worker.py")
    text = worker_path.read_text(encoding="utf-8")
    assert "RustServicesClient" not in text
    assert "rust_services_addr" not in text
    assert "create_default_execution_service" not in text
    assert "WorkspaceService" not in text


def test_agent_activities_uses_workspace_id_mapping():
    activities_path = Path(
        "backend/agent-workflow/src/kardcraft/temporal/activities/agent_activities.py"
    )
    text = activities_path.read_text(encoding="utf-8")
    assert 'input_payload.get("session_id")' in text
    assert '"workspace_id": workspace_id' in text


def test_shell_uses_execution_port_engine():
    shell_path = Path("backend/agent-workflow/src/kardcraft/agent_skills/shell.py")
    text = shell_path.read_text(encoding="utf-8")
    assert "ExecutionPort" in text
    assert "ShellExecutionEngine" in text
    assert "ToolExecutionFacade" not in text


def test_agent_skills_exports_code_middleware():
    init_path = Path("backend/agent-workflow/src/kardcraft/agent_skills/__init__.py")
    text = init_path.read_text(encoding="utf-8")
    assert "CodeMiddleware" in text
