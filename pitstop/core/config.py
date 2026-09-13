"""Configuration: defaults, validation, updates and the one-time invalid-config notice."""
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple

from pitstop.core.fsutil import atomic_write_text
from pitstop.core.paths import Layout


@dataclass(frozen=True)
class Config:
    enabled: bool = True
    notify: bool = True
    threshold_tokens: int = 200000
    retrigger_step_tokens: int = 50000
    resume_window_minutes: int = 60


class ConfigError(Exception):
    """config.json cannot be used. The message is shown to the user, in Italian."""


_BOOL_KEYS = ("enabled", "notify")
_INT_RANGES = {
    "threshold_tokens": (50000, 900000),
    "retrigger_step_tokens": (10000, None),
    "resume_window_minutes": (1, 60),
}


def parse_config(raw: Any) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("il file deve contenere un oggetto JSON")
    values: Dict[str, Any] = asdict(Config())
    for key in _BOOL_KEYS:
        if key in raw:
            if not isinstance(raw[key], bool):
                raise ConfigError("%s deve essere true o false" % key)
            values[key] = raw[key]
    for key, (low, high) in _INT_RANGES.items():
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError("%s deve essere un numero intero" % key)
        if value < low or (high is not None and value > high):
            limit = "%d–%d" % (low, high) if high is not None else "≥ %d" % low
            raise ConfigError("%s fuori intervallo (%s)" % (key, limit))
        values[key] = value
    return Config(**values)


def load_config(layout: Layout) -> Tuple[Config, Optional[str]]:
    """Missing file: defaults. Unusable file: pitstop disabled, plus the reason."""
    try:
        text = layout.config.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Config(), None
    except OSError as exc:
        return Config(enabled=False), "config.json illeggibile (%s)" % exc.strerror
    try:
        return parse_config(json.loads(text)), None
    except ValueError:
        return Config(enabled=False), "config.json non è JSON valido"
    except ConfigError as exc:
        return Config(enabled=False), str(exc)


def update_config(layout: Layout, **changes: Any) -> Config:
    """Apply changes and rewrite config.json in full. Never overwrites a file it cannot parse."""
    try:
        raw = json.loads(layout.config.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    except ValueError:
        raise ConfigError("config.json non è JSON valido: correggilo o cancellalo") from None
    if not isinstance(raw, dict):
        raise ConfigError("config.json deve contenere un oggetto JSON: correggilo o cancellalo")
    raw.update(changes)
    config = parse_config(raw)
    atomic_write_text(layout.config, json.dumps(asdict(config), indent=2) + "\n")
    return config


def should_show_config_notice(layout: Layout, error: str) -> bool:
    """True the first time an error is seen for a given version of config.json."""
    try:
        version = str(layout.config.stat().st_mtime_ns)
    except OSError:
        version = "missing"
    key = "%s|%s" % (version, error)
    try:
        if layout.config_notice.read_text(encoding="utf-8") == key:
            return False
    except OSError:
        pass
    atomic_write_text(layout.config_notice, key)
    return True
