"""Run the dedicated bundle tool on one disposable cache copy."""
from pathlib import Path
import subprocess
import sys
import os

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

root = Path(__file__).resolve().parent / "card-probe"
try:
    result = subprocess.run(
        [str(root / "byd_mod_studio.exe")], cwd=root,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        input=b"y\n\ny\nn\nn\n",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90,
    )
except subprocess.TimeoutExpired as exc:
    output = exc.stdout or b""
    (root / "probe.log").write_bytes(output)
    print(output.decode("utf-8", errors="replace"))
    raise SystemExit("Tool timed out; log preserved")
(root / "probe.log").write_bytes(result.stdout)
print(result.stdout.decode("utf-8", errors="replace"))
print(f"EXIT_CODE={result.returncode}")
