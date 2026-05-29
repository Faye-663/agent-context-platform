from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from agent_context_platform.models import IndexedItem


logger = logging.getLogger(__name__)
_DASHSCOPE_MULTIMODAL_PATH = (
    "/services/embeddings/multimodal-embedding/multimodal-embedding"
)


class EmbeddingProviderError(RuntimeError):
    """Raised when the external embedding provider cannot return usable vectors."""


class EmbeddingDimensionError(ValueError):
    """Raised when embedding dimensions do not match the configured model boundary."""


@dataclass(frozen=True)
class EmbeddingIdentity:
    """一个 embedding 向量空间的身份。

    例子：provider="dashscope", model="text-embedding-v4", dimension=1024。
    只有三者都相同的向量才可以直接做相似度比较。
    """

    # provider 是服务商或实现名，例如 "dashscope" 或测试里的 "fake"。
    provider: str
    # model 是具体 embedding 模型名。
    model: str
    # dimension 是向量维度，用来阻止不同维度向量误写入或误比较。
    dimension: int

    def __post_init__(self) -> None:
        # provider/model/dimension 共同定义向量空间，缺一项都会让后续相似度比较失去意义。
        if not self.provider.strip():
            raise ValueError("embedding provider must not be empty")
        if not self.model.strip():
            raise ValueError("embedding model must not be empty")
        if self.dimension <= 0:
            raise ValueError("embedding dimension must be positive")


class EmbeddingProvider(Protocol):
    identity: EmbeddingIdentity
    batch_size: int

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding for each input text."""


class DashScopeEmbeddingProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimension: int,
        batch_size: int,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not base_url.strip():
            raise ValueError("DashScope base_url must not be empty")
        if not api_key.strip():
            raise ValueError("DashScope api_key must not be empty")
        if batch_size <= 0:
            raise ValueError("DashScope batch_size must be positive")

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.batch_size = batch_size
        self.timeout = timeout
        self.identity = EmbeddingIdentity(
            provider="dashscope",
            model=model,
            dimension=dimension,
        )
        self._client = client or httpx.Client()

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}{_DASHSCOPE_MULTIMODAL_PATH}"

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        # DashScope multimodal embedding 使用 input.contents；不要套用 OpenAI /embeddings 的 payload。
        payload = {
            "model": self.model,
            "input": {"contents": [{"text": text} for text in texts]},
            "parameters": {"dimension": self.identity.dimension},
        }
        try:
            response = self._client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            logger.exception(
                "embedding_provider_error provider=dashscope endpoint_path=%s model=%s",
                _DASHSCOPE_MULTIMODAL_PATH,
                self.model,
            )
            raise EmbeddingProviderError(
                f"DashScope embedding request failed: {exc}"
            ) from exc

        if response.status_code >= 400:
            code, message = _provider_error(response)
            logger.error(
                "embedding_provider_error provider=dashscope endpoint_path=%s "
                "model=%s status_code=%s error_code=%s",
                _DASHSCOPE_MULTIMODAL_PATH,
                self.model,
                response.status_code,
                code,
            )
            raise EmbeddingProviderError(
                f"DashScope embedding request failed with {response.status_code}: "
                f"{code} {message}".strip()
            )

        embeddings = _parse_dashscope_embeddings(response)
        if len(embeddings) != len(texts):
            raise EmbeddingProviderError(
                "DashScope embedding response count does not match input count"
            )
        for embedding in embeddings:
            # 维度必须在 provider 边界先校验，避免错误向量写入 item_embeddings 后才暴露。
            _validate_embedding_dimension(embedding, self.identity)
        return embeddings


def embed_and_save_items(
    repository: Any,
    provider: EmbeddingProvider,
    items: Sequence[IndexedItem],
) -> int:
    saved_count = 0
    for batch in _batches(items, provider.batch_size):
        # 批量调用外部 provider，减少网络往返；保存时仍逐条保留 item 与 embedding 的对应关系。
        texts = [_embedding_text(item) for item in batch]
        embeddings = provider.embed_texts(texts)
        if len(embeddings) != len(batch):
            raise EmbeddingProviderError(
                "embedding provider returned a different number of vectors"
            )
        for item, embedding in zip(batch, embeddings):
            repository.save(
                item,
                embedding=embedding,
                embedding_identity=provider.identity,
            )
            saved_count += 1
    return saved_count


def _batches(
    items: Sequence[IndexedItem], batch_size: int
) -> list[Sequence[IndexedItem]]:
    if batch_size <= 0:
        raise ValueError("embedding batch_size must be positive")
    return [
        items[index : index + batch_size]
        for index in range(0, len(items), batch_size)
    ]


def _embedding_text(item: IndexedItem) -> str:
    # embedding 文本保留 title/summary/content，避免只嵌入正文时丢掉符号名和章节名。
    return "\n".join([item.title, item.summary, item.content])


def _parse_dashscope_embeddings(response: httpx.Response) -> list[list[float]]:
    try:
        raw = response.json()
        raw_embeddings = raw["output"]["embeddings"]
    except (KeyError, TypeError, ValueError) as exc:
        raise EmbeddingProviderError(
            "DashScope embedding response shape is invalid"
        ) from exc

    embeddings: list[list[float]] = []
    for raw_embedding in raw_embeddings:
        try:
            embedding = raw_embedding["embedding"]
        except (KeyError, TypeError) as exc:
            raise EmbeddingProviderError(
                "DashScope embedding response item is invalid"
            ) from exc
        embeddings.append([float(value) for value in embedding])
    return embeddings


def _provider_error(response: httpx.Response) -> tuple[str, str]:
    try:
        payload = response.json()
    except ValueError:
        return "unknown", response.text

    if isinstance(payload, dict):
        code = str(
            payload.get("code") or payload.get("error", {}).get("code") or "unknown"
        )
        message = str(
            payload.get("message") or payload.get("error", {}).get("message") or ""
        )
        return code, message
    return "unknown", str(payload)


def _validate_embedding_dimension(
    embedding: Sequence[float],
    identity: EmbeddingIdentity,
) -> None:
    if len(embedding) != identity.dimension:
        raise EmbeddingDimensionError(
            "embedding dimension mismatch for "
            f"{identity.provider}/{identity.model}: expected {identity.dimension}, "
            f"got {len(embedding)}"
        )
