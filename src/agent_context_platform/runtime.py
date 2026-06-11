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
from agent_context_platform.embeddings import (
    DashScopeEmbeddingProvider,
    EmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
from agent_context_platform.retrieval import HybridSearchService
from agent_context_platform.storage import IndexedItemRepository, make_engine


logger = logging.getLogger(__name__)
_VALID_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


class RuntimeConfigError(ValueError):
    """Raised when runtime configuration cannot safely start the service."""


class EmbeddingProviderSettings(BaseModel):
    """外部 embedding provider 的运行配置。

    例子：DashScope base_url + api_key + model + dimension + batch_size。
    这里的 dimension 会一路传到 EmbeddingIdentity，用来保护向量比较边界。
    """

    # provider 选择请求协议；默认保持历史 DashScope native 行为。
    provider: str = Field(default="dashscope", min_length=1)
    # base_url 是 provider API 根地址，不包含具体 embedding path。
    base_url: str = Field(min_length=1)
    # api_key 只从环境变量读取，不写入文档或日志。
    api_key: str = Field(min_length=1)
    # model 是 embedding 模型名，例如 DashScope 的 multimodal embedding 模型。
    model: str = Field(min_length=1)
    # dimension 必须和 provider 实际返回向量维度一致。
    dimension: int = Field(gt=0)
    # batch_size 控制一次外部请求包含多少 IndexedItem 文本。
    batch_size: int = Field(gt=0)
    # Jina/OpenAI-compatible provider 可用 document/query task 区分索引与查询 mode。
    document_task: str | None = None
    query_task: str | None = None


class RuntimeSettings(BaseModel):
    """应用启动时需要的完整运行配置。

    从 ACP_* 环境变量解析后，create_runtime_app 会把它组装成 engine、session、
    repository、HybridSearchService 和 FastAPI app。
    """

    # database_url 决定真实后端：本地测试可用 SQLite，生产检索应使用 PostgreSQL/pgvector。
    database_url: str = Field(min_length=1)
    # environment 仅标识运行环境，例如 local/test/prod。
    environment: str = Field(default="local", min_length=1)
    # log_level 只控制 agent_context_platform logger。
    log_level: str = "INFO"
    # sql_echo 用于调试 SQLAlchemy 生成的 SQL，不建议生产常开。
    sql_echo: bool = False
    # default_repo 用于单 code repo 本地运行时自动限定检索范围。
    default_repo: str | None = None
    # require_repo_filter 开启后，请求必须显式携带 repo 或由 default_repo 注入。
    require_repo_filter: bool = False
    # embedding 为空时仍可做 keyword 检索；非空时 search 会启用 query embedding。
    embedding: EmbeddingProviderSettings | None = None


def load_runtime_settings(environ: Mapping[str, str] | None = None) -> RuntimeSettings:
    # 这里是 .env/环境变量进入应用的唯一配置入口，调试启动失败先看 ACP_* 是否在这里解析成功。
    values = dict(os.environ if environ is None else environ)
    database_url = _required(values, "ACP_DATABASE_URL")
    embedding = _load_embedding_settings(values)
    try:
        return RuntimeSettings(
            database_url=database_url,
            environment=values.get("ACP_ENV", "local"),
            log_level=_parse_log_level(values.get("ACP_LOG_LEVEL", "INFO")),
            sql_echo=_parse_bool(values.get("ACP_SQL_ECHO", "false"), "ACP_SQL_ECHO"),
            default_repo=_optional_env_value(values.get("ACP_DEFAULT_REPO")),
            require_repo_filter=_parse_bool(
                values.get("ACP_REQUIRE_REPO_FILTER", "false"),
                "ACP_REQUIRE_REPO_FILTER",
            ),
            embedding=embedding,
        )
    except ValidationError as exc:
        raise RuntimeConfigError(f"运行配置格式错误：{exc}") from exc


def create_runtime_app(settings: RuntimeSettings | None = None) -> FastAPI:
    # runtime 负责把配置装配成真实依赖；api.py 只关心传入的 search_service_scope。
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
        # embedding provider 是可选依赖；没有配置时 API 仍可走 keyword-only 检索。
        embedding_provider = build_embedding_provider(resolved_settings.embedding)

    @contextmanager
    def search_service_scope() -> Iterator[HybridSearchService]:
        # 长期运行服务按请求创建 Session，避免把一个可变 Session 绑定到整个进程生命周期。
        with session_factory() as session:
            yield HybridSearchService(
                IndexedItemRepository(session),
                embedding_provider,
            )

    app = create_app(
        search_service_scope=search_service_scope,
        default_repo=resolved_settings.default_repo,
        require_repo_filter=resolved_settings.require_repo_filter,
    )
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.runtime_settings = resolved_settings
    return app


def _load_embedding_settings(
    environ: Mapping[str, str],
) -> EmbeddingProviderSettings | None:
    env_names = {
        "provider": "ACP_EMBEDDING_PROVIDER",
        "base_url": "ACP_EMBEDDING_BASE_URL",
        "api_key": "ACP_EMBEDDING_API_KEY",
        "model": "ACP_EMBEDDING_MODEL",
        "dimension": "ACP_EMBEDDING_DIMENSION",
        "batch_size": "ACP_EMBEDDING_BATCH_SIZE",
        "document_task": "ACP_EMBEDDING_DOCUMENT_TASK",
        "query_task": "ACP_EMBEDDING_QUERY_TASK",
    }
    raw_values = {field: environ.get(name) for field, name in env_names.items()}
    if not any(raw_values.values()):
        return None

    optional_fields = {"provider", "document_task", "query_task"}
    missing = [
        name
        for field, name in env_names.items()
        if field not in optional_fields and not raw_values[field]
    ]
    if missing:
        raise RuntimeConfigError(
            "embedding provider 配置不完整，缺少：" + ", ".join(missing)
        )

    try:
        return EmbeddingProviderSettings(
            provider=str(raw_values["provider"] or "dashscope"),
            base_url=str(raw_values["base_url"]),
            api_key=str(raw_values["api_key"]),
            model=str(raw_values["model"]),
            dimension=_parse_positive_int(
                str(raw_values["dimension"]), "ACP_EMBEDDING_DIMENSION"
            ),
            batch_size=_parse_positive_int(
                str(raw_values["batch_size"]), "ACP_EMBEDDING_BATCH_SIZE"
            ),
            document_task=_optional_env_value(raw_values["document_task"]),
            query_task=_optional_env_value(raw_values["query_task"]),
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


def _optional_env_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def build_embedding_provider(settings: EmbeddingProviderSettings) -> EmbeddingProvider:
    provider = settings.provider.strip().lower()
    if provider == "dashscope":
        return DashScopeEmbeddingProvider(
            base_url=settings.base_url,
            api_key=settings.api_key,
            model=settings.model,
            dimension=settings.dimension,
            batch_size=settings.batch_size,
        )
    if provider in {"openai", "jina"}:
        document_task = settings.document_task
        query_task = settings.query_task
        if provider == "jina":
            document_task = document_task or "retrieval.passage"
            query_task = query_task or "retrieval.query"
        return OpenAICompatibleEmbeddingProvider(
            provider=provider,
            base_url=settings.base_url,
            api_key=settings.api_key,
            model=settings.model,
            dimension=settings.dimension,
            batch_size=settings.batch_size,
            document_task=document_task,
            query_task=query_task,
        )
    raise RuntimeConfigError(
        "ACP_EMBEDDING_PROVIDER 必须是 dashscope、openai 或 jina。"
    )


def _configure_logging(log_level: str) -> None:
    logging.getLogger("agent_context_platform").setLevel(log_level)


