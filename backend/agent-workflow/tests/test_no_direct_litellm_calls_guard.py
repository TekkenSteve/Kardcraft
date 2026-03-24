import subprocess
from pathlib import Path


def test_no_direct_litellm_runtime_calls_guard_script():
    script = Path("scripts/check_no_direct_litellm_calls.sh")
    result = subprocess.run([str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
