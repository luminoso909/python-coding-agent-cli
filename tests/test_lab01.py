"""验证 Lab01 CLI 与项目脚手架没有被后续实验破坏。"""

from pathlib import Path

from typer.testing import CliRunner

from init_project import PACKAGE_DIRS, PLAIN_DIRS, scaffold
from main import APP_NAME, VERSION, app


runner = CliRunner()


def test_hello_default_and_custom_name() -> None:
    default = runner.invoke(app, ["hello"])
    custom = runner.invoke(app, ["hello", "--name", "Lucius"])

    assert default.exit_code == 0
    assert f"{APP_NAME} v{VERSION}" in default.output
    assert f"Hello, Developer! Welcome to {APP_NAME}." in default.output
    assert custom.exit_code == 0
    assert f"Hello, Lucius! Welcome to {APP_NAME}." in custom.output


def test_hello_rejects_blank_name() -> None:
    result = runner.invoke(app, ["hello", "--name", "   "])

    assert result.exit_code == 2
    assert "名字不能为空" in result.output


def test_version_and_dynamic_help_include_all_commands() -> None:
    version_result = runner.invoke(app, ["version"])
    help_result = runner.invoke(app, ["help"])

    assert version_result.exit_code == 0
    assert f"{APP_NAME} v{VERSION}" in version_result.output
    assert help_result.exit_code == 0
    for command in ["agent", "chat", "hello", "help", "version"]:
        assert command in help_result.output


def test_scaffold_is_idempotent_and_preserves_existing_init(tmp_path: Path) -> None:
    first = scaffold(tmp_path)
    sentinel = tmp_path / "app" / "llm" / "__init__.py"
    sentinel.write_text("SENTINEL = True\n", encoding="utf-8")
    second = scaffold(tmp_path)

    assert first == (len(PLAIN_DIRS) + len(PACKAGE_DIRS), len(PACKAGE_DIRS))
    assert second == (0, 0)
    assert sentinel.read_text(encoding="utf-8") == "SENTINEL = True\n"
    assert all((tmp_path / path).is_dir() for path in PLAIN_DIRS + PACKAGE_DIRS)
    assert all(
        (tmp_path / path / "__init__.py").is_file() for path in PACKAGE_DIRS
    )
