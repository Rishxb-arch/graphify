# DO NOT import from graphify.extract here — direction is extract.py → extractors/ only.
from __future__ import annotations

from pathlib import Path

from graphify.ids import make_id

# Language built-in globals that AST may classify as call targets when used as
# constructors or coercion functions (e.g. String(x), Number(x), Boolean(x)).
# Without this filter they become god-nodes accumulating spurious edges from
# every call site. Filter applied at same-file and cross-file resolution.
# See issue #726.
_LANGUAGE_BUILTIN_GLOBALS: frozenset[str] = frozenset({
    # JavaScript / TypeScript ECMAScript built-ins
    "String", "Number", "Boolean", "Object", "Array", "Symbol", "BigInt",
    "Date", "RegExp", "Error", "TypeError", "RangeError", "SyntaxError",
    "ReferenceError", "EvalError", "URIError",
    "Promise", "Map", "Set", "WeakMap", "WeakSet", "JSON", "Math",
    "Reflect", "Proxy", "Intl",
    "parseInt", "parseFloat", "isNaN", "isFinite",
    "encodeURIComponent", "decodeURIComponent", "encodeURI", "decodeURI",
    # Browser / Node common globals
    "URL", "URLSearchParams", "FormData", "Blob", "File",
    "Headers", "Request", "Response", "AbortController", "AbortSignal",
    "TextEncoder", "TextDecoder", "console",
    # Python built-in callables
    "str", "int", "float", "bool", "list", "dict", "set", "tuple", "bytes",
    "len", "range", "enumerate", "zip", "map", "filter", "sum", "min", "max",
    "print", "open", "isinstance", "type", "super", "sorted", "reversed",
    "any", "all", "abs", "round", "next", "iter", "hash", "id", "repr",
    "callable", "getattr", "setattr", "hasattr", "delattr", "vars", "dir",
    # Swift standard library / Foundation / SwiftUI (#2147). Value-type
    # initializers (Data(x), Int(x), UUID()) and protocol conformance targets
    # appear from virtually every file of a Swift codebase, exactly like the
    # ECMAScript constructors above. String/Date/URL/Error are already listed.
    "Int", "Int8", "Int16", "Int32", "Int64",
    "UInt", "UInt8", "UInt16", "UInt32", "UInt64",
    "Double", "Float", "Bool", "Character",
    "Sendable", "Codable", "Decodable", "Encodable", "Equatable", "Hashable",
    "Identifiable", "Comparable", "CaseIterable", "RawRepresentable",
    "CustomStringConvertible", "CustomDebugStringConvertible", "AnyObject",
    "LocalizedError",
    "Data", "UUID", "Decimal", "Calendar", "Locale", "TimeZone", "Bundle",
    "IndexPath", "IndexSet", "NotificationCenter", "UserDefaults",
    "FileManager", "URLSession", "URLRequest", "URLComponents",
    "JSONDecoder", "JSONEncoder", "DateFormatter", "NumberFormatter",
    "ISO8601DateFormatter",
    "NSObject", "NSString", "NSError", "NSLock", "NSAttributedString",
    "DispatchQueue", "DispatchGroup", "OperationQueue", "RunLoop",
    "View", "Color", "Font",
})


def _make_id(*parts: str) -> str:
    return make_id(*parts)


def _file_stem(path: Path) -> str:
    """Stem used as the node-ID prefix for a file and its symbols.

    The full path (extension dropped) is preserved as path segments; ``make_id``
    later collapses the separators to underscores. Using every segment — not just
    the immediate parent dir (#1504) — means same-named files in different
    directories get distinct IDs instead of colliding into one
    last-writer-wins node:

        docs/v1/api/README.md -> docs/v1/api/README -> docs_v1_api_readme
        docs/v2/api/README.md -> docs/v2/api/README -> docs_v2_api_readme

    Top-level files keep a bare stem (``setup.py`` -> ``setup``). When passed an
    absolute path the whole path is encoded; the extract() id-remap post-pass
    re-derives the canonical repo-relative form from ``source_file`` so the on-disk
    location can't leak into the persisted IDs (#502).

    Returns "" for a path with no name (``Path('.')`` — a source_file that equals
    the scan root, so it has no per-file stem). Guarding here keeps
    ``path.with_suffix("")`` from raising ``ValueError: '.' has an empty name`` and
    protects every caller, not just ``_semantic_id_remap`` (#1618)."""
    if not path.name:
        return ""
    return path.with_suffix("").as_posix()


def _read_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def callable_label_name(label: str) -> str:
    """Bare name of a function or method label (``.bark()`` / ``bark()`` -> ``bark``)."""
    return str(label).strip("()").lstrip(".")


def index_methods_by_class(
    nodes: list,
    edges: list,
) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """Index ``method`` edges the extractor has already emitted.

    Returns ``(method_nid -> class_nid, (class_nid, method_name) -> method_nid)``.
    A repeated name on one class keeps the last edge, which is the same
    last-definition rule the file-wide label map used *within* a single class.
    """
    by_id = {
        n.get("id"): n for n in nodes if isinstance(n, dict) and n.get("id")
    }
    owner: dict[str, str] = {}
    by_class: dict[tuple[str, str], str] = {}
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("relation") != "method":
            continue
        src, tgt = edge.get("source"), edge.get("target")
        if not src or not tgt:
            continue
        owner[str(tgt)] = str(src)
        node = by_id.get(tgt)
        if node is None:
            continue
        name = callable_label_name(str(node.get("label", "")))
        if name:
            by_class[(str(src), name)] = str(tgt)
    return owner, by_class


def resolve_own_class_method(
    caller_nid: str,
    callee_name: str,
    method_owner: dict[str, str],
    methods_by_class: dict[tuple[str, str], str],
    unscoped: str | None,
) -> tuple[bool, str | None]:
    """Bind a same-class call using ``method`` edges, not the file-wide name map.

    When ``caller_nid`` is a method of class C, the callee resolves to C's own
    method of that name. If C does not define it, a file-wide hit that belongs
    to a *different* class is dropped (``None``) rather than used. A hit that
    is not a method — a module-level function — is kept.

    ``(False, None)`` means the caller is not a method; keep the unscoped lookup.
    """
    owner = method_owner.get(caller_nid)
    if not owner:
        return False, None
    own = methods_by_class.get((owner, callee_name))
    if own:
        return True, own
    if unscoped:
        other = method_owner.get(unscoped)
        if other is not None and other != owner:
            return True, None
    return True, unscoped
