import io
import subprocess
import sys

import pytest

import semipulse_sentinel.cli as cli
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


def test_cli_help_exposes_source_only_workflow_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    for command in (
        "build-source",
        "validate-source",
        "decide-source-publication",
        "check-market-session",
        "notify-source",
    ):
        assert command in output


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


def test_json_output_is_safe_for_a_non_unicode_windows_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252", write_through=True)
    monkeypatch.setattr(cli.sys, "stdout", stream)

    cli._emit({"source_title": "狼来了的故事"}, json_output=True)

    assert b"\\u72fc\\u6765\\u4e86" in buffer.getvalue()
