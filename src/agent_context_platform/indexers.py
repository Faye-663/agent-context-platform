from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

import sqlglot
import tree_sitter_java
from markdown_it import MarkdownIt
from sqlglot import exp
from tree_sitter import Language, Node, Parser

from agent_context_platform.models import AssetType, IndexedItem, SourceCitation, SourceType


_JAVA_LANGUAGE = Language(tree_sitter_java.language())
_JAVA_PARSER = Parser(_JAVA_LANGUAGE)


def index_java_source(path: str, content: str, repo: str | None = None) -> list[IndexedItem]:
    tree = _JAVA_PARSER.parse(content.encode("utf-8"))
    items: list[IndexedItem] = []
    for class_node in _walk_nodes(tree.root_node, {"class_declaration"}):
        class_name_node = class_node.child_by_field_name("name")
        if class_name_node is None:
            continue

        class_name = _node_text(class_name_node)
        class_source = _source_lines(content, class_node)
        class_annotations = _annotation_names(class_node)
        class_signature = _signature_text(class_node)
        items.append(
            _indexed_item(
                item_id=f"code:{path}:{class_name}",
                asset_type=AssetType.CODE,
                title=class_name,
                content=class_source.text,
                summary=f"Java 类 {class_name}。",
                metadata={
                    "language": "java",
                    "symbol_type": "class",
                    "annotations": class_annotations,
                    "signature": class_signature,
                },
                source=SourceCitation(
                    source_type=SourceType.CODE,
                    repo=repo,
                    path=path,
                    start_line=class_source.start_line,
                    end_line=class_source.end_line,
                    symbol=class_name,
                ),
            )
        )

        class_body = class_node.child_by_field_name("body")
        if class_body is None:
            continue
        for method_node in _walk_nodes(class_body, {"method_declaration"}):
            method_name_node = method_node.child_by_field_name("name")
            if method_name_node is None:
                continue
            method_name = _node_text(method_name_node)
            symbol = f"{class_name}.{method_name}"
            method_source = _source_lines(content, method_node)
            items.append(
                _indexed_item(
                    item_id=f"code:{path}:{symbol}",
                    asset_type=AssetType.CODE,
                    title=symbol,
                    content=method_source.text,
                    summary=f"Java 方法 {symbol}。",
                    metadata={
                        "language": "java",
                        "symbol_type": "method",
                        "annotations": _annotation_names(method_node),
                        "signature": _signature_text(method_node),
                    },
                    source=SourceCitation(
                        source_type=SourceType.CODE,
                        repo=repo,
                        path=path,
                        start_line=method_source.start_line,
                        end_line=method_source.end_line,
                        symbol=symbol,
                    ),
                )
            )
    return items


def index_sql_ddl(path: str, content: str, repo: str | None = None) -> list[IndexedItem]:
    expressions = sqlglot.parse(content, read="postgres")
    indexes_by_table = _collect_sql_indexes(expressions)
    items: list[IndexedItem] = []

    for expression in expressions:
        if not isinstance(expression, exp.Create) or expression.args.get("kind") != "TABLE":
            continue

        table_name = expression.this.this.name
        column_defs = list(expression.find_all(exp.ColumnDef))
        column_names = [column.name for column in column_defs]
        indexes = indexes_by_table[table_name]
        table_source = SourceCitation(
            source_type=SourceType.DB_SCHEMA,
            repo=repo,
            path=path,
            table=table_name,
        )
        items.append(
            _indexed_item(
                item_id=f"db_schema:{path}:{table_name}",
                asset_type=AssetType.DB_SCHEMA,
                title=table_name,
                content=expression.sql(dialect="postgres"),
                summary=f"数据库表 {table_name}。",
                metadata={
                    "symbol_type": "table",
                    "table": table_name,
                    "columns": column_names,
                    "indexes": indexes,
                },
                source=table_source,
            )
        )

        for column in column_defs:
            column_name = column.name
            data_type = column.args["kind"].sql(dialect="postgres")
            items.append(
                _indexed_item(
                    item_id=f"db_schema:{path}:{table_name}.{column_name}",
                    asset_type=AssetType.DB_SCHEMA,
                    title=f"{table_name}.{column_name}",
                    content=column.sql(dialect="postgres"),
                    summary=f"数据库字段 {table_name}.{column_name}。",
                    metadata={
                        "symbol_type": "column",
                        "table": table_name,
                        "column": column_name,
                        "data_type": data_type,
                    },
                    source=SourceCitation(
                        source_type=SourceType.DB_SCHEMA,
                        repo=repo,
                        path=path,
                        table=table_name,
                        column=column_name,
                    ),
                )
            )

    return items


