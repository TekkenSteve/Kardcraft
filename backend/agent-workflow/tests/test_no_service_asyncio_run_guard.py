import subprocess
from pathlib import Path


def test_no_service_asyncio_run_guard_script():
    script = Path("scripts/check_no_service_asyncio_run.sh")
    result = subprocess.run([str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
