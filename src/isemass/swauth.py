"""Switch SSH authentication session helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

from isemass.coa import RE_MAC_PATTERN

DEVICE_TYPE = "cisco_xe"
NO_SESSION_TEXT = "No sessions match supplied criteria"
SHOW_COMMAND_TEMPLATE = "show authentication sessions mac {mac} detail"
CLEAR_COMMAND_TEMPLATE = "clear authentication sessions mac {mac}"
REQUIRED_COLUMNS = ("switch_address", "mac_address")

ConnectHandlerFunc = Callable[..., Any]


class SwauthCsvError(Exception):
    """Raised when the swauth CSV cannot produce runnable input."""


@dataclass(frozen=True)
class SwauthInputWarning:
    """Warning for a skipped CSV row."""

    row_number: int
    message: str


@dataclass(frozen=True)
class SwauthInputData:
    """Validated switch-to-MAC input data."""

    switch_macs: dict[str, list[str]]
    warnings: list[SwauthInputWarning]

    @property
    def switch_count(self) -> int:
        """Return the number of unique switches."""
        return len(self.switch_macs)

    @property
    def mac_count(self) -> int:
        """Return the total number of MAC operations."""
        return sum(len(macs) for macs in self.switch_macs.values())


@dataclass(frozen=True)
class SwauthResult:
    """Result for one switch/MAC reauthentication attempt."""

    switch_address: str
    mac: str
    success: bool
    result_message: str
    seconds: float
    show_command: str
    clear_command: str | None = None
    error_type: str | None = None
    error_message: str | None = None


def load_switch_mac_groups(path: Path) -> SwauthInputData:
    """Read and validate a swauth CSV file."""
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as exc:
        raise SwauthCsvError(f"Unable to read input CSV file {path}: {exc}") from exc

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise SwauthCsvError(f"Input CSV is missing required column(s): {missing}")

    switch_macs: dict[str, list[str]] = {}
    warnings: list[SwauthInputWarning] = []
    seen_pairs: set[tuple[str, str]] = set()

    for index, row in df.iterrows():
        row_number = int(index) + 2
        switch_address = str(row["switch_address"]).strip()
        mac = str(row["mac_address"]).strip()

        if not switch_address:
            warnings.append(
                SwauthInputWarning(
                    row_number=row_number,
                    message="switch_address is blank; row skipped.",
                )
            )
            continue

        if not RE_MAC_PATTERN.fullmatch(mac):
            warnings.append(
                SwauthInputWarning(
                    row_number=row_number,
                    message="mac_address must contain exactly one supported MAC address; row skipped.",
                )
            )
            continue

        pair = (switch_address, mac)
        if pair in seen_pairs:
            continue

        seen_pairs.add(pair)
        switch_macs.setdefault(switch_address, []).append(mac)

    if not switch_macs:
        raise SwauthCsvError(f"No valid switch/MAC rows found in {path}.")

    return SwauthInputData(switch_macs=switch_macs, warnings=warnings)


def process_switch(
    *,
    switch_address: str,
    macs: Sequence[str],
    username: str,
    password: str,
    ssh_config_file: Path,
    connect_handler: ConnectHandlerFunc | None = None,
) -> list[SwauthResult]:
    """Process all MAC addresses assigned to one switch."""
    resolved_connect_handler = connect_handler or _default_connect_handler
    mac_list = list(macs)
    connection_start = perf_counter()

    try:
        connection = resolved_connect_handler(
            device_type=DEVICE_TYPE,
            host=switch_address,
            username=username,
            password=password,
            ssh_config_file=str(ssh_config_file),
        )
    except Exception as exc:
        seconds = _elapsed_seconds(connection_start)
        return [
            _failed_result(
                switch_address=switch_address,
                mac=mac,
                result_message="SSH to switch failed",
                seconds=seconds,
                error=exc,
            )
            for mac in mac_list
        ]

    try:
        return [_process_mac(connection, switch_address=switch_address, mac=mac) for mac in mac_list]
    finally:
        disconnect = getattr(connection, "disconnect", None)
        if callable(disconnect):
            disconnect()


def run_swauth_requests(
    *,
    switch_macs: Mapping[str, Sequence[str]],
    username: str,
    password: str,
    max_workers: int,
    ssh_config_file: Path,
    connect_handler: ConnectHandlerFunc | None = None,
) -> Iterable[SwauthResult]:
    """Run switch reauthentication tasks concurrently and yield results as switches finish."""
    switch_items = [(switch_address, list(macs)) for switch_address, macs in switch_macs.items()]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_switch = {
            executor.submit(
                process_switch,
                switch_address=switch_address,
                macs=macs,
                username=username,
                password=password,
                ssh_config_file=ssh_config_file,
                connect_handler=connect_handler,
            ): (switch_address, macs)
            for switch_address, macs in switch_items
        }

        for future in as_completed(future_to_switch):
            switch_address, macs = future_to_switch[future]
            try:
                yield from future.result()
            except Exception as exc:
                for mac in macs:
                    yield _failed_result(
                        switch_address=switch_address,
                        mac=mac,
                        result_message="Undefined failure",
                        seconds=0.0,
                        error=exc,
                    )


def _process_mac(connection: Any, *, switch_address: str, mac: str) -> SwauthResult:
    show_command = SHOW_COMMAND_TEMPLATE.format(mac=mac)
    clear_command = CLEAR_COMMAND_TEMPLATE.format(mac=mac)
    start = perf_counter()

    try:
        show_output = str(connection.send_command(show_command))
        if NO_SESSION_TEXT in show_output:
            return SwauthResult(
                switch_address=switch_address,
                mac=mac,
                success=False,
                result_message="No Session Found",
                seconds=_elapsed_seconds(start),
                show_command=show_command,
            )

        connection.send_command(clear_command)
        return SwauthResult(
            switch_address=switch_address,
            mac=mac,
            success=True,
            result_message="Session was found and cleared",
            seconds=_elapsed_seconds(start),
            show_command=show_command,
            clear_command=clear_command,
        )
    except Exception as exc:
        return _failed_result(
            switch_address=switch_address,
            mac=mac,
            result_message="SSH command failed",
            seconds=_elapsed_seconds(start),
            error=exc,
        )


def _failed_result(
    *,
    switch_address: str,
    mac: str,
    result_message: str,
    seconds: float,
    error: Exception,
) -> SwauthResult:
    return SwauthResult(
        switch_address=switch_address,
        mac=mac,
        success=False,
        result_message=result_message,
        seconds=seconds,
        show_command=SHOW_COMMAND_TEMPLATE.format(mac=mac),
        error_type=type(error).__name__,
        error_message=str(error),
    )


def _default_connect_handler(**kwargs: Any) -> Any:
    from netmiko import ConnectHandler

    return ConnectHandler(**kwargs)


def _elapsed_seconds(start: float) -> float:
    return round(perf_counter() - start, 2)
