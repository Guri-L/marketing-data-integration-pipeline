"""Credential handling.

Rules this module enforces:
* secrets are only ever read from the environment or GCP Secret Manager,
  never from files in the repository;
* a secret is wrapped in ``Secret`` the moment it is read, so printing a
  settings object, an exception or a log record cannot leak it;
* every secret value read is registered with the log redaction filter.
"""

from __future__ import annotations

import os

from .exceptions import ConfigurationError

_REGISTERED: set[str] = set()


class Secret:
    """A string that never shows its value unless ``reveal()`` is called."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value
        if len(value) >= 6:  # too-short values would redact ordinary log text
            _REGISTERED.add(value)

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret('********')"

    __str__ = __repr__

    def __bool__(self) -> bool:
        return bool(self._value)


def registered_secret_values() -> frozenset[str]:
    """Values the logging filter must mask."""
    return frozenset(_REGISTERED)


def get_secret(name: str, *, backend: str = "env", project_id: str | None = None) -> Secret:
    """Resolve secret ``name`` (an env-var style name such as META_ACCESS_TOKEN)."""
    if backend == "env":
        value = os.environ.get(name, "").strip()
        if not value:
            raise ConfigurationError(f"Missing required secret: environment variable {name}")
        return Secret(value)
    if backend == "gcp_secret_manager":
        return Secret(_from_secret_manager(name, project_id))
    raise ConfigurationError(f"Unknown SECRET_BACKEND: {backend!r}")


def _from_secret_manager(name: str, project_id: str | None) -> str:
    if not project_id:
        raise ConfigurationError(
            "GCP_PROJECT_ID is required when SECRET_BACKEND=gcp_secret_manager"
        )
    try:
        from google.cloud import secretmanager
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ConfigurationError(
            "Install the 'live' extra to use Secret Manager: pip install -e '.[live]'"
        ) from exc
    secret_id = name.lower().replace("_", "-")
    resource = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    try:
        client = secretmanager.SecretManagerServiceClient()
        payload = client.access_secret_version(name=resource).payload.data
    except Exception as exc:  # noqa: BLE001 - surface any client failure as config error
        raise ConfigurationError(
            f"Could not read secret {secret_id!r} from Secret Manager"
        ) from exc
    return payload.decode("utf-8").strip()
