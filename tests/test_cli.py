from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from isemass.cli import cli
from isemass.coa import CoaCredentialValidationError, CoaResult
from isemass.swauth import SwauthCredentialValidationError, SwauthResult


def _patch_config_dir(monkeypatch, path: Path) -> Path:
    config_dir = path / "config"
    monkeypatch.setattr("isemass.config.user_config_dir", lambda app_name: str(config_dir))
    return config_dir


def _patch_coa_runner(monkeypatch):
    _patch_coa_preflight(monkeypatch)
    calls = []

    def fake_run_coa_requests(**kwargs):
        calls.append(kwargs)
        for mac in kwargs["macs"]:
            yield CoaResult(
                mac=mac,
                success=True,
                seconds=0.12,
                result_message="mocked success",
            )

    monkeypatch.setattr("isemass.cli.coa_ops.run_coa_requests", fake_run_coa_requests)
    return calls


def _patch_coa_preflight(monkeypatch):
    calls = []

    def fake_validate_coa_credentials(**kwargs):
        calls.append(kwargs)
        return CoaResult(
            mac="02:00:00:00:00:00",
            success=False,
            seconds=0.12,
            result_message="MAC address not a valid session",
        )

    monkeypatch.setattr("isemass.cli.coa_ops.validate_coa_credentials", fake_validate_coa_credentials)
    return calls


def _patch_swauth_runner(monkeypatch):
    _patch_swauth_preflight(monkeypatch)
    calls = []

    def fake_run_swauth_requests(**kwargs):
        callback = kwargs.pop("on_switch_complete", None)
        calls.append(kwargs)
        for switch_address, macs in kwargs["switch_macs"].items():
            for mac in macs:
                yield SwauthResult(
                    switch_address=switch_address,
                    mac=mac,
                    success=True,
                    seconds=0.12,
                    result_message="mocked switch success",
                    show_command=f"show authentication sessions mac {mac} detail",
                    clear_command=f"clear authentication sessions mac {mac}",
                )
            if callback is not None:
                callback(switch_address)

    monkeypatch.setattr("isemass.cli.swauth_ops.run_swauth_requests", fake_run_swauth_requests)
    return calls


def _patch_swauth_preflight(monkeypatch):
    calls = []

    def fake_validate_swauth_credentials(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        "isemass.cli.swauth_ops.validate_swauth_credentials",
        fake_validate_swauth_credentials,
    )
    return calls


def _write_swauth_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    csv_rows = ["switch_address,mac_address"]
    csv_rows.extend(f"{switch_address},{mac}" for switch_address, mac in rows)
    path.write_text("\n".join(csv_rows) + "\n", encoding="utf-8")


def _detailed_result(
    mac: str,
    *,
    success: bool = True,
    seconds: float = 0.12,
    result_message: str = "CoA Succeeded",
    response_status_code: int | None = 200,
    response_text: str | None = "<remoteCoA><results>true</results></remoteCoA>",
    ise_result_value: str | None = "true",
    error_type: str | None = None,
    error_message: str | None = None,
) -> CoaResult:
    return CoaResult(
        mac=mac,
        success=success,
        seconds=seconds,
        result_message=result_message,
        request_url=f"https://ise-mnt.example.com/admin/API/mnt/CoA/Reauth/ise-psn01/{mac}/0",
        verify_tls=False,
        response_status_code=response_status_code,
        response_headers={"Content-Type": "application/xml"},
        response_text=response_text,
        ise_result_value=ise_result_value,
        error_type=error_type,
        error_message=error_message,
    )


def _patch_coa_runner_with_results(monkeypatch, results: list[CoaResult]):
    _patch_coa_preflight(monkeypatch)
    calls = []

    def fake_run_coa_requests(**kwargs):
        calls.append(kwargs)
        yield from results

    monkeypatch.setattr("isemass.cli.coa_ops.run_coa_requests", fake_run_coa_requests)
    return calls


class FakeProgress:
    instances = []

    def __init__(self, *args, **kwargs) -> None:
        self.tasks = []
        self.advances = []
        FakeProgress.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def add_task(self, description, *, total):
        self.tasks.append({"description": description, "total": total})
        return len(self.tasks)

    def advance(self, task) -> None:
        self.advances.append(task)


