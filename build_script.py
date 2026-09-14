"""Сборка Windows exe через PyInstaller. Requires: pip install pyinstaller."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def remove_content(folder_path):
    """Remove content of a given folder."""
    for name in os.listdir(folder_path):
        file_path = os.path.join(folder_path, name)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as exc:
            print("Failed to delete %s. Reason: %s" % (file_path, exc))


def main():
    icon = ROOT / "ui" / "resources" / "icons" / "RustDaVinci-icon.ico"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",
        '--name=RustDaVinci',
        "app.py",
    ]
    if icon.exists():
        cmd.insert(-1, "--icon=%s" % icon)
    # OpenCV-шаблон поиска панели лежит в lib/opencv_template.
    cmd.insert(-1, "--add-data=%s%slib/opencv_template" % (ROOT / "lib" / "opencv_template", os.pathsep))
    subprocess.run(cmd, cwd=ROOT, check=True)

    folder = ROOT / "executable"
    if folder.exists():
        remove_content(str(folder))
    else:
        folder.mkdir(parents=True)

    dist_app = ROOT / "dist" / "RustDaVinci"
    if dist_app.is_dir():
        shutil.move(str(dist_app), str(folder / "RustDaVinci"))
    else:
        # onefile-режим: переносим exe
        for exe in (ROOT / "dist").glob("RustDaVinci*"):
            shutil.move(str(exe), str(folder / exe.name))

    for leftover in ("build", "dist"):
        path = ROOT / leftover
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    spec = ROOT / "RustDaVinci.spec"
    if spec.exists():
        spec.unlink()
    print("Готово: %s" % folder)


if __name__ == "__main__":
    main()
