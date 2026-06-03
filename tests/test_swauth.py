from __future__ import annotations

from pathlib import Path

import pytest

from isemass.swauth import (
    CLEAR_COMMAND_TEMPLATE,
    DEVICE_TYPE,
    NO_SESSION_TEXT,
    SHOW_COMMAND_TEMPLATE,
    SwauthCsvError,
    load_switch_mac_groups,
    process_switch,
    run_swauth_requests,
)


class FakeConnection:
    def __init__(
        self,
        *,
        outputs: dict[str, str] | None = None,
        failures: dict[str, Exception] | None = None,
        default_show_output: str = "session found",
    ) -> None:
        self.outputs = outputs or {}
        self.failures = failures or {}
        self.default_show_output = default_show_output
        self.commands: list[str] = []
        self.disconnected = False

    def send_command(self, command: str) -> str:
        self.commands.append(command)
        failure = self.failures.get(command)
        if failure is not None:
            raise failure
        if command in self.outputs:
            return self.outputs[command]
        if command.startswith("show authentication sessions"):
            return self.default_show_output
        return ""

    def disconnect(self) -> None:
        self.disconnected = True


def _write_csv(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_switch_mac_groups_validates_groups_and_skips_bad_rows(tmp_path: Path) -> None:
    input_file = tmp_path / "switches.csv"
    _write_csv(
        input_file,
        [
            "switch_address,mac_address,unused",
            "10.1.1.1,aaaa.bbbb.cccc,x",
            "10.1.1.1,aa:bb:cc:dd:ee:ff,x",
            " ,00:11:22:33:44:55,x",
            "10.2.2.2,not-a-mac,x",
            "10.1.1.1,aaaa.bbbb.cccc,x",
            "switch.example.com,AA-BB-CC-DD-EE-FF,x",
        ],
    )

    input_data = load_switch_mac_groups(input_file)

    assert input_data.switch_macs == {
        "10.1.1.1": ["aaaa.bbbb.cccc", "aa:bb:cc:dd:ee:ff"],
        "switch.example.com": ["AA-BB-CC-DD-EE-FF"],
    }
    assert input_data.switch_count == 2
    assert input_data.mac_count == 3
    assert [warning.row_number for warning in input_data.warnings] == [4, 5]
    assert "switch_address is blank" in input_data.warnings[0].message
    assert "mac_address must contain exactly one" in input_data.warnings[1].message


def test_load_switch_mac_groups_requires_columns(tmp_path: Path) -> None:
    input_file = tmp_path / "switches.csv"
    _write_csv(input_file, ["switch_address", "10.1.1.1"])

    with pytest.raises(SwauthCsvError, match="mac_address"):
        load_switch_mac_groups(input_file)


def test_load_switch_mac_groups_requires_single_full_mac_cell(tmp_path: Path) -> None:
    input_file = tmp_path / "switches.csv"
    _write_csv(
        input_file,
        [
            "switch_address,mac_address",
            "10.1.1.1,aa:bb:cc:dd:ee:ff extra",
        ],
    )

    with pytest.raises(SwauthCsvError, match="No valid switch/MAC rows"):
        load_switch_mac_groups(input_file)


def test_process_switch_no_session_does_not_clear(tmp_path: Path) -> None:
    mac = "aa:bb:cc:dd:ee:ff"
    show_command = SHOW_COMMAND_TEMPLATE.format(mac=mac)
    connection = FakeConnection(outputs={show_command: NO_SESSION_TEXT})

    results = process_switch(
        switch_address="10.1.1.1",
        macs=[mac],
        username="switch-user",
        password="switch-pass",
        ssh_config_file=tmp_path / "ssh_config",
        connect_handler=lambda **kwargs: connection,
    )

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].result_message == "No Session Found"
    assert connection.commands == [show_command]
    assert connection.disconnected is True


