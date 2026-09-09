"""Script d'exécution des tests unitaires avec l'environnement virtuel du projet."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).resolve().parent
    venv_python = project_root / "venv" / "Scripts" / "python.exe"

    python_bin = str(venv_python) if venv_python.exists() else sys.executable
    cmd = [python_bin, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]

    print(f"Exécution des tests avec : {python_bin}")
    res = subprocess.run(cmd, cwd=str(project_root))
    sys.exit(res.returncode)


if __name__ == "__main__":
    main()
