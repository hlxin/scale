"""Build hook: bundle released specifications, skills and examples into the wheel.

The repository keeps them beside the code (scale-release.yaml, core/, domain/,
releases/, skills/, governance/, ...). A regular (non-editable) build copies them into
``scale/_data``, mirroring the repository layout, so that ``pip install`` or ``uvx`` works without a
checkout. Editable installs read them from the checkout directly. What to bundle is declared once,
in ``tools/layout.py`` (loaded by path: the package is not importable while it is built).
"""

import importlib.util
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("_scale_layout", ROOT / "tools" / "layout.py")
layout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(layout)


class BuildWithData(build_py):
    def run(self):
        super().run()
        dest = Path(self.build_lib) / "scale" / "_data"
        if dest.exists():
            shutil.rmtree(dest)
        for item in layout.BUNDLE:
            src = ROOT / item
            if src.is_dir():
                shutil.copytree(src, dest / item, ignore=layout.bundle_ignore(ROOT))
            elif src.is_file():
                (dest / item).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest / item)
            else:      # a silently missing item would ship a wheel that fails only when the item is read
                raise FileNotFoundError(f"setup.py: bundled item {item} is missing (is MANIFEST.in grafting it?)")


setup(cmdclass={"build_py": BuildWithData})
