"""Click command line interface for isemass."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from isemass import __version__
from isemass.config import SettingsError, get_settings_path, load_settings, write_default_settings
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


def _coerce_positive_int(value: Any, *, field_name: str) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise click.ClickException(f"{field_name} must be a positive integer.") from exc

    if resolved < 1:
        raise click.ClickException(f"{field_name} must be a positive integer.")

    return resolved


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="isemass")
def cli() -> None:
    """Mass Cisco ISE related operations."""


@cli.command()
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite an existing settings.toml file.",
)
def init(force: bool) -> None:
    """Create the optional settings.toml file."""
    path, wrote_file = write_default_settings(force=force)

    if not wrote_file:
        raise click.ClickException(f"Settings file already exists: {path}. Use --force to overwrite.")

    console.print(f"[green]Created settings file:[/green] {path}")


@cli.command()
@click.option(
    "-i",
    "--input-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Input text file containing MAC addresses.",
)
@click.option(
    "-u",
    "--username",
    help="API username. Prompts if omitted and not configured.",
)
@click.option(
    "-w",
    "--max-workers",
    type=int,
    help="Max workers for multitasking at once.",
)
@click.option(
    "--host",
    help="FQDN or IP for the API request, typically the MnT node.",
)
@click.option(
    "-n",
    "--node",
    help="Short ISE node name that processes the CoA request.",
)
@click.option(
    "-k",
    "--insecure",
    is_flag=True,
    default=None,
    help="Skip HTTPS certificate validation.",
)
def coa(
    input_file: Path | None,
    username: str | None,
    max_workers: int | None,
    host: str | None,
    node: str | None,
    insecure: bool | None,
) -> None:
    """ISE Mass CoA through API."""
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
    resolved_insecure = bool(_resolve_option(insecure, coa_settings.get("insecure")))

    console.print("[yellow]CoA operation is not implemented yet.[/yellow]")
    console.print(f"Input file: {resolved_input_file}")
    console.print(f"Username: {resolved_username}")
    console.print(f"Max workers: {resolved_max_workers}")
    console.print(f"Host: {resolved_host}")
    console.print(f"Node: {resolved_node}")
    console.print(f"Insecure: {resolved_insecure}")


@cli.command()
def swauth() -> None:
    """Mass session reauthentication through switch SSH."""
    settings = _load_settings_for_cli()
    swauth_settings = _section(settings, "swauth")
    verbose = bool(swauth_settings.get("verbose", False))

    console.print("[yellow]Switch reauthentication is not implemented yet.[/yellow]")
    console.print(f"Verbose: {verbose}")
    console.print(f"Settings path: {get_settings_path()}")

