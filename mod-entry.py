"""Keep packaged startup errors readable even before Qt has been imported."""
import faulthandler
import json
import os
from pathlib import Path
import sys
import traceback

log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SVWBCardMod"
log_dir.mkdir(parents=True, exist_ok=True)
log = (log_dir / "startup.log").open("a", encoding="utf-8", buffering=1)
sys.stdout = log
sys.stderr = log
faulthandler.enable(log)
smoke = "--smoke-test" in sys.argv
if smoke:
    faulthandler.dump_traceback_later(15, repeat=True, file=log)
try:
    print("Starting SVWBCardMod")
    from svwbmod import main
    print("Imports complete")
    code = main()
except Exception:
    details = traceback.format_exc()
    print(details)
    if smoke:
        path = Path(sys.argv[sys.argv.index("--smoke-test") + 1])
        path.write_text(json.dumps({"error": details}), encoding="utf-8")
    else:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, f"程序启动失败，详细日志：{log_dir / 'startup.log'}\n\n{details}", "SVWB 卡图工坊", 16)
    code = 1
finally:
    if smoke:
        faulthandler.cancel_dump_traceback_later()
raise SystemExit(code)
