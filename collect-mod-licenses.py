"""Copy installed dependency license files into the local application bundle."""
from importlib import metadata
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parent
output = root / "input/mod-build-data/licenses"
output.mkdir(parents=True, exist_ok=True)
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if not python_license.is_file():
    raise RuntimeError("Python runtime license was not found")
shutil.copy2(python_license, output / "PYTHON-LICENSE.txt")
for license_file in (root / "third_party/licenses").glob("*.txt"):
    shutil.copy2(license_file, output / license_file.name)
summary = []
for distribution in metadata.distributions():
    name = distribution.metadata.get("Name", "unknown")
    summary.append(f"{name} {distribution.version}\n{distribution.metadata.get('License-Expression') or distribution.metadata.get('License') or 'See included license files / project website'}\n")
    for file in distribution.files or []:
        if any(token in str(file).lower() for token in ("license", "copying", "notice")):
            source = distribution.locate_file(file)
            if source.is_file() and source.suffix.lower() not in (".dll", ".exe", ".py", ".pyc"):
                destination = output / name / Path(str(file))
                if not destination.resolve().is_relative_to(output.resolve()):
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
(output / "DEPENDENCIES.txt").write_text("\n".join(sorted(summary)), encoding="utf-8")
(output / "Qt-LGPL-NOTICE.txt").write_text(
    "This local application uses the unmodified PySide6/Qt libraries through dynamically loaded DLLs.\n"
    "PySide6/Qt is available under LGPLv3 and other applicable licenses; see included upstream license files.\n"
    "The Qt DLLs remain separate in the _internal directory; users may replace compatible libraries.\n"
    "Reverse engineering for debugging modifications to LGPL-covered components is not prohibited by this application.\n"
    "Corresponding upstream source: https://download.qt.io/official_releases/QtForPython/\n"
    "https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://code.qt.io/cgit/qt/\n"
    "If distributing a build publicly, review all dependency license obligations for the exact binary versions.\n",
    encoding="utf-8",
)
print(f"Dependency notices copied to {output}")
