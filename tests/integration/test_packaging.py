"""Wheel-level package-resource acceptance."""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest


def _venv_python(environment: Path) -> Path:
    for relative in (Path("Scripts/python.exe"), Path("bin/python")):
        candidate = environment / relative
        if candidate.is_file():
            return candidate
    raise AssertionError("virtual environment has no Windows or POSIX Python")


@pytest.mark.parametrize(
    "relative", [Path("Scripts/python.exe"), Path("bin/python")]
)
def test_venv_python_supports_windows_and_posix_layouts(
    tmp_path: Path, relative: Path
) -> None:
    expected = tmp_path / relative
    expected.parent.mkdir(parents=True)
    expected.touch()

    assert _venv_python(tmp_path) == expected


def test_isolated_wheel_install_contains_daily_template_and_stylesheet(
    tmp_path: Path,
) -> None:
    project = Path(__file__).parents[2]
    wheel_dir = tmp_path / "wheel"
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(wheel_dir),
        ],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    wheels = tuple(wheel_dir.glob("semipulse_sentinel-*.whl"))
    assert len(wheels) == 1

    environment = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True, clear=True).create(environment)
    python = _venv_python(environment)
    install = subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "--disable-pip-version-check",
            "install",
            "--no-deps",
            str(wheels[0]),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert install.returncode == 0, install.stderr
    probe_cwd = tmp_path / "isolated-probe"
    probe_cwd.mkdir()
    assert not probe_cwd.resolve().is_relative_to(project.resolve())
    probe_environment = os.environ.copy()
    probe_environment.pop("PYTHONHOME", None)
    probe_environment.pop("PYTHONPATH", None)
    probe_environment["PYTHONNOUSERSITE"] = "1"
    probe = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            (
                "from importlib.resources import files; from pathlib import Path; "
                "import semipulse_sentinel, sys; "
                "assert sys.flags.isolated == 1; "
                "module=Path(semipulse_sentinel.__file__).resolve(); "
                "assert module.is_relative_to(Path(sys.prefix).resolve()); "
                "root=files('semipulse_sentinel'); "
                "assert '<!doctype html>' in "
                "root.joinpath('templates/report.html.j2').read_text('utf-8'); "
                "assert 'Trading decision summary' in "
                "root.joinpath('templates/report.html.j2').read_text('utf-8'); "
                "assert ':root' in "
                "root.joinpath('static/report.css').read_text('utf-8'); "
                "assert '.chart-card' in "
                "root.joinpath('static/report.css').read_text('utf-8')"
            ),
        ],
        cwd=probe_cwd,
        env=probe_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr
