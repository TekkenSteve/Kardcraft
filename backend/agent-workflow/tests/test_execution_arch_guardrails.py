import subprocess
from pathlib import Path


def test_execution_arch_guardrails_script():
    script = Path("scripts/check_execution_arch_guardrails.sh")
    result = subprocess.run([str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr

