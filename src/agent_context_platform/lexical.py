from __future__ import annotations

import logging
import math
import re
import threading
import warnings
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from agent_context_platform.models import IndexedItem

try:  # pragma: no cover - fallback path is covered by pure helper tests.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="invalid escape sequence.*",
            category=SyntaxWarning,
        )
        import jieba

    jieba.setLogLevel(logging.ERROR)
except ImportError:  # pragma: no cover - production dependency should install jieba.
    jieba = None


_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[._:-][A-Za-z0-9]+)*|[0-9]+")
_CHINESE_SEGMENT_RE = re.compile(r"[\u4e00-\u9fff]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SEPARATORS_RE = re.compile(r"[._:/\\#@$+,\-\s]+")
_JIEBA_LOCK = threading.Lock()
_JIEBA_REGISTERED_TERMS: set[str] = set()
_CHINESE_MIN_TOKEN_LENGTH = 2
_CHINESE_MAX_FALLBACK_NGRAM = 4

# 轻量内置词表只覆盖工程检索里常见的中文业务/技术词，避免 fallback 退回纯 bigram。
_ENGINEERING_CHINESE_TERMS = frozenset(
    {
        "知识库",
        "上下文",
        "多路召回",
        "向量检索",
        "关键词检索",
        "混合检索",
        "结构化索引",
        "关系索引",
        "代码索引",
        "查询路由",
        "重排序",
        "来源引用",
        "可追溯",
        "工程知识",
        "业务规则",
        "风险点",
        "风险标签",
        "状态",
        "流转",
        "状态流转",
        "状态机",
        "接口文档",
        "设计文档",
        "表结构",
        "数据库",
        "数据表",
        "字段",
        "主键",
        "索引",
        "实体关系",
        "模块",
        "核心类",
        "相关类",
        "方法",
        "类名",
        "方法名",
        "调用链",
        "影响分析",
        "单元测试",
        "异常处理",
        "错误码",
        "幂等",
        "重试",
        "补偿",
        "回滚",
        "权限",
        "审计",
        "支付",
        "订单",
        "支付订单",
        "报文",
        "支付报文",
        "校验",
        "审批",
        "审批流",
        "现金流",
        "现金流审批",
        "资金",
        "资金安全",
        "风控",
        "对账",
        "清算",
        "结算",
        "账务",
        "交易",
        "金额",
        "付款",
        "收款",
        "退款",
        "入账",
        "出账",
        "余额",
        "账户",
        "商户",
        "客户",
        "凭证",
        "限额",
        "费率",
        "汇率",
    }
)
_CHINESE_STOPWORDS = frozenset(
    {
        "一个",
        "一些",
        "这个",
        "那个",
        "哪些",
        "什么",
        "怎么",
        "如何",
        "是否",
        "以及",
        "或者",
        "并且",
        "相关",
        "涉及",
        "需要",
        "当前",
    }
)


@dataclass(frozen=True)
class LexicalTokenSet:
    tokens: tuple[str, ...]
    symbol_terms: tuple[str, ...]


@dataclass(frozen=True)
class LexicalScore:
    score: float
    raw_score: float
    matched_tokens: tuple[str, ...]
    matched_fields: tuple[str, ...]


@dataclass(frozen=True)
class FieldTokens:
    field: str
    weight: float
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class CandidateDocument:
    item: IndexedItem
    fields: tuple[FieldTokens, ...]
    token_counts: Counter[str] = field(init=False)
    field_hits: dict[str, set[str]] = field(init=False)
    length: float = field(init=False)

    def __post_init__(self) -> None:
        counts: Counter[str] = Counter()
        field_hits: dict[str, set[str]] = {}
        length = 0.0
        for field_tokens in self.fields:
            field_counter = Counter(field_tokens.tokens)
            for token, count in field_counter.items():
                counts[token] += count * field_tokens.weight
                field_hits.setdefault(token, set()).add(field_tokens.field)
                length += count * field_tokens.weight
        object.__setattr__(self, "token_counts", counts)
        object.__setattr__(self, "field_hits", field_hits)
        object.__setattr__(self, "length", max(length, 1.0))


def tokenize_query(text: str, domain_terms: tuple[str, ...] = ()) -> LexicalTokenSet:
    tokens = _tokenize_text(text, domain_terms=domain_terms)
    return LexicalTokenSet(
        tokens=tuple(sorted(set(tokens))),
        symbol_terms=tuple(sorted(_symbol_terms(text))),
    )


def tokenize_item(item: IndexedItem, domain_terms: tuple[str, ...] = ()) -> CandidateDocument:
    fields = [
        FieldTokens("title", 3.0, tuple(_tokenize_text(item.title, domain_terms=domain_terms))),
        FieldTokens(
            "summary", 1.8, tuple(_tokenize_text(item.summary, domain_terms=domain_terms))
        ),
        FieldTokens(
            "content", 1.0, tuple(_tokenize_text(item.content, domain_terms=domain_terms))
        ),
        FieldTokens(
            "metadata", 1.5, tuple(_tokenize_metadata(item.metadata, domain_terms))
        ),
    ]
    source = item.source
    if source.symbol:
        fields.append(
            FieldTokens(
                "symbol", 4.0, tuple(_tokenize_text(source.symbol, domain_terms=domain_terms))
            )
        )
    if source.table:
        fields.append(
            FieldTokens(
                "table", 4.0, tuple(_tokenize_text(source.table, domain_terms=domain_terms))
            )
        )
    if source.column:
        fields.append(
            FieldTokens(
                "column", 4.0, tuple(_tokenize_text(source.column, domain_terms=domain_terms))
            )
        )
    if source.heading_path:
        fields.append(
            FieldTokens(
                "heading_path",
                3.0,
                tuple(_tokenize_text(source.heading_path, domain_terms=domain_terms)),
            )
        )
    if source.path:
        fields.append(
            FieldTokens("path", 1.2, tuple(_tokenize_text(source.path, domain_terms=domain_terms)))
        )
    return CandidateDocument(item=item, fields=tuple(fields))


def score_documents(
    query_tokens: tuple[str, ...],
    items: list[IndexedItem],
    *,
    domain_terms: tuple[str, ...] = (),
) -> dict[tuple[str | None, str], LexicalScore]:
    if not query_tokens or not items:
        return {}

    documents = [tokenize_item(item, domain_terms=domain_terms) for item in items]
    document_frequency: Counter[str] = Counter()
    for document in documents:
        for token in set(document.token_counts):
            document_frequency[token] += 1

    average_length = sum(document.length for document in documents) / len(documents)
    raw_scores: dict[tuple[str | None, str], LexicalScore] = {}
    for document in documents:
        raw_score = 0.0
        matched_tokens: set[str] = set()
        matched_fields: set[str] = set()
        for token in query_tokens:
            term_frequency = document.token_counts.get(token, 0.0)
            if term_frequency <= 0:
                continue
            matched_tokens.add(token)
            matched_fields.update(document.field_hits.get(token, set()))
            idf = math.log(
                1.0
                + (len(documents) - document_frequency[token] + 0.5)
                / (document_frequency[token] + 0.5)
            )
            raw_score += idf * _bm25_tf(term_frequency, document.length, average_length)
        if raw_score <= 0:
            continue
        raw_scores[(document.item.source.repo, document.item.id)] = LexicalScore(
            score=raw_score,
            raw_score=raw_score,
            matched_tokens=tuple(sorted(matched_tokens)),
            matched_fields=tuple(sorted(matched_fields)),
        )

    if not raw_scores:
        return {}
    max_score = max(score.raw_score for score in raw_scores.values())
    return {
        key: LexicalScore(
            score=round(score.raw_score / max_score, 6),
            raw_score=round(score.raw_score, 6),
            matched_tokens=score.matched_tokens,
            matched_fields=score.matched_fields,
        )
        for key, score in raw_scores.items()
    }


def _bm25_tf(
    term_frequency: float,
    document_length: float,
    average_document_length: float,
    *,
    k1: float = 1.2,
    b: float = 0.75,
) -> float:
    denominator = term_frequency + k1 * (
        1.0 - b + b * (document_length / max(average_document_length, 1.0))
    )
    return (term_frequency * (k1 + 1.0)) / denominator


def _tokenize_metadata(metadata: dict[str, Any], domain_terms: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for value in metadata.values():
        if isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value)
        elif isinstance(value, dict):
            values.extend(str(item) for item in value.values())
        else:
            values.append(str(value))
    return _tokenize_text(" ".join(values), domain_terms=domain_terms)


def _tokenize_text(text: str, *, domain_terms: tuple[str, ...] = ()) -> list[str]:
    normalized_domain_terms = {
        term.strip().lower() for term in domain_terms if len(term.strip()) > 1
    }
    tokens: list[str] = []
    lowered = text.lower()
    for term in normalized_domain_terms:
        if term in lowered:
            tokens.extend(_tokenize_domain_term(term))

    for match in _ASCII_TOKEN_RE.finditer(text):
        tokens.extend(_split_engineering_token(match.group(0)))

    for segment in _CHINESE_SEGMENT_RE.findall(text):
        tokens.extend(_split_chinese_segment(segment, normalized_domain_terms))

    return [token for token in tokens if len(token) > 1]


def _split_engineering_token(token: str) -> list[str]:
    pieces: list[str] = []
    raw_parts = [part for part in _SEPARATORS_RE.split(token) if part]
    for raw_part in raw_parts:
        pieces.append(raw_part.lower())
        pieces.extend(part.lower() for part in _CAMEL_BOUNDARY_RE.split(raw_part) if part)
    if len(raw_parts) > 1:
        pieces.append(".".join(part.lower() for part in raw_parts))
    return sorted(set(piece for piece in pieces if len(piece) > 1))


def _split_chinese_segment(segment: str, domain_terms: set[str]) -> list[str]:
    lowered = segment.lower()
    dictionary_terms = _chinese_dictionary(domain_terms)
    tokens = [lowered]
    tokens.extend(_contained_chinese_terms(lowered, dictionary_terms))
    if jieba is not None:
        tokens.extend(_jieba_search_tokens(segment, dictionary_terms))
    else:
        tokens.extend(_fallback_chinese_tokens(lowered, dictionary_terms))
    return _dedupe_tokens(_valid_chinese_token(token) for token in tokens)


def _chinese_dictionary(domain_terms: set[str]) -> set[str]:
    terms = set(_ENGINEERING_CHINESE_TERMS)
    terms.update(term for term in domain_terms if _contains_chinese(term))
    return {term.lower() for term in terms if len(term.strip()) >= _CHINESE_MIN_TOKEN_LENGTH}


def _contained_chinese_terms(text: str, dictionary_terms: set[str]) -> list[str]:
    return sorted(
        (term for term in dictionary_terms if term in text),
        key=lambda value: (-len(value), value),
    )


def _jieba_search_tokens(segment: str, dictionary_terms: set[str]) -> list[str]:
    assert jieba is not None
    _register_jieba_terms(dictionary_terms)
    return [
        token.strip().lower()
        for token in jieba.cut_for_search(segment, HMM=True)
        if token.strip()
    ]


def _register_jieba_terms(dictionary_terms: set[str]) -> None:
    assert jieba is not None
    missing_terms = dictionary_terms - _JIEBA_REGISTERED_TERMS
    if not missing_terms:
        return
    with _JIEBA_LOCK:
        for term in sorted(missing_terms, key=lambda value: (-len(value), value)):
            if term not in _JIEBA_REGISTERED_TERMS:
                jieba.add_word(term, freq=2_000_000)
                _JIEBA_REGISTERED_TERMS.add(term)


def _fallback_chinese_tokens(text: str, dictionary_terms: set[str]) -> list[str]:
    # 没有第三方分词器时，先做领域词最长匹配；未知片段再用 2-4 gram 保底。
    tokens: list[str] = []
    index = 0
    while index < len(text):
        matched = _longest_dictionary_match(text, index, dictionary_terms)
        if matched is not None:
            tokens.append(matched)
            index += len(matched)
            continue

        start = index
        index += 1
        while index < len(text) and _longest_dictionary_match(text, index, dictionary_terms) is None:
            index += 1
        tokens.extend(_fallback_ngrams(text[start:index]))
    return tokens


def _longest_dictionary_match(
    text: str,
    index: int,
    dictionary_terms: set[str],
) -> str | None:
    matches = [term for term in dictionary_terms if text.startswith(term, index)]
    if not matches:
        return None
    return max(matches, key=len)


def _fallback_ngrams(text: str) -> list[str]:
    if len(text) < _CHINESE_MIN_TOKEN_LENGTH:
        return []
    tokens: list[str] = []
    max_length = min(_CHINESE_MAX_FALLBACK_NGRAM, len(text))
    for size in range(max_length, _CHINESE_MIN_TOKEN_LENGTH - 1, -1):
        tokens.extend(text[index : index + size] for index in range(len(text) - size + 1))
    return tokens


def _valid_chinese_token(token: str) -> str | None:
    stripped = token.strip().lower()
    if len(stripped) < _CHINESE_MIN_TOKEN_LENGTH:
        return None
    if stripped in _CHINESE_STOPWORDS:
        return None
    if not _contains_chinese(stripped):
        return None
    return stripped


def _dedupe_tokens(tokens: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for token in tokens:
        if token is None or token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def _tokenize_domain_term(term: str) -> list[str]:
    if _contains_chinese(term):
        return _split_chinese_segment(term, {term})
    return _split_engineering_token(term)


def _symbol_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for match in _ASCII_TOKEN_RE.finditer(text):
        token = match.group(0).strip()
        if len(token) <= 1:
            continue
        terms.add(token)
        terms.add(token.lower())
        terms.update(_split_engineering_token(token))
    return terms


def _contains_chinese(text: str) -> bool:
    return bool(_CHINESE_SEGMENT_RE.search(text))
