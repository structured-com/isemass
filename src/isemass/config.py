"""Optional settings.toml support for isemass."""

from __future__ import annotations

import copy
import tomllib
from importlib.resources import files
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

from isemass.defaults import DEFAULT_SETTINGS

APP_NAME = "isemass"
SETTINGS_FILENAME = "settings.toml"
SSH_CONFIG_FILENAME = "ssh_config"
TEMPLATE_PACKAGE = "isemass.templates"
TEMPLATE_FILENAMES = (SETTINGS_FILENAME, SSH_CONFIG_FILENAME)


class SettingsError(Exception):
    """Raised when settings.toml cannot be loaded safely."""


def get_config_dir() -> Path:
    """Return the platform-specific user config directory."""
    return Path(user_config_dir(APP_NAME))


def get_settings_path() -> Path:
    """Return the platform-specific settings.toml path."""
    return get_config_dir() / SETTINGS_FILENAME


def get_ssh_config_path() -> Path:
    """Return the platform-specific ssh_config path."""
    return get_config_dir() / SSH_CONFIG_FILENAME


def default_settings() -> dict[str, dict[str, Any]]:
    """Return a copy of the built-in settings defaults."""
    return copy.deepcopy(DEFAULT_SETTINGS)


def load_settings() -> dict[str, dict[str, Any]]:
    """Load settings.toml and merge it over built-in defaults."""
    path = get_settings_path()
    settings = default_settings()

    if not path.exists():
        return settings

    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"Invalid TOML in {path}: {exc}") from exc
    except OSError as exc:
        raise SettingsError(f"Unable to read settings file {path}: {exc}") from exc

    for section_name, section_values in parsed.items():
        if not isinstance(section_values, dict):
            raise SettingsError(
                f"Invalid settings in {path}: top-level key '{section_name}' must be a table."
            )
        settings.setdefault(section_name, {}).update(section_values)

    return settings


def load_settings_template() -> str:
    """Return the packaged default settings.toml template."""
    return _load_template(SETTINGS_FILENAME)


def load_ssh_config_template() -> str:
    """Return the packaged default ssh_config template."""
    return _load_template(SSH_CONFIG_FILENAME)


def write_default_settings(*, force: bool = False) -> tuple[Path, bool]:
    """Write the default settings template.

    Returns the settings path and a boolean indicating whether a file was written.
    """
    path = get_settings_path()
    return _write_template(path=path, filename=SETTINGS_FILENAME, force=force)


def write_default_config_files(*, force: bool = False) -> list[tuple[Path, bool]]:
    """Write generated config files.

    Returns a list of path/write-status tuples. Existing files are left untouched
    unless force is true.
    """
    return [
        _write_template(path=get_config_dir() / filename, filename=filename, force=force)
        for filename in TEMPLATE_FILENAMES
    ]


def _write_template(*, path: Path, filename: str, force: bool) -> tuple[Path, bool]:
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and not force:
        return path, False

    path.write_text(_load_template(filename), encoding="utf-8")
    return path, True


def _load_template(filename: str) -> str:
    return files(TEMPLATE_PACKAGE).joinpath(filename).read_text(encoding="utf-8")
