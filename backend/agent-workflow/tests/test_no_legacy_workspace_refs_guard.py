import subprocess
from pathlib import Path


def test_no_legacy_workspace_runtime_reference_guard_script():
    script = Path("scripts/check_no_legacy_workspace_refs.sh")
    result = subprocess.run([str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