def _patch_progress(monkeypatch) -> type[FakeProgress]:
    FakeProgress.instances = []
    monkeypatch.setattr("isemass.cli.Progress", FakeProgress)
    return FakeProgress


def test_root_help_shows_commands() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "init" in result.output
    assert "coa" in result.output
    assert "swauth" in result.output


def test_root_version_uses_project_metadata() -> None:
    result = CliRunner().invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert "isemass, version 0.4.0.dev0" in result.output


def test_coa_help_shows_requested_options() -> None:
    result = CliRunner().invoke(cli, ["coa", "--help"])

    assert result.exit_code == 0
    assert "-i, --input-file" in result.output
    assert "-u, --username" in result.output
    assert "-w, --max-workers" in result.output
    assert "--host" in result.output
    assert "-n, --node" in result.output
    assert "-k, --insecure" in result.output
    assert "-o, --output-file" in result.output
    assert "-y, --yes" in result.output


def test_swauth_help_shows_requested_options() -> None:
    result = CliRunner().invoke(cli, ["swauth", "--help"])

    assert result.exit_code == 0
    assert "-i, --input-file" in result.output
    assert "-u, --username" in result.output
    assert "-w, --max-workers" in result.output
    assert "--verbose" not in result.output


def test_init_creates_config_files(monkeypatch, tmp_path: Path) -> None:
    config_dir = _patch_config_dir(monkeypatch, tmp_path)

    result = CliRunner().invoke(cli, ["init"])

    settings_file = config_dir / "settings.toml"
    ssh_config_file = config_dir / "ssh_config"
    assert result.exit_code == 0
    assert settings_file.exists()
    assert ssh_config_file.exists()
    settings_text = settings_file.read_text(encoding="utf-8")
    active_settings_lines = [
        line.strip()
        for line in settings_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert "[coa]" in settings_text
    assert "# Turns on extra verbose logging (NOT IMPLEMENTED YET)" in settings_text
    assert "# username = \"bob-example\"" in settings_text
    assert "# output_file = \"coa-results.json\"" in settings_text
    assert "[swauth]" in settings_text
    assert "# input_file = \"switches-and-macs.csv\"" in settings_text
    assert "username = \"bob-example\"" not in active_settings_lines
    assert "StrictHostKeyChecking no" in ssh_config_file.read_text(encoding="utf-8")
    assert str(settings_file) in result.output.replace("\n", "")
    assert str(ssh_config_file) in result.output.replace("\n", "")


def test_init_writes_missing_files_without_overwriting_existing(
    monkeypatch, tmp_path: Path
) -> None:
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    settings_file = config_dir / "settings.toml"
    settings_file.write_text("existing = true\n", encoding="utf-8")
    ssh_config_file = config_dir / "ssh_config"

    result = CliRunner().invoke(cli, ["init"])

    assert result.exit_code == 0
    assert settings_file.read_text(encoding="utf-8") == "existing = true\n"
    assert ssh_config_file.exists()
    assert "Left existing config file unchanged" in result.output
    assert "Created config file" in result.output


def test_init_force_overwrites_existing_files(monkeypatch, tmp_path: Path) -> None:
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    settings_file = config_dir / "settings.toml"
    settings_file.write_text("existing = true\n", encoding="utf-8")
    ssh_config_file = config_dir / "ssh_config"
    ssh_config_file.write_text("existing ssh config\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["init", "--force"])

    assert result.exit_code == 0
    assert "[coa]" in settings_file.read_text(encoding="utf-8")
    assert "Host *" in ssh_config_file.read_text(encoding="utf-8")


def test_init_leaves_all_existing_files_without_force(monkeypatch, tmp_path: Path) -> None:
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    settings_file = config_dir / "settings.toml"
    ssh_config_file = config_dir / "ssh_config"
    settings_file.write_text("existing = true\n", encoding="utf-8")
    ssh_config_file.write_text("existing ssh config\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["init"])

    assert result.exit_code == 0
    assert settings_file.read_text(encoding="utf-8") == "existing = true\n"
    assert ssh_config_file.read_text(encoding="utf-8") == "existing ssh config\n"
    assert "All generated config files already exist" in result.output


def test_swauth_cli_options_override_settings(monkeypatch, tmp_path: Path) -> None:
    calls = _patch_swauth_runner(monkeypatch)
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    configured_input = tmp_path / "configured-switches.csv"
    _write_swauth_csv(configured_input, [("configured-switch", "00:11:22:33:44:55")])
    cli_input = tmp_path / "cli-switches.csv"
    _write_swauth_csv(cli_input, [("10.1.1.1", "aa:bb:cc:dd:ee:ff")])
    (config_dir / "settings.toml").write_text(
        f"""
[swauth]
input_file = "{configured_input}"
username = "config-user"
max_workers = 5
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "swauth",
            "--input-file",
            str(cli_input),
            "--username",
            "cli-user",
            "--max-workers",
            "9",
        ],
        input="switch-password\n",
    )

    assert result.exit_code == 0
    assert "Validating switch SSH credentials" in result.output
    assert "10.1.1.1" in result.output
    assert calls == [
        {
            "switch_macs": {"10.1.1.1": ["aa:bb:cc:dd:ee:ff"]},
            "username": "cli-user",
            "password": "switch-password",
            "max_workers": 9,
            "ssh_config_file": config_dir / "ssh_config",
        }
    ]
    assert "10.1.1.1" in result.output
    assert "aa:bb:cc:dd:ee:ff" in result.output
    assert "mocked switch success" in " ".join(result.output.split())


def test_swauth_settings_override_defaults_when_cli_omits_values(
    monkeypatch, tmp_path: Path
) -> None:
    calls = _patch_swauth_runner(monkeypatch)
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    configured_input = tmp_path / "configured-switches.csv"
    _write_swauth_csv(configured_input, [("switch-a.example.com", "0011.2233.4455")])
    (config_dir / "settings.toml").write_text(
        f"""
[swauth]
input_file = "{configured_input}"
username = "config-user"
max_workers = 5
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["swauth"], input="switch-password\n")

    assert result.exit_code == 0
    assert calls[0]["switch_macs"] == {"switch-a.example.com": ["0011.2233.4455"]}
    assert calls[0]["username"] == "config-user"
    assert calls[0]["max_workers"] == 5


def test_swauth_uses_defaults_when_cli_and_settings_omit_optional_values(
    monkeypatch, tmp_path: Path
) -> None:
    calls = _patch_swauth_runner(monkeypatch)
    _patch_config_dir(monkeypatch, tmp_path)
    input_file = tmp_path / "switches.csv"
    _write_swauth_csv(input_file, [("10.1.1.1", "00-11-22-33-44-55")])

    result = CliRunner().invoke(
        cli,
        [
            "swauth",
            "--input-file",
            str(input_file),
            "--username",
            "cli-user",
        ],
        input="switch-password\n",
    )

    assert result.exit_code == 0
    assert calls[0]["max_workers"] == 20


def test_swauth_prompts_for_username_when_missing(monkeypatch, tmp_path: Path) -> None:
    calls = _patch_swauth_runner(monkeypatch)
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    input_file = tmp_path / "switches.csv"
    _write_swauth_csv(input_file, [("10.1.1.1", "00:11:22:33:44:55")])
    (config_dir / "settings.toml").write_text(
        f"""
[swauth]
input_file = "{input_file}"
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["swauth"], input="prompt-user\nprompt-pass\n")

    assert result.exit_code == 0
    assert "Switch username:" in result.output
    assert "Switch password for prompt-user:" in result.output
    assert calls[0]["username"] == "prompt-user"
    assert calls[0]["password"] == "prompt-pass"


def test_swauth_missing_required_resolved_values_errors(monkeypatch, tmp_path: Path) -> None:
    _patch_config_dir(monkeypatch, tmp_path)

    result = CliRunner().invoke(cli, ["swauth"])

    assert result.exit_code == 2
    assert "Missing required option(s)" in result.output
    assert "--input-file" in result.output
    assert "[swauth]" in result.output


def test_swauth_prints_csv_warnings_but_processes_valid_rows(
    monkeypatch, tmp_path: Path
) -> None:
    calls = _patch_swauth_runner(monkeypatch)
    _patch_config_dir(monkeypatch, tmp_path)
    input_file = tmp_path / "switches.csv"
    input_file.write_text(
        "\n".join(
            [
                "switch_address,mac_address",
                "10.1.1.1,00:11:22:33:44:55",
                " ,aa:bb:cc:dd:ee:ff",
                "10.1.1.2,not-a-mac",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "swauth",
            "--input-file",
            str(input_file),
            "--username",
            "cli-user",
        ],
        input="switch-password\n",
    )

    assert result.exit_code == 0
    assert calls[0]["switch_macs"] == {"10.1.1.1": ["00:11:22:33:44:55"]}
    assert "Warning: CSV row 3" in result.output
    assert "Warning: CSV row 4" in result.output


def test_swauth_preflight_failure_aborts_before_worker_submission(
    monkeypatch, tmp_path: Path
) -> None:
    calls = _patch_swauth_runner(monkeypatch)
    _patch_config_dir(monkeypatch, tmp_path)
    input_file = tmp_path / "switches.csv"
    _write_swauth_csv(input_file, [("10.1.1.1", "00:11:22:33:44:55")])

    def fail_preflight(**kwargs):
        raise SwauthCredentialValidationError(
            switch_address=kwargs["switch_address"],
            error=RuntimeError("authentication failed"),
        )

    monkeypatch.setattr(
        "isemass.cli.swauth_ops.validate_swauth_credentials",
        fail_preflight,
    )

    result = CliRunner().invoke(
        cli,
        [
            "swauth",
            "--input-file",
            str(input_file),
            "--username",
            "cli-user",
        ],
        input="switch-password\n",
    )

    assert result.exit_code != 0
    assert calls == []
    assert "Please validate user/pass combination is correct" in result.output
    assert "Validate the first switch hostname/ip in the input CSV is valid" in result.output
    assert "switch-password" not in result.output


def test_swauth_progress_advances_once_per_switch(monkeypatch, tmp_path: Path) -> None:
    progress = _patch_progress(monkeypatch)
    _patch_swauth_runner(monkeypatch)
    _patch_config_dir(monkeypatch, tmp_path)
    input_file = tmp_path / "switches.csv"
    _write_swauth_csv(
        input_file,
        [
            ("10.1.1.1", "00:11:22:33:44:55"),
            ("10.1.1.2", "aa:bb:cc:dd:ee:ff"),
        ],
    )

    result = CliRunner().invoke(
        cli,
        [
            "swauth",
            "--input-file",
            str(input_file),
            "--username",
            "cli-user",
        ],
        input="switch-password\n",
    )

    assert result.exit_code == 0
    assert progress.instances[0].tasks == [
        {"description": "Processing switch workers...", "total": 2}
    ]
    assert len(progress.instances[0].advances) == 2


def test_coa_cli_options_override_settings(monkeypatch, tmp_path: Path) -> None:
    calls = _patch_coa_runner(monkeypatch)
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    configured_input = tmp_path / "configured-macs.txt"
    configured_input.write_text("00:11:22:33:44:55\n", encoding="utf-8")
    cli_input = tmp_path / "cli-macs.txt"
    cli_input.write_text("aa:bb:cc:dd:ee:ff\n", encoding="utf-8")
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
            "--yes",
        ],
        input="api-password\n",
    )

    assert result.exit_code == 0
    assert "Validating CoA API credentials" in result.output
    assert "02:00:00:00:00:00" in result.output
    assert calls == [
        {
            "macs": ["AA:BB:CC:DD:EE:FF"],
            "host": "cli-host.example.com",
            "node": "cli-node",
            "username": "cli-user",
            "password": "api-password",
            "max_workers": 9,
            "insecure": True,
        }
    ]
    assert "AA:BB:CC:DD:EE:FF" in result.output
    assert "mocked success" in result.output


def test_coa_settings_override_defaults_when_cli_omits_values(monkeypatch, tmp_path: Path) -> None:
    calls = _patch_coa_runner(monkeypatch)
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    configured_input = tmp_path / "configured-macs.txt"
    configured_input.write_text("00:11:22:33:44:55\n", encoding="utf-8")
    (config_dir / "settings.toml").write_text(
        f"""
[coa]
input_file = "{configured_input}"
username = "config-user"
host = "config-host.example.com"
node = "config-node"
max_workers = 5
insecure = true
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["coa", "--yes"], input="api-password\n")

    assert result.exit_code == 0
    assert calls[0]["max_workers"] == 5
    assert calls[0]["insecure"] is True
    assert calls[0]["macs"] == ["00:11:22:33:44:55"]


def test_coa_uses_defaults_when_cli_and_settings_omit_optional_values(
    monkeypatch, tmp_path: Path
) -> None:
    calls = _patch_coa_runner(monkeypatch)
    _patch_config_dir(monkeypatch, tmp_path)
    input_file = tmp_path / "macs.txt"
    input_file.write_text("00:11:22:33:44:55\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "coa",
            "--input-file",
            str(input_file),
            "--username",
            "cli-user",
            "--host",
            "ise-mnt.example.com",
            "--node",
            "ise-psn01",
            "--yes",
        ],
        input="api-password\n",
    )

    assert result.exit_code == 0
    assert calls[0]["max_workers"] == 20
    assert calls[0]["insecure"] is False


def test_coa_rejects_invalid_boolean_setting(monkeypatch, tmp_path: Path) -> None:
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    input_file = tmp_path / "macs.txt"
    input_file.write_text("00:11:22:33:44:55\n", encoding="utf-8")
    (config_dir / "settings.toml").write_text(
        f"""
[coa]
input_file = "{input_file}"
username = "config-user"
host = "ise-mnt.example.com"
node = "ise-psn01"
insecure = "false"
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["coa"])

    assert result.exit_code != 0
    assert "insecure must be a boolean true or false" in result.output


def test_coa_no_macs_found_aborts_before_api_submission(monkeypatch, tmp_path: Path) -> None:
    calls = _patch_coa_runner(monkeypatch)
    _patch_config_dir(monkeypatch, tmp_path)
    input_file = tmp_path / "macs.txt"
    input_file.write_text("no macs here\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "coa",
            "--input-file",
            str(input_file),
            "--username",
            "cli-user",
            "--host",
            "ise-mnt.example.com",
            "--node",
            "ise-psn01",
            "--yes",
        ],
        input="api-password\n",
    )

    assert result.exit_code != 0
    assert "No MAC addresses found" in result.output
    assert calls == []


def test_coa_confirmation_decline_aborts_before_api_submission(monkeypatch, tmp_path: Path) -> None:
    calls = _patch_coa_runner(monkeypatch)
    _patch_config_dir(monkeypatch, tmp_path)
    input_file = tmp_path / "macs.txt"
    input_file.write_text("00:11:22:33:44:55\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "coa",
            "--input-file",
            str(input_file),
            "--username",
            "cli-user",
            "--host",
            "ise-mnt.example.com",
            "--node",
            "ise-psn01",
        ],
        input="api-password\nn\n",
    )

    assert result.exit_code != 0
    assert "Operation not approved" in result.output
    assert calls == []


def test_coa_missing_required_resolved_values_errors(monkeypatch, tmp_path: Path) -> None:
    _patch_config_dir(monkeypatch, tmp_path)

    result = CliRunner().invoke(cli, ["coa"])

    assert result.exit_code == 2
    assert "Missing required option(s)" in result.output
    assert "--input-file" in result.output
    assert "--host" in result.output
    assert "--node" in result.output


def test_coa_prompts_for_username_when_missing(monkeypatch, tmp_path: Path) -> None:
    calls = _patch_coa_runner(monkeypatch)
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    input_file = tmp_path / "macs.txt"
    input_file.write_text("00:11:22:33:44:55\n", encoding="utf-8")
    (config_dir / "settings.toml").write_text(
        f"""
[coa]
input_file = "{input_file}"
host = "ise-mnt.example.com"
node = "ise-psn01"
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["coa", "--yes"], input="prompt-user\nprompt-pass\n")

    assert result.exit_code == 0
    assert "API username:" in result.output
    assert "API password for prompt-user:" in result.output
    assert calls[0]["username"] == "prompt-user"
    assert calls[0]["password"] == "prompt-pass"


def test_coa_preflight_failure_aborts_before_api_submission(monkeypatch, tmp_path: Path) -> None:
    calls = _patch_coa_runner(monkeypatch)
    _patch_config_dir(monkeypatch, tmp_path)
    input_file = tmp_path / "macs.txt"
    input_file.write_text("00:11:22:33:44:55\n", encoding="utf-8")
    failed_result = CoaResult(
        mac="02:00:00:00:00:00",
        success=False,
        seconds=0.12,
        result_message="Invalid API credentials",
    )

    def fail_preflight(**kwargs):
        raise CoaCredentialValidationError(
            host=kwargs["host"],
            node=kwargs["node"],
            result=failed_result,
        )

    monkeypatch.setattr("isemass.cli.coa_ops.validate_coa_credentials", fail_preflight)

    result = CliRunner().invoke(
        cli,
        [
            "coa",
            "--input-file",
            str(input_file),
            "--username",
            "cli-user",
            "--host",
            "ise-mnt.example.com",
            "--node",
            "ise-psn01",
            "--yes",
        ],
        input="api-password\n",
    )

    assert result.exit_code != 0
    assert calls == []
    assert "Please validate user/pass combination is correct" in result.output
    assert "Invalid API credentials" in result.output
    assert "api-password" not in result.output


def test_coa_progress_advances_once_per_mac(monkeypatch, tmp_path: Path) -> None:
    progress = _patch_progress(monkeypatch)
    _patch_coa_runner(monkeypatch)
    _patch_config_dir(monkeypatch, tmp_path)
    input_file = tmp_path / "macs.txt"
    input_file.write_text("00:11:22:33:44:55\naa:bb:cc:dd:ee:ff\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "coa",
            "--input-file",
            str(input_file),
            "--username",
            "cli-user",
            "--host",
            "ise-mnt.example.com",
            "--node",
            "ise-psn01",
            "--yes",
        ],
        input="api-password\n",
    )

    assert result.exit_code == 0
    assert progress.instances[0].tasks == [{"description": "Performing CoA requests...", "total": 2}]
    assert len(progress.instances[0].advances) == 2


def test_coa_cli_output_file_overrides_settings_output_file(monkeypatch, tmp_path: Path) -> None:
    _patch_coa_runner_with_results(
        monkeypatch,
        [_detailed_result("AA:BB:CC:DD:EE:FF")],
    )
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    input_file = tmp_path / "macs.txt"
    input_file.write_text("aa:bb:cc:dd:ee:ff\n", encoding="utf-8")
    settings_output = tmp_path / "settings-output.json"
    cli_output = tmp_path / "cli-output.json"
    (config_dir / "settings.toml").write_text(
        f"""
[coa]
input_file = "{input_file}"
username = "config-user"
host = "ise-mnt.example.com"
node = "ise-psn01"
output_file = "{settings_output}"
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["coa", "--output-file", str(cli_output), "--yes"],
        input="api-password\n",
    )

    assert result.exit_code == 0
    assert cli_output.exists()
    assert not settings_output.exists()


def test_coa_uses_config_output_file_when_cli_omits_it(monkeypatch, tmp_path: Path) -> None:
    _patch_coa_runner_with_results(
        monkeypatch,
        [_detailed_result("AA:BB:CC:DD:EE:FF")],
    )
    config_dir = _patch_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    input_file = tmp_path / "macs.txt"
    input_file.write_text("aa:bb:cc:dd:ee:ff\n", encoding="utf-8")
    settings_output = tmp_path / "settings-output.json"
    (config_dir / "settings.toml").write_text(
        f"""
[coa]
input_file = "{input_file}"
username = "config-user"
host = "ise-mnt.example.com"
node = "ise-psn01"
output_file = "{settings_output}"
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["coa", "--yes"], input="api-password\n")

    assert result.exit_code == 0
    assert settings_output.exists()


def test_coa_does_not_write_output_file_when_unset(monkeypatch, tmp_path: Path) -> None:
    _patch_coa_runner_with_results(
        monkeypatch,
        [_detailed_result("AA:BB:CC:DD:EE:FF")],
    )
    _patch_config_dir(monkeypatch, tmp_path)
    input_file = tmp_path / "macs.txt"
    input_file.write_text("aa:bb:cc:dd:ee:ff\n", encoding="utf-8")
    unused_output = tmp_path / "unused-output.json"

    result = CliRunner().invoke(
        cli,
        [
            "coa",
            "--input-file",
            str(input_file),
            "--username",
            "cli-user",
            "--host",
            "ise-mnt.example.com",
            "--node",
            "ise-psn01",
            "--yes",
        ],
        input="api-password\n",
    )

    assert result.exit_code == 0
    assert not unused_output.exists()


def test_coa_output_file_creates_parents_and_overwrites_existing_file(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_coa_runner_with_results(
        monkeypatch,
        [_detailed_result("AA:BB:CC:DD:EE:FF")],
    )
    _patch_config_dir(monkeypatch, tmp_path)
    input_file = tmp_path / "macs.txt"
    input_file.write_text("aa:bb:cc:dd:ee:ff\n", encoding="utf-8")
    output_file = tmp_path / "reports" / "coa-results.json"
    output_file.parent.mkdir()
    output_file.write_text("old contents\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "coa",
            "--input-file",
            str(input_file),
            "--username",
            "cli-user",
            "--host",
            "ise-mnt.example.com",
            "--node",
            "ise-psn01",
            "--output-file",
            str(output_file),
            "--yes",
        ],
        input="api-password\n",
    )

    assert result.exit_code == 0
    assert output_file.read_text(encoding="utf-8") != "old contents\n"
    assert json.loads(output_file.read_text(encoding="utf-8"))[0]["mac_address"] == (
        "AA:BB:CC:DD:EE:FF"
    )


def test_coa_output_json_is_detailed_ordered_and_excludes_auth(
    monkeypatch, tmp_path: Path
) -> None:
    input_order = ["AA:BB:CC:DD:EE:FF", "00:11:22:33:44:55"]
    completion_order_results = [
        _detailed_result(
            "00:11:22:33:44:55",
            success=False,
            seconds=0.34,
            result_message="Undefined failure",
            response_status_code=None,
            response_text=None,
            ise_result_value=None,
            error_type="Timeout",
            error_message="timed out",
        ),
        _detailed_result("AA:BB:CC:DD:EE:FF"),
    ]
    _patch_coa_runner_with_results(monkeypatch, completion_order_results)
    _patch_config_dir(monkeypatch, tmp_path)
    input_file = tmp_path / "macs.txt"
    input_file.write_text("\n".join(input_order) + "\n", encoding="utf-8")
    output_file = tmp_path / "reports" / "coa-results.json"

    result = CliRunner().invoke(
        cli,
        [
            "coa",
            "--input-file",
            str(input_file),
            "--username",
            "cli-user",
            "--host",
            "ise-mnt.example.com",
            "--node",
            "ise-psn01",
            "--insecure",
            "--output-file",
            str(output_file),
            "--yes",
        ],
        input="api-password\n",
    )

    assert result.exit_code == 0
    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert [entry["mac_address"] for entry in data] == input_order
    assert data[0] == {
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "success": True,
        "result_message": "CoA Succeeded",
        "seconds": 0.12,
        "request_method": "GET",
        "request_url": (
            "https://ise-mnt.example.com/admin/API/mnt/CoA/Reauth/"
            "ise-psn01/AA:BB:CC:DD:EE:FF/0"
        ),
        "verify_tls": False,
        "response_status_code": 200,
        "response_headers": {"Content-Type": "application/xml"},
        "response_text": "<remoteCoA><results>true</results></remoteCoA>",
        "ise_result_value": "true",
        "error_type": None,
        "error_message": None,
    }
    assert data[1]["success"] is False
    assert data[1]["result_message"] == "Undefined failure"
    assert data[1]["error_type"] == "Timeout"
    output_text = output_file.read_text(encoding="utf-8")
    assert "api-password" not in output_text
    output_keys = {key.casefold() for entry in data for key in entry}
    assert "status" not in output_keys
    assert "detail" not in output_keys
    assert "auth" not in output_keys
    assert "password" not in output_keys
    assert "authorization" not in output_keys
