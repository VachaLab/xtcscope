"""Entry point for `python -m xtcscope` and for the PyInstaller build."""

# an absolute import: PyInstaller runs this file as a script, outside the package
from xtcscope.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
