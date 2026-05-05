from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Tuple, Type

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

DEFAULT_CONFIG_FILE: Path = Path.home() / ".riverbank" / "config.toml"


class LLMSettings(BaseModel):
    """LLM provider configuration."""

    provider: Literal["ollama", "openai", "anthropic", "vllm", "azure-openai"] = "ollama"
    api_base: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    model: str = "llama3.2"
    embed_model: str = "nomic-embed-text"
    max_tokens: int = 4096


class DatabaseSettings(BaseModel):
    """PostgreSQL database configuration."""

    dsn: str = "postgresql+psycopg://riverbank:riverbank@localhost:5432/riverbank"


class LangfuseSettings(BaseModel):
    """Langfuse observability configuration."""

    enabled: bool = False
    public_key: str = ""
    secret_key: str = ""
    host: str = "http://localhost:3000"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RIVERBANK_",
        env_nested_delimiter="__",
    )

    llm: LLMSettings = Field(default_factory=LLMSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        """Priority: init kwargs > env vars > config.toml file."""
        config_file = Path(
            os.environ.get("RIVERBANK_CONFIG_FILE", str(DEFAULT_CONFIG_FILE))
        )
        if config_file.exists():
            return (
                init_settings,
                env_settings,
                TomlConfigSettingsSource(settings_cls, toml_file=config_file),
            )
        return (init_settings, env_settings)


def get_settings() -> Settings:
    """Return a Settings instance resolved from env vars and optional config.toml."""
    return Settings()
