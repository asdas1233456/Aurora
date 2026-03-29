"""项目配置模块。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH, override=False)

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}
OPENAI_PROVIDER = "openai"
OPENAI_COMPATIBLE_PROVIDERS = {
    "openai_compatible",
    "deepseek",
    "qwen",
    "zhipu",
    "moonshot",
    "siliconflow",
    "openrouter",
}
SUPPORTED_MODEL_PROVIDERS = {OPENAI_PROVIDER, *OPENAI_COMPATIBLE_PROVIDERS}
PROVIDER_ALIASES = {
    "compatible": "openai_compatible",
    "custom_api": "openai_compatible",
    "openai_compatible_api": "openai_compatible",
    "dashscope": "qwen",
    "tongyi": "qwen",
    "bigmodel": "zhipu",
    "glm": "zhipu",
    "kimi": "moonshot",
    "moonshot_ai": "moonshot",
    "silicon": "siliconflow",
    "silicon_cloud": "siliconflow",
}


def _get_env(*names: str, default: str = "") -> str:
    """按顺序读取环境变量，返回第一个非空值。"""
    for name in names:
        value = os.getenv(name)
        if value is not None:
            stripped_value = value.strip()
            if stripped_value:
                return stripped_value
    return default


def _normalize_provider(value: str, default: str = "openai") -> str:
    """统一 provider 命名，减少配置时的歧义。"""
    normalized = value.strip().lower().replace("-", "_")
    if not normalized:
        return default
    return PROVIDER_ALIASES.get(normalized, normalized)


def is_openai_provider(value: str) -> bool:
    return _normalize_provider(value) == OPENAI_PROVIDER


def is_openai_compatible_provider(value: str) -> bool:
    return _normalize_provider(value) in OPENAI_COMPATIBLE_PROVIDERS


@dataclass(slots=True)
class AppConfig:
    """统一管理项目中的基础配置。"""

    base_dir: Path = BASE_DIR
    data_dir: Path = BASE_DIR / "data"
    db_dir: Path = BASE_DIR / "db"
    logs_dir: Path = BASE_DIR / "logs"
    collection_name: str = field(
        default_factory=lambda: _get_env("CHROMA_COLLECTION_NAME", default="ai_kb_docs")
    )
    llm_provider: str = field(
        default_factory=lambda: _normalize_provider(_get_env("LLM_PROVIDER", default="openai"))
    )
    embedding_provider: str = field(
        default_factory=lambda: _normalize_provider(
            _get_env("EMBEDDING_PROVIDER", default="openai")
        )
    )
    llm_api_key: str = field(default_factory=lambda: _get_env("LLM_API_KEY", "OPENAI_API_KEY"))
    llm_api_base: str = field(
        default_factory=lambda: _get_env("LLM_API_BASE", "OPENAI_API_BASE")
    )
    llm_model: str = field(
        default_factory=lambda: _get_env("LLM_MODEL", "OPENAI_MODEL", default="gpt-4.1-mini")
    )
    llm_temperature: float = field(
        default_factory=lambda: float(
            _get_env("LLM_TEMPERATURE", "OPENAI_TEMPERATURE", default="0.2")
        )
    )
    llm_timeout: float = field(default_factory=lambda: float(_get_env("LLM_TIMEOUT", default="60")))
    llm_max_tokens: int = field(
        default_factory=lambda: int(_get_env("LLM_MAX_TOKENS", default="2048"))
    )
    embedding_api_key: str = field(
        default_factory=lambda: _get_env("EMBEDDING_API_KEY", "OPENAI_API_KEY")
    )
    embedding_api_base: str = field(
        default_factory=lambda: _get_env("EMBEDDING_API_BASE", "OPENAI_API_BASE")
    )
    embedding_model: str = field(
        default_factory=lambda: _get_env(
            "EMBEDDING_MODEL",
            "OPENAI_EMBED_MODEL",
            default="text-embedding-3-small",
        )
    )
    chunk_size: int = field(default_factory=lambda: int(_get_env("CHUNK_SIZE", default="800")))
    chunk_overlap: int = field(
        default_factory=lambda: int(_get_env("CHUNK_OVERLAP", default="100"))
    )
    default_top_k: int = field(default_factory=lambda: int(_get_env("TOP_K", default="4")))
    max_history_turns: int = field(
        default_factory=lambda: int(_get_env("MAX_HISTORY_TURNS", default="6"))
    )
    no_answer_min_score: float = field(
        default_factory=lambda: float(_get_env("NO_ANSWER_MIN_SCORE", default="0.22"))
    )
    log_level: str = field(default_factory=lambda: _get_env("LOG_LEVEL", default="INFO").upper())
    api_host: str = field(default_factory=lambda: _get_env("API_HOST", default="127.0.0.1"))
    api_port: int = field(default_factory=lambda: int(_get_env("API_PORT", default="8000")))
    cors_origins: str = field(default_factory=lambda: _get_env("CORS_ORIGINS", default="*"))
    app_name: str = "Aurora"
    app_title: str = "Aurora - 软件测试知识工作台"
    app_version: str = "v0.7.0"

    @property
    def llm_api_ready(self) -> bool:
        if not self.llm_model:
            return False
        if is_openai_provider(self.llm_provider):
            return bool(self.llm_api_key)
        if is_openai_compatible_provider(self.llm_provider):
            return bool(self.llm_api_base)
        return False

    @property
    def embedding_api_ready(self) -> bool:
        if not self.embedding_model:
            return False
        if is_openai_provider(self.embedding_provider):
            return bool(self.embedding_api_key)
        if is_openai_compatible_provider(self.embedding_provider):
            return bool(self.embedding_api_base)
        return False

    @property
    def api_key_ready(self) -> bool:
        return self.llm_api_ready and self.embedding_api_ready

    @property
    def llm_api_key_for_client(self) -> str:
        return self.llm_api_key or "EMPTY"

    @property
    def embedding_api_key_for_client(self) -> str:
        return self.embedding_api_key or "EMPTY"

    @property
    def supported_extensions_text(self) -> str:
        return ", ".join(sorted(SUPPORTED_EXTENSIONS))

    @property
    def app_log_path(self) -> Path:
        return self.logs_dir / "app.log"

    @property
    def docs_api_url(self) -> str:
        return f"http://{self.api_host}:{self.api_port}/docs"

    @property
    def cors_origin_list(self) -> list[str]:
        raw_items = [item.strip() for item in self.cors_origins.split(",")]
        return [item for item in raw_items if item]

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def with_runtime_overrides(
        self,
        *,
        llm_api_key: str = "",
        embedding_api_key: str = "",
        llm_api_base: str = "",
        embedding_api_base: str = "",
    ) -> "AppConfig":
        """基于当前配置生成带运行时覆盖的新配置。"""
        updated_config = replace(self)

        if llm_api_key.strip():
            updated_config.llm_api_key = llm_api_key.strip()
        if embedding_api_key.strip():
            updated_config.embedding_api_key = embedding_api_key.strip()
        if llm_api_base.strip():
            updated_config.llm_api_base = llm_api_base.strip()
        if embedding_api_base.strip():
            updated_config.embedding_api_base = embedding_api_base.strip()

        return updated_config


def get_config() -> AppConfig:
    """返回初始化后的配置对象。"""
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    config = AppConfig()
    config.ensure_directories()
    return config
