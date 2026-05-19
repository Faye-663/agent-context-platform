from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import sessionmaker

from agent_context_platform.api import create_app
from agent_context_platform.embeddings import DashScopeEmbeddingProvider
from agent_context_platform.retrieval import HybridSearchService
from agent_context_platform.storage import IndexedItemRepository, make_engine


logger = logging.getLogger(__name__)
_VALID_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


class RuntimeConfigError(ValueError):
    """Raised when runtime configuration cannot safely start the service."""


class EmbeddingProviderSettings(BaseModel):
    base_url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    model: str = Field(min_length=1)
    dimension: int = Field(gt=0)
    batch_size: int = Field(gt=0)


class RuntimeSettings(BaseModel):
    database_url: str = Field(min_length=1)
    environment: str = Field(default="local", min_length=1)
    log_level: str = "INFO"
    sql_echo: bool = False
    embedding: EmbeddingProviderSettings | None = None


def load_runtime_settings(environ: Mapping[str, str] | None = None) -> RuntimeSettings:
    values = dict(os.environ if environ is None else environ)
    database_url = _required(values, "ACP_DATABASE_URL")
    embedding = _load_embedding_settings(values)
    try:
        return RuntimeSettings(
            database_url=database_url,
            environment=values.get("ACP_ENV", "local"),
            log_level=_parse_log_level(values.get("ACP_LOG_LEVEL", "INFO")),
            sql_echo=_parse_bool(values.get("ACP_SQL_ECHO", "false"), "ACP_SQL_ECHO"),
            embedding=embedding,
        )
    except ValidationError as exc:
        raise RuntimeConfigError(f"运行配置格式错误：{exc}") from exc


def create_runtime_app(settings: RuntimeSettings | None = None) -> FastAPI:
    resolved_settings = settings or load_runtime_settings()
    _configure_logging(resolved_settings.log_level)
    try:
        engine = make_engine(
            resolved_settings.database_url,
            echo=resolved_settings.sql_echo,
        )
    except ArgumentError as exc:
        logger.exception("runtime_config_error invalid_database_url")
        raise RuntimeConfigError(f"ACP_DATABASE_URL 格式错误：{exc}") from exc

    session_factory = sessionmaker(bind=engine)
    embedding_provider = None
    if resolved_settings.embedding is not None:
        embedding_provider = DashScopeEmbeddingProvider(
            base_url=resolved_settings.embedding.base_url,
            api_key=resolved_settings.embedding.api_key,
            model=resolved_settings.embedding.model,
            dimension=resolved_settings.embedding.dimension,
            batch_size=resolved_settings.embedding.batch_size,
        )

    @contextmanager
    def search_service_scope() -> Iterator[HybridSearchService]:
        # 长期运行服务按请求创建 Session，避免把一个可变 Session 绑定到整个进程生命周期。
        with session_factory() as session:
            yield HybridSearchService(
                IndexedItemRepository(session),
                embedding_provider,
            )

    app = create_app(search_service_scope=search_service_scope)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.runtime_settings = resolved_settings
    return app


def _load_embedding_settings(
    environ: Mapping[str, str],
) -> EmbeddingProviderSettings | None:
    env_names = {
        "base_url": "ACP_EMBEDDING_BASE_URL",
        "api_key": "ACP_EMBEDDING_API_KEY",
        "model": "ACP_EMBEDDING_MODEL",
        "dimension": "ACP_EMBEDDING_DIMENSION",
        "batch_size": "ACP_EMBEDDING_BATCH_SIZE",
    }
    raw_values = {field: environ.get(name) for field, name in env_names.items()}
    if not any(raw_values.values()):
        return None

    missing = [name for field, name in env_names.items() if not raw_values[field]]
    if missing:
        raise RuntimeConfigError(
            "embedding provider 配置不完整，缺少：" + ", ".join(missing)
        )

    try:
        return EmbeddingProviderSettings(
            base_url=str(raw_values["base_url"]),
            api_key=str(raw_values["api_key"]),
            model=str(raw_values["model"]),
            dimension=_parse_positive_int(
                str(raw_values["dimension"]), "ACP_EMBEDDING_DIMENSION"
            ),
            batch_size=_parse_positive_int(
                str(raw_values["batch_size"]), "ACP_EMBEDDING_BATCH_SIZE"
            ),
        )
    except ValidationError as exc:
        raise RuntimeConfigError(f"embedding provider 配置格式错误：{exc}") from exc


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        logger.error("runtime_config_error missing_env=%s", name)
        raise RuntimeConfigError(f"缺少必填运行配置：{name}")
    return value


def _parse_log_level(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in _VALID_LOG_LEVELS:
        raise RuntimeConfigError(
            "ACP_LOG_LEVEL 必须是 CRITICAL、ERROR、WARNING、INFO 或 DEBUG。"
        )
    return normalized


def _parse_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeConfigError(f"{name} 必须是 true/false 类型值。")


def _parse_positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeConfigError(f"{name} 必须是正整数。") from exc
    if parsed <= 0:
        raise RuntimeConfigError(f"{name} 必须是正整数。")
    return parsed


def _configure_logging(log_level: str) -> None:
    logging.getLogger("agent_context_platform").setLevel(log_level)


