import subprocess
import sys

import pytest

from semipulse_sentinel.cli import main


def test_cli_reports_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == "semipulse-sentinel 0.1.0"


def test_cli_help_names_the_program(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    assert "usage: semipulse-sentinel" in capsys.readouterr().out


def test_python_module_entrypoint_reports_the_package_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "semipulse_sentinel", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "semipulse-sentinel 0.1.0"
    assert result.stderr == ""
