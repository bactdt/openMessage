import os
import warnings
from dataclasses import dataclass
from typing import AbstractSet, Mapping, Optional


DEVELOPMENT_SECRET_KEY = "openmessage-development-secret-key"
DEFAULT_ALLOWED_EXPIRES = frozenset({3600, 86400, 604800})
FALSE_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Config:
    SECRET_KEY: str
    MAX_CONTENT_LENGTH: int
    RATE_LIMIT_STORAGE_URI: str
    V2_E2E_ENABLED: bool
    ALLOWED_EXPIRES: AbstractSet[int]
    HOST: str
    PORT: int
    WORKERS: int
    BIND: str


def _env_value(env: Mapping[str, str], name: str) -> Optional[str]:
    value = env.get(name)
    if value is None or value == "":
        return None
    return value


def _is_production(env: Mapping[str, str]) -> bool:
    return any(env.get(name, "").strip().lower() == "production" for name in ("APP_ENV", "FLASK_ENV"))


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in FALSE_VALUES


def _env_int(env: Mapping[str, str], name: str, default: int, minimum: Optional[int] = None) -> int:
    raw = env.get(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        value = default
    if minimum is not None:
        value = max(value, minimum)
    return value


def _secret_key(env: Mapping[str, str]) -> str:
    secret_key = _env_value(env, "SECRET_KEY")
    if secret_key is not None:
        return secret_key

    if _is_production(env):
        raise RuntimeError("SECRET_KEY is required when APP_ENV or FLASK_ENV is production")

    warnings.warn(
        "SECRET_KEY is not set; using deterministic development fallback",
        RuntimeWarning,
        stacklevel=2,
    )
    return DEVELOPMENT_SECRET_KEY


def load_config(env: Optional[Mapping[str, str]] = None) -> Config:
    source = os.environ if env is None else env
    host = source.get("HOST", "0.0.0.0")
    port = _env_int(source, "PORT", 5000, minimum=1)
    workers = _env_int(source, "WORKERS", 4, minimum=1)
    bind = source.get("BIND", f"{host}:{port}")

    return Config(
        SECRET_KEY=_secret_key(source),
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        RATE_LIMIT_STORAGE_URI=source.get("RATE_LIMIT_STORAGE_URI", "memory://"),
        V2_E2E_ENABLED=_env_bool(source, "OPENMESSAGE_V2_E2E", True),
        ALLOWED_EXPIRES=DEFAULT_ALLOWED_EXPIRES,
        HOST=host,
        PORT=port,
        WORKERS=workers,
        BIND=bind,
    )
