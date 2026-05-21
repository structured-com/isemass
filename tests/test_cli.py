from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from isemass.cli import cli


def _patch_config_dir(monkeypatch, path: Path) -> Path:
    config_dir = path / "config"
    monkeypatch.setattr("isemass.config.user_config_dir", lambda app_name: str(config_dir))
    return config_dir


def test_root_help_shows_commands() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "init" in result.output
    assert "coa" in result.output
    assert "swauth" in result.output


def test_coa_help_shows_requested_options() -> None:
    result = CliRunner().invoke(cli, ["coa", "--help"])

    assert result.exit_code == 0
    assert "-i, --input-file" in result.output
    assert "-u, --username" in result.output
    assert "-w, --max-workers" in result.output
    assert "--host" in result.output
    assert "-n, --node" in result.output
    assert "-k, --insecure" in result.output


def test_init_creates_settings_file(monkeypatch, tmp_path: Path) -> None:
    config_dir = _patch_config_dir(monkeypatch, tmp_path)

    result = CliRunner().invoke(cli, ["init"])

    settings_file = config_dir / "settings.toml"
    assert result.exit_code == 0
    assert settings_file.exists()
    assert "[coa]" in settings_file.read_text(encoding="utf-8")
    assert str(settings_file) in result.output.replace("\n", "")


def test_init_refuses_overwrite_without_force(monkeypatch, tmp_path: Path) -> None:
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    settings_file = config_dir / "settings.toml"
    settings_file.write_text("existing = true\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["init"])

    assert result.exit_code != 0
    assert "already exists" in result.output
    assert settings_file.read_text(encoding="utf-8") == "existing = true\n"


def test_init_force_overwrites_existing_file(monkeypatch, tmp_path: Path) -> None:
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    settings_file = config_dir / "settings.toml"
    settings_file.write_text("existing = true\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["init", "--force"])

    assert result.exit_code == 0
    assert "[coa]" in settings_file.read_text(encoding="utf-8")


def test_coa_cli_options_override_settings(monkeypatch, tmp_path: Path) -> None:
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    configured_input = tmp_path / "configured-macs.txt"
    configured_input.write_text("001122334455\n", encoding="utf-8")
    cli_input = tmp_path / "cli-macs.txt"
    cli_input.write_text("aabbccddeeff\n", encoding="utf-8")
    (config_dir / "settings.toml").write_text(
        f"""
[coa]
input_file = "{configured_input}"
username = "config-user"
host = "config-host.example.com"
node = "config-node"
max_workers = 5
insecure = false
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "coa",
            "--input-file",
            str(cli_input),
            "--username",
            "cli-user",
            "--max-workers",
            "9",
            "--host",
            "cli-host.example.com",
            "--node",
            "cli-node",
            "--insecure",
        ],
    )

    assert result.exit_code == 0
    normalized_output = result.output.replace("\n", "")
    assert f"Input file: {cli_input}" in normalized_output
    assert "Username: cli-user" in result.output
    assert "Max workers: 9" in result.output
    assert "Host: cli-host.example.com" in result.output
    assert "Node: cli-node" in result.output
    assert "Insecure: True" in result.output


def test_coa_missing_required_resolved_values_errors(monkeypatch, tmp_path: Path) -> None:
    _patch_config_dir(monkeypatch, tmp_path)

    result = CliRunner().invoke(cli, ["coa"])

    assert result.exit_code == 2
    assert "Missing required option(s)" in result.output
    assert "--input-file" in result.output
    assert "--host" in result.output
    assert "--node" in result.output


def test_coa_prompts_for_username_when_missing(monkeypatch, tmp_path: Path) -> None:
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    input_file = tmp_path / "macs.txt"
    input_file.write_text("001122334455\n", encoding="utf-8")
    (config_dir / "settings.toml").write_text(
        f"""
[coa]
input_file = "{input_file}"
host = "ise-mnt.example.com"
node = "ise-psn01"
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["coa"], input="prompt-user\n")

    assert result.exit_code == 0
    assert "API username:" in result.output
    assert "Username: prompt-user" in result.output
