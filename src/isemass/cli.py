"""Click command line interface for isemass."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
from rich.table import Table
from rich.panel import Panel

from isemass import __version__
from isemass import coa as coa_ops
from isemass import swauth as swauth_ops
from isemass.config import (
    SettingsError,
    get_ssh_config_path,
    load_settings,
    write_default_config_files,
)
from isemass.console import console


def _load_settings_for_cli() -> dict[str, dict[str, Any]]:
    try:
        return load_settings()
    except SettingsError as exc:
        raise click.ClickException(str(exc)) from exc


def _section(settings: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    values = settings.get(name, {})
    if not isinstance(values, dict):
        raise click.ClickException(f"Invalid settings: [{name}] must be a table.")
    return values


def _resolve_option(cli_value: Any, config_value: Any) -> Any:
    return cli_value if cli_value is not None else config_value


def _missing_required_options(options: dict[str, Any]) -> list[str]:
    return [option_name for option_name, value in options.items() if value in (None, "")]


def _coerce_input_file(value: Any) -> Path:
    path = Path(value).expanduser()
    if not path.is_file():
        raise click.ClickException(f"Input file does not exist: {path}")
    return path


def _coerce_optional_output_file(value: Any) -> Path | None:
    if value in (None, ""):
        return None

    path = Path(value).expanduser()
    if path.exists() and path.is_dir():
        raise click.ClickException(f"Output file cannot be a directory: {path}")
    return path


def _coerce_positive_int(value: Any, *, field_name: str) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise click.ClickException(f"{field_name} must be a positive integer.") from exc

    if resolved < 1:
        raise click.ClickException(f"{field_name} must be a positive integer.")

    return resolved


def _coerce_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value

    raise click.ClickException(f"{field_name} must be a boolean true or false.")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="isemass")
def cli() -> None:
    """Mass Cisco ISE related operations."""


@cli.command()
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing generated config files.",
)
def init(force: bool) -> None:
    """Create optional generated config files."""
    results = write_default_config_files(force=force)

    wrote_any = False
    for path, wrote_file in results:
        if wrote_file:
            wrote_any = True
            action = "Wrote" if force else "Created"
            console.print(f"[green]{action} config file:[/green] '{path}'")
        else:
            console.print(f"[yellow]Left existing config file unchanged:[/yellow] '{path}'")

    if not wrote_any:
        console.print("[yellow]All generated config files already exist. Use --force to overwrite.[/yellow]")


@cli.command()
@click.option(
    "-i",
    "--input-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Input text file containing MAC addresses. Can be any format, even unclean, as MAC address will be extracted via RegEx patterns",
)
@click.option(
    "-u",
    "--username",
    help="API username. Prompts during runtime if omitted.",
)
@click.option(
    "-w",
    "--max-workers",
    type=int,
    help="Maximum number of concurrent workers for CoA tasks.",
)
@click.option(
    "--host",
    help="API host to connect to, typically the MnT node FQDN or IP.",
)
@click.option(
    "-n",
    "--node",
    help="Short ISE node name that processes the CoA request, typically a PSN.",
)
@click.option(
    "-k",
    "--insecure",
    is_flag=True,
    default=None,
    help="Skip HTTPS certificate validation when set",
)
@click.option(
    "-o",
    "--output-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Optional output JSON file with detailed results.",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Skip confirmation before submitting CoA requests.",
)
def coa(
    input_file: Path | None,
    username: str | None,
    max_workers: int | None,
    host: str | None,
    node: str | None,
    insecure: bool | None,
    output_file: Path | None,
    yes: bool,
) -> None:
    """ISE Mass CoA through API."""

    console.print()
    settings = _load_settings_for_cli()
    coa_settings = _section(settings, "coa")

    required_values = {
        "--input-file": _resolve_option(input_file, coa_settings.get("input_file")),
        "--host": _resolve_option(host, coa_settings.get("host")),
        "--node": _resolve_option(node, coa_settings.get("node")),
    }
    missing = _missing_required_options(required_values)
    if missing:
        missing_options = ", ".join(missing)
        raise click.UsageError(
            f"Missing required option(s): {missing_options}. "
            "Provide them on the CLI or in [coa]."
        )

    resolved_input_file = _coerce_input_file(required_values["--input-file"])
    resolved_host = str(required_values["--host"])
    resolved_node = str(required_values["--node"])
    resolved_username = _resolve_option(username, coa_settings.get("username"))
    if not resolved_username:
        resolved_username = click.prompt("API username", type=str)

    resolved_max_workers = _coerce_positive_int(
        _resolve_option(max_workers, coa_settings.get("max_workers")),
        field_name="max_workers",
    )
    resolved_insecure = _coerce_bool(
        _resolve_option(insecure, coa_settings.get("insecure")),
        field_name="insecure",
    )
    resolved_output_file = _coerce_optional_output_file(
        _resolve_option(output_file, coa_settings.get("output_file"))
    )

    password = click.prompt(f"API password for {resolved_username}", hide_input=True, type=str)
    console.print()

    macs = coa_ops.extract_macs_from_file(resolved_input_file)
    if not macs:
        raise click.ClickException(f"No MAC addresses found in {resolved_input_file}.")

    _print_mac_preview(macs)
    if not yes and not click.confirm("Continue with CoA operation?", default=False):
        raise click.ClickException("Operation not approved. Aborting.")
    
    console.print()
    console.print(Panel.fit(f"Starting CoA requests for {len(macs)} MAC address(es)..."))

    results: list[coa_ops.CoaResult] = []
    for result in coa_ops.run_coa_requests(
        macs=macs,
        host=resolved_host,
        node=resolved_node,
        username=str(resolved_username),
        password=password,
        max_workers=resolved_max_workers,
        insecure=resolved_insecure,
    ):
        results.append(result)
        _print_coa_result(result)
    console.print()

    if resolved_output_file is not None:
        try:
            coa_ops.write_results_json(resolved_output_file, results, mac_order=macs)
        except OSError as exc:
            raise click.ClickException(
                f"Unable to write output JSON file {resolved_output_file}: {exc}"
            ) from exc
        console.print(f"Wrote CoA results JSON: {resolved_output_file}")


@cli.command()
@click.option(
    "-i",
    "--input-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Input CSV file that has columns/data of switch_address and mac_address.",
)
@click.option(
    "-u",
    "--username",
    help="Username for Cisco switches. Prompts during runtime if omitted.",
)
@click.option(
    "-w",
    "--max-workers",
    type=int,
    help="Maximum number of concurrent switch SSH workers.",
)
def swauth(
    input_file: Path | None,
    username: str | None,
    max_workers: int | None,
) -> None:
    """Mass session reauthentication through switch SSH."""
    console.print()
    settings = _load_settings_for_cli()
    swauth_settings = _section(settings, "swauth")
    _coerce_bool(swauth_settings.get("verbose", False), field_name="verbose")

    required_values = {
        "--input-file": _resolve_option(input_file, swauth_settings.get("input_file")),
    }
    missing = _missing_required_options(required_values)
    if missing:
        missing_options = ", ".join(missing)
        raise click.UsageError(
            f"Missing required option(s): {missing_options}. "
            "Provide them on the CLI or in [swauth]."
        )

    resolved_input_file = _coerce_input_file(required_values["--input-file"])
    resolved_username = _resolve_option(username, swauth_settings.get("username"))
    if not resolved_username:
        resolved_username = click.prompt("Switch username", type=str)

    resolved_max_workers = _coerce_positive_int(
        _resolve_option(max_workers, swauth_settings.get("max_workers")),
        field_name="max_workers",
    )

    password = click.prompt(f"Switch password for {resolved_username}", hide_input=True, type=str)
    console.print()

    try:
        input_data = swauth_ops.load_switch_mac_groups(resolved_input_file)
    except swauth_ops.SwauthCsvError as exc:
        raise click.ClickException(str(exc)) from exc

    _print_swauth_warnings(input_data.warnings)
    console.print()
    console.print(
        Panel.fit(
            (
                f"Starting switch reauthentication for {input_data.mac_count} MAC address(es) "
                f"across {input_data.switch_count} switch(es)..."
            )
        )
    )

    for result in swauth_ops.run_swauth_requests(
        switch_macs=input_data.switch_macs,
        username=str(resolved_username),
        password=password,
        max_workers=resolved_max_workers,
        ssh_config_file=get_ssh_config_path(),
    ):
        _print_swauth_result(result)
    console.print()


def _print_mac_preview(macs: list[str]) -> None:
    """
    Print a compact validation preview of unique MAC addresses.

    Shows all MACs for small lists. For large lists, shows only the first 20
    and last 20, plus a count of how many entries were hidden.
    """
    preview_limit = 20
    total = len(macs)

    table = Table(title=f"Unique MAC addresses ({total})")
    table.add_column("#", justify="right")
    table.add_column("MAC address", style="green")

    if total <= preview_limit * 2:
        preview_rows = list(enumerate(macs, start=1))
        hidden_count = 0
    else:
        first_rows = list(enumerate(macs[:preview_limit], start=1))
        last_start_index = total - preview_limit + 1
        last_rows = list(enumerate(macs[-preview_limit:], start=last_start_index))

        preview_rows = first_rows + [(None, "...")] + last_rows
        hidden_count = total - (preview_limit * 2)

    for index, mac in preview_rows:
        if index is None:
            table.add_row("...", "[dim]...[/dim]")
        else:
            table.add_row(str(index), mac)

    console.print(table)

    if hidden_count:
        console.print(f"[dim]{hidden_count:,} MAC addresses not shown[/dim]")

    console.print()


def _print_coa_result(result: coa_ops.CoaResult) -> None:

    success_icon = "✅" if result.success else "❌"

    console.print(
        (
            f"[green]{result.mac:<17}[/green] | "
            f"[blue]{result.seconds:>6.2f}s[/blue] | "
            f"{success_icon:^3} | "
            f"{result.result_message}"
        ),
        highlight=False,
    )


def _print_swauth_warnings(warnings: list[swauth_ops.SwauthInputWarning]) -> None:
    for warning in warnings:
        console.print(
            f"[yellow]Warning:[/yellow] CSV row {warning.row_number}: {warning.message}",
            highlight=False,
        )


def _print_swauth_result(result: swauth_ops.SwauthResult) -> None:
    status = "OK" if result.success else "FAIL"

    console.print(
        (
            f"[cyan]{result.switch_address:<20}[/cyan] | "
            f"[green]{result.mac:<17}[/green] | "
            f"[blue]{result.seconds:>6.2f}s[/blue] | "
            f"{status:^5} | "
            f"{result.result_message}"
        ),
        highlight=False,
    )
