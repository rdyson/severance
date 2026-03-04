"""Configuration loading from YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class ProviderConfig:
    admin_api_key: str = ""


@dataclass
class GoogleConfig:
    project_id: str = ""
    credentials_path: str = ""


@dataclass
class AuthConfig:
    username: str = "admin"
    password: str = "changeme"


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8077


@dataclass
class RefreshConfig:
    interval_hours: int = 6
    default_granularity: str = "1d"


@dataclass
class Config:
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    google: Optional[GoogleConfig] = None
    auth: AuthConfig = field(default_factory=AuthConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    refresh: RefreshConfig = field(default_factory=RefreshConfig)


def load_config(path: str | Path | None = None) -> Config:
    """Load config from YAML file. Falls back to config.yaml in CWD."""
    if path is None:
        path = os.environ.get("SEVERANCE_CONFIG", "config.yaml")
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Copy config.example.yaml to config.yaml and fill in your keys."
        )

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    cfg = Config()

    # Providers
    for name, prov in (raw.get("providers") or {}).items():
        if name == "google":
            cfg.google = GoogleConfig(
                project_id=prov.get("project_id", ""),
                credentials_path=prov.get("credentials_path", ""),
            )
        else:
            cfg.providers[name] = ProviderConfig(
                admin_api_key=prov.get("admin_api_key", ""),
            )

    # Auth
    auth = raw.get("auth") or {}
    cfg.auth = AuthConfig(
        username=auth.get("username", "admin"),
        password=auth.get("password", "changeme"),
    )

    # Server
    srv = raw.get("server") or {}
    cfg.server = ServerConfig(
        host=srv.get("host", "127.0.0.1"),
        port=srv.get("port", 8077),
    )

    # Refresh
    ref = raw.get("refresh") or {}
    cfg.refresh = RefreshConfig(
        interval_hours=ref.get("interval_hours", 6),
        default_granularity=ref.get("default_granularity", "1d"),
    )

    return cfg