def index_markdown_document(
    path: str, content: str, repo: str | None = None
) -> list[IndexedItem]:
    tokens = MarkdownIt().parse(content)
    lines = content.splitlines()
    headings = _markdown_headings(tokens)
    items: list[IndexedItem] = []
    title_stack: dict[int, str] = {}

    for index, heading in enumerate(headings):
        title_stack = {
            level: title for level, title in title_stack.items() if level < heading.level
        }
        title_stack[heading.level] = heading.title
        heading_path = " > ".join(title_stack[level] for level in sorted(title_stack))
        end_line = _markdown_section_end_line(lines, headings, index)
        section_text = "\n".join(lines[heading.start_line - 1 : end_line]).strip()
        items.append(
            _indexed_item(
                item_id=f"doc:{path}:{heading_path}",
                asset_type=AssetType.DOC,
                title=heading.title,
                content=section_text,
                summary=f"文档章节 {heading_path}。",
                metadata={
                    "heading_path": heading_path,
                    "heading_level": heading.level,
                },
                source=SourceCitation(
                    source_type=SourceType.DOC,
                    repo=repo,
                    path=path,
                    start_line=heading.start_line,
                    end_line=end_line,
                    heading_path=heading_path,
                ),
            )
        )

    return items


@dataclass(frozen=True)
class _LineSource:
    start_line: int
    end_line: int
    text: str


@dataclass(frozen=True)
class _MarkdownHeading:
    level: int
    title: str
    start_line: int


def _indexed_item(
    *,
    item_id: str,
    asset_type: AssetType,
    title: str,
    content: str,
    summary: str,
    metadata: dict[str, object],
    source: SourceCitation,
) -> IndexedItem:
    return IndexedItem(
        id=item_id,
        asset_type=asset_type,
        title=title,
        content=content,
        summary=summary,
        metadata=metadata,
        source=source,
    )


def _walk_nodes(root: Node, node_types: set[str]) -> list[Node]:
    found: list[Node] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in node_types:
            found.append(node)
        stack.extend(reversed(node.children))
    return found


def _node_text(node: Node) -> str:
    return node.text.decode("utf-8")


def _source_lines(content: str, node: Node) -> _LineSource:
    lines = content.splitlines()
    start_line = node.start_point.row + 1
    end_line = node.end_point.row + 1
    text = "\n".join(lines[start_line - 1 : end_line]).strip()
    return _LineSource(start_line=start_line, end_line=end_line, text=text)


def _annotation_names(node: Node) -> list[str]:
    modifiers = next((child for child in node.children if child.type == "modifiers"), None)
    if modifiers is None:
        return []

    annotations: list[str] = []
    for annotation in _walk_nodes(modifiers, {"annotation", "marker_annotation"}):
        name_node = annotation.child_by_field_name("name")
        if name_node is not None:
            annotations.append(_node_text(name_node))
    return annotations


def _signature_text(node: Node) -> str:
    raw = _node_text(node).split("{", maxsplit=1)[0].strip()
    lines = [line.strip() for line in raw.splitlines() if not line.strip().startswith("@")]
    # signature 用于检索和展示，压缩空白可以避免源文件换行风格影响索引稳定性。
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _collect_sql_indexes(expressions: list[exp.Expression]) -> dict[str, list[str]]:
    indexes_by_table: dict[str, list[str]] = defaultdict(list)
    for expression in expressions:
        if not isinstance(expression, exp.Create) or expression.args.get("kind") != "INDEX":
            continue
        index = expression.this
        indexes_by_table[index.args["table"].name].append(index.name)
    return indexes_by_table


def _markdown_headings(tokens: list[object]) -> list[_MarkdownHeading]:
    headings: list[_MarkdownHeading] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.map is None:
            continue
        inline = tokens[index + 1]
        level = int(token.tag.removeprefix("h"))
        headings.append(
            _MarkdownHeading(
                level=level,
                title=inline.content,
                start_line=token.map[0] + 1,
            )
        )
    return headings


def _markdown_section_end_line(
    lines: list[str], headings: list[_MarkdownHeading], heading_index: int
) -> int:
    if heading_index + 1 < len(headings):
        end_line = headings[heading_index + 1].start_line - 2
    else:
        end_line = len(lines)

    start_line = headings[heading_index].start_line
    while end_line > start_line and not lines[end_line - 1].strip():
        end_line -= 1
    return max(start_line, end_line)