def test_process_switch_found_session_clears(tmp_path: Path) -> None:
    mac = "aaaa.bbbb.cccc"
    show_command = SHOW_COMMAND_TEMPLATE.format(mac=mac)
    clear_command = CLEAR_COMMAND_TEMPLATE.format(mac=mac)
    connection = FakeConnection(outputs={show_command: "Authorized session details"})

    results = process_switch(
        switch_address="switch-a.example.com",
        macs=[mac],
        username="switch-user",
        password="switch-pass",
        ssh_config_file=tmp_path / "ssh_config",
        connect_handler=lambda **kwargs: connection,
    )

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].result_message == "Session was found and cleared"
    assert results[0].clear_command == clear_command
    assert connection.commands == [show_command, clear_command]
    assert connection.disconnected is True


def test_process_switch_connection_failure_returns_result_per_mac(tmp_path: Path) -> None:
    def fail_connect(**kwargs):
        raise RuntimeError("authentication failed")

    results = process_switch(
        switch_address="10.1.1.1",
        macs=["aa:bb:cc:dd:ee:ff", "0011.2233.4455"],
        username="switch-user",
        password="switch-pass",
        ssh_config_file=tmp_path / "ssh_config",
        connect_handler=fail_connect,
    )

    assert len(results) == 2
    assert all(result.success is False for result in results)
    assert all(result.result_message == "SSH to switch failed" for result in results)
    assert {result.mac for result in results} == {"aa:bb:cc:dd:ee:ff", "0011.2233.4455"}
    assert all(result.error_type == "RuntimeError" for result in results)


def test_process_switch_command_failure_continues_with_remaining_macs(tmp_path: Path) -> None:
    failing_mac = "aa:bb:cc:dd:ee:ff"
    succeeding_mac = "00:11:22:33:44:55"
    failing_show_command = SHOW_COMMAND_TEMPLATE.format(mac=failing_mac)
    succeeding_show_command = SHOW_COMMAND_TEMPLATE.format(mac=succeeding_mac)
    succeeding_clear_command = CLEAR_COMMAND_TEMPLATE.format(mac=succeeding_mac)
    connection = FakeConnection(
        outputs={succeeding_show_command: "Authorized session details"},
        failures={failing_show_command: RuntimeError("show failed")},
    )

    results = process_switch(
        switch_address="10.1.1.1",
        macs=[failing_mac, succeeding_mac],
        username="switch-user",
        password="switch-pass",
        ssh_config_file=tmp_path / "ssh_config",
        connect_handler=lambda **kwargs: connection,
    )

    assert [result.success for result in results] == [False, True]
    assert results[0].result_message == "SSH command failed"
    assert results[0].error_type == "RuntimeError"
    assert results[1].result_message == "Session was found and cleared"
    assert connection.commands == [
        failing_show_command,
        succeeding_show_command,
        succeeding_clear_command,
    ]
    assert connection.disconnected is True


def test_run_swauth_requests_uses_one_connection_per_switch(tmp_path: Path) -> None:
    calls = []

    def fake_connect(**kwargs):
        calls.append(kwargs)
        return FakeConnection(default_show_output=NO_SESSION_TEXT)

    results = list(
        run_swauth_requests(
            switch_macs={
                "10.1.1.1": ["aa:bb:cc:dd:ee:ff"],
                "switch-b.example.com": ["0011.2233.4455"],
            },
            username="switch-user",
            password="switch-pass",
            max_workers=2,
            ssh_config_file=tmp_path / "ssh_config",
            connect_handler=fake_connect,
        )
    )

    assert len(results) == 2
    assert {result.switch_address for result in results} == {
        "10.1.1.1",
        "switch-b.example.com",
    }
    assert len(calls) == 2
    assert {call["host"] for call in calls} == {"10.1.1.1", "switch-b.example.com"}
    assert all(call["device_type"] == DEVICE_TYPE for call in calls)
    assert all(call["username"] == "switch-user" for call in calls)
    assert all(call["password"] == "switch-pass" for call in calls)
    assert all(call["ssh_config_file"] == str(tmp_path / "ssh_config") for call in calls)
