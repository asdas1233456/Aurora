"""Legacy config import path kept for compatibility."""

from app.core import config as _core_config
from app.core.config import *  # noqa: F401,F403

_get_env = _core_config._get_env
_get_env_bool = _core_config._get_env_bool
_normalize_provider = _core_config._normalize_provider
