from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

import sqlglot
import tree_sitter_java
from markdown_it import MarkdownIt
from sqlglot import exp
from tree_sitter import Language, Node, Parser

from agent_context_platform.models import (
    AssetType,
    IndexedItem,
    SourceCitation,
    SourceType,
    SymbolCatalogEntry,
)


_JAVA_LANGUAGE = Language(tree_sitter_java.language())
_JAVA_PARSER = Parser(_JAVA_LANGUAGE)
_JAVA_TYPE_NODE_KINDS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "annotation_type_declaration": "annotation_type",
}


def index_java_source(path: str, content: str, repo: str | None = None) -> list[IndexedItem]:
    # 这里是 Java 离线索引的最小边界：调用方负责读取文件，本函数只把单个文件解析成可检索资产。
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
        # class 自身作为一个 IndexedItem，后续可按 symbol_type=class 做结构化过滤。
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
        # method 作为独立资产入库，避免检索结果只能定位到整类而不能定位到具体实现片段。
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


def index_java_symbols(
    path: str,
    content: str,
    repo: str | None = None,
    *,
    indexed_items: list[IndexedItem] | None = None,
) -> list[SymbolCatalogEntry]:
    # symbol catalog 只记录声明节点，为后续 code graph 提供稳定节点身份。
    tree = _JAVA_PARSER.parse(content.encode("utf-8"))
    package_name = _java_package_name(tree.root_node)
    item_ids = _source_item_ids_by_symbol(indexed_items or [])
    symbols: list[SymbolCatalogEntry] = []

    for type_node in _walk_nodes(tree.root_node, set(_JAVA_TYPE_NODE_KINDS)):
        name_node = type_node.child_by_field_name("name")
        if name_node is None:
            continue
        type_name = _node_text(name_node)
        kind = _JAVA_TYPE_NODE_KINDS[type_node.type]
        qualified_type_name = _qualified_java_type_name(
            package_name=package_name,
            type_node=type_node,
            type_name=type_name,
        )
        type_source = _source_lines(content, type_node)
        type_item_id = item_ids.get(type_name)
        symbols.append(
            _symbol_entry(
                repo=repo,
                language="java",
                path=path,
                kind=kind,
                name=type_name,
                qualified_name=qualified_type_name,
                source=type_source,
                source_item_id=type_item_id,
            )
        )

        body = type_node.child_by_field_name("body")
        if body is None:
            continue
        for member_node in body.named_children:
            if member_node.type == "method_declaration":
                method_name_node = member_node.child_by_field_name("name")
                if method_name_node is None:
                    continue
                method_name = _node_text(method_name_node)
                parameter_types = _parameter_types(member_node)
                qualified_name = (
                    f"{qualified_type_name}.{method_name}({', '.join(parameter_types)})"
                )
                method_source = _source_lines(content, member_node)
                symbols.append(
                    _symbol_entry(
                        repo=repo,
                        language="java",
                        path=path,
                        kind="method",
                        name=method_name,
                        qualified_name=qualified_name,
                        source=method_source,
                        source_item_id=item_ids.get(f"{type_name}.{method_name}"),
                    )
                )
            elif member_node.type in {"constructor_declaration", "compact_constructor_declaration"}:
                constructor_name = type_name
                name_node = member_node.child_by_field_name("name")
                if name_node is not None:
                    constructor_name = _node_text(name_node)
                parameter_types = _parameter_types(member_node)
                qualified_name = (
                    f"{qualified_type_name}.<init>({', '.join(parameter_types)})"
                )
                constructor_source = _source_lines(content, member_node)
                symbols.append(
                    _symbol_entry(
                        repo=repo,
                        language="java",
                        path=path,
                        kind="constructor",
                        name=constructor_name,
                        qualified_name=qualified_name,
                        source=constructor_source,
                        source_item_id=type_item_id,
                    )
                )
            elif member_node.type == "field_declaration":
                field_source = _source_lines(content, member_node)
                for variable_node in _walk_nodes(member_node, {"variable_declarator"}):
                    field_name_node = variable_node.child_by_field_name("name")
                    if field_name_node is None:
                        continue
                    field_name = _node_text(field_name_node)
                    symbols.append(
                        _symbol_entry(
                            repo=repo,
                            language="java",
                            path=path,
                            kind="field",
                            name=field_name,
                            qualified_name=f"{qualified_type_name}.{field_name}",
                            source=field_source,
                            source_item_id=type_item_id,
                        )
                    )

    return sorted(symbols, key=lambda symbol: (symbol.qualified_name, symbol.kind))


