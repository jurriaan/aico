import os
from pathlib import Path
from typing import TypedDict

from pydantic import TypeAdapter, ValidationError


class TrustConfig(TypedDict):
    trusted_projects: list[str]


# Use XDG_CONFIG_HOME or default to ~/.config/aico
def _get_config_dir() -> Path:
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else Path.home() / ".config"
    return base / "aico"


def _get_trust_file() -> Path:
    return _get_config_dir() / "trust.json"


def _load_trusted_paths() -> set[str]:
    """Loads trusted paths as a set of strings."""
    trust_file = _get_trust_file()
    if not trust_file.exists():
        return set()

    try:
        data: TrustConfig = TypeAdapter(TrustConfig).validate_json(trust_file.read_text(encoding="utf-8"))
        return set(data["trusted_projects"])
    except (ValidationError, OSError, KeyError):
        return set()


def _save_trusted_paths(paths: set[str]) -> None:
    """Saves the set of paths to the JSON file."""
    trust_file = _get_trust_file()
    trust_file.parent.mkdir(parents=True, exist_ok=True)

    data: TrustConfig = {"trusted_projects": sorted(list(paths))}

    # Atomic write to prevent corruption
    from aico.lib.atomic_io import atomic_write_text

    atomic_write_text(trust_file, TypeAdapter(TrustConfig).dump_json(data, indent=2))
    trust_file.chmod(0o600)


def is_project_trusted(path: Path) -> bool:
    """
    Checks if a specific path is in the trust allowlist.
    Resolves the path to absolute before checking.
    """
    resolved_path = str(path.resolve())
    trusted_paths = _load_trusted_paths()
    return resolved_path in trusted_paths


def trust_project(path: Path) -> None:
    """Adds a path to the trust allowlist."""
    resolved_path = str(path.resolve())
    trusted_paths = _load_trusted_paths()

    trusted_paths.add(resolved_path)
    _save_trusted_paths(trusted_paths)


def untrust_project(path: Path) -> bool:
    """
    Removes a path from the trust allowlist.
    Returns True if removed, False if it wasn't there.
    """
    resolved_path = str(path.resolve())
    trusted_paths = _load_trusted_paths()

    if resolved_path in trusted_paths:
        trusted_paths.remove(resolved_path)
        _save_trusted_paths(trusted_paths)
        return True
    return False


def list_trusted_projects() -> list[str]:
    """Returns a sorted list of trusted project paths."""
    return sorted(list(_load_trusted_paths()))
