"""Stage the two public demo inputs without duplicating their source originals."""

from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


DEMO_INPUTS = (
    "examples/elastic_minimal.json",
    "UMATs/UMATs/ICP/elasticity/elastic.f",
)


class BuildWithDemo(build_py):
    def run(self):
        super().run()
        root = Path(__file__).resolve().parent
        for relative in DEMO_INPUTS:
            target = Path(self.build_lib) / "umat_oti/app/demo_inputs" / relative
            self.mkpath(str(target.parent))
            self.copy_file(str(root / relative), str(target))


setup(cmdclass={"build_py": BuildWithDemo})