def index_sql_ddl(path: str, content: str, repo: str | None = None) -> list[IndexedItem]:
    # sqlglot 输出 AST 后，再拆成 table/column 两级资产，方便任务只召回相关表或字段。
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


def index_sql_symbols(
    path: str,
    content: str,
    repo: str | None = None,
    *,
    indexed_items: list[IndexedItem] | None = None,
) -> list[SymbolCatalogEntry]:
    expressions = sqlglot.parse(content, read="postgres")
    item_ids = _source_item_ids_by_symbol(indexed_items or [])
    symbols: list[SymbolCatalogEntry] = []
    for expression in expressions:
        if not isinstance(expression, exp.Create) or expression.args.get("kind") != "TABLE":
            continue
        table_name = expression.this.this.name
        symbols.append(
            _symbol_entry(
                repo=repo,
                language="sql",
                path=path,
                kind="table",
                name=table_name,
                qualified_name=table_name,
                source=None,
                source_item_id=item_ids.get(table_name),
            )
        )
        for column in expression.find_all(exp.ColumnDef):
            column_name = column.name
            qualified_name = f"{table_name}.{column_name}"
            symbols.append(
                _symbol_entry(
                    repo=repo,
                    language="sql",
                    path=path,
                    kind="column",
                    name=column_name,
                    qualified_name=qualified_name,
                    source=None,
                    source_item_id=item_ids.get(qualified_name),
                )
            )
    return symbols


def index_markdown_document(
    path: str, content: str, repo: str | None = None
) -> list[IndexedItem]:
    # Markdown 按 heading 切片，而不是整篇入库，避免一个长文档压过真正相关的小节。
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


def _symbol_entry(
    *,
    repo: str | None,
    language: str,
    path: str,
    kind: str,
    name: str,
    qualified_name: str,
    source: _LineSource | None,
    source_item_id: str | None,
) -> SymbolCatalogEntry:
    return SymbolCatalogEntry(
        symbol_id=f"{language}:{kind}:{qualified_name}",
        repo=repo or "",
        path=path,
        language=language,
        kind=kind,
        name=name,
        qualified_name=qualified_name,
        start_line=source.start_line if source is not None else None,
        end_line=source.end_line if source is not None else None,
        source_item_id=source_item_id,
    )


def _walk_nodes(root: Node, node_types: set[str]) -> list[Node]:
    # tree-sitter 的 Node 没有直接按类型查询的高层 API，这里用显式栈保留遍历顺序和可调试性。
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


def _java_package_name(root: Node) -> str | None:
    package_node = next(iter(_walk_nodes(root, {"package_declaration"})), None)
    if package_node is None:
        return None
    scoped_identifier = next(
        (
            child
            for child in package_node.named_children
            if child.type in {"scoped_identifier", "identifier"}
        ),
        None,
    )
    return _node_text(scoped_identifier) if scoped_identifier is not None else None


def _qualified_java_type_name(
    *,
    package_name: str | None,
    type_node: Node,
    type_name: str,
) -> str:
    enclosing_names: list[str] = []
    parent = type_node.parent
    while parent is not None:
        if parent.type in _JAVA_TYPE_NODE_KINDS:
            name_node = parent.child_by_field_name("name")
            if name_node is not None:
                enclosing_names.append(_node_text(name_node))
        parent = parent.parent
    parts = ([package_name] if package_name else []) + list(reversed(enclosing_names)) + [
        type_name
    ]
    return ".".join(parts)


def _parameter_types(node: Node) -> list[str]:
    parameters_node = node.child_by_field_name("parameters")
    if parameters_node is None:
        return []
    parameter_types: list[str] = []
    for parameter_node in parameters_node.named_children:
        if parameter_node.type not in {"formal_parameter", "spread_parameter"}:
            continue
        type_node = parameter_node.child_by_field_name("type")
        if type_node is not None:
            parameter_types.append(_node_text(type_node))
    return parameter_types


def _source_item_ids_by_symbol(items: list[IndexedItem]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for item in items:
        if item.source.symbol:
            ids[item.source.symbol] = item.id
        if item.source.table:
            ids[item.source.table] = item.id
        if item.source.table and item.source.column:
            ids[f"{item.source.table}.{item.source.column}"] = item.id
    return ids


def _annotation_names(node: Node) -> list[str]:
    # 只读取当前节点 modifiers 下的注解，避免 method 注解泄漏到 class 级 metadata。
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
