"""Static, best-effort Python repository analysis using only the standard library."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "site-packages",
    "node_modules",
    "build",
    "dist",
}


def _module_name(file_path: Path, root: Path) -> str:
    relative = file_path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or root.name


def _attribute_name(node: ast.AST) -> str:
    """Return the dotted spelling of a Name/Attribute expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _attribute_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


class _DefinitionVisitor(ast.NodeVisitor):
    """Collect definitions and calls, associating calls with their enclosing function."""

    def __init__(self, module: str, relative_file: str) -> None:
        self.module = module
        self.relative_file = relative_file
        self.class_stack: list[str] = []
        self.function_stack: list[str] = []
        self.definitions: list[dict[str, Any]] = []
        self.calls: list[dict[str, str]] = []

    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        parent_parts = [*self.class_stack, *self.function_stack]
        qualified = ".".join([self.module, *parent_parts, node.name])
        kind = "method" if self.class_stack else "function"
        item = {
            "id": qualified,
            "name": node.name,
            "qualified_name": qualified,
            "module": self.module,
            "kind": kind,
            "file": self.relative_file,
            "line": node.lineno,
            "is_async": isinstance(node, ast.AsyncFunctionDef),
        }
        self.definitions.append(item)
        self.function_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        self.function_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        self.class_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if self.function_stack:
            caller = ".".join(
                [self.module, *self.class_stack, *self.function_stack]
            )
            spelling = _attribute_name(node.func)
            if spelling:
                self.calls.append({"caller": caller, "spelling": spelling})
        self.generic_visit(node)


def _import_targets(tree: ast.Module, module: str, is_package_init: bool) -> list[str]:
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = module if is_package_init else module.rpartition(".")[0]
                package_parts = package.split(".") if package else []
                remove_count = node.level - 1
                if remove_count:
                    package_parts = package_parts[: max(0, len(package_parts) - remove_count)]
                base = ".".join(package_parts)
                if node.module:
                    base = f"{base}.{node.module}" if base else node.module
                if base:
                    targets.add(base)
                elif node.module:
                    targets.add(node.module)
            elif node.module:
                targets.add(node.module)
            # For `from package import submodule`, also expose likely submodule edges.
            if node.module:
                targets.update(
                    f"{node.module}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )
    return sorted(targets)


def analyze_repository(root: str | Path) -> dict[str, Any]:
    """Analyze Python files under *root* and return a JSON-serializable graph.

    Call edges are conservative: a bare call resolves first to a same-module
    function, then to a project-wide uniquely named function. Attribute calls
    resolve only when the attribute name has a single project-wide definition.
    Dynamic dispatch and ambiguous calls are intentionally not guessed.
    """
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise ValueError(f"Repository path is not an existing directory: {root_path}")

    python_files = sorted(
        path
        for path in root_path.rglob("*.py")
        if not any(part in IGNORED_DIRS for part in path.relative_to(root_path).parts)
    )

    modules: list[dict[str, Any]] = []
    functions: list[dict[str, Any]] = []
    raw_calls: list[dict[str, str]] = []
    import_edges: set[tuple[str, str]] = set()
    errors: list[dict[str, str]] = []

    for file_path in python_files:
        relative_file = file_path.relative_to(root_path).as_posix()
        module = _module_name(file_path, root_path)
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative_file)
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append(
                {
                    "file": relative_file,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        visitor = _DefinitionVisitor(module, relative_file)
        visitor.visit(tree)
        functions.extend(visitor.definitions)
        raw_calls.extend(visitor.calls)
        modules.append({"name": module, "file": relative_file})
        for target in _import_targets(
            tree, module, file_path.name == "__init__.py"
        ):
            import_edges.add((module, target))

    by_name: dict[str, list[dict[str, Any]]] = {}
    by_module_and_name: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_id = {item["id"]: item for item in functions}
    for item in functions:
        by_name.setdefault(item["name"], []).append(item)
        by_module_and_name.setdefault((item["module"], item["name"]), []).append(item)

    call_edges: set[tuple[str, str]] = set()
    for call in raw_calls:
        caller = call["caller"]
        spelling = call["spelling"]
        caller_item = by_id.get(caller)
        if not caller_item:
            continue
        if "." not in spelling:
            candidates = by_module_and_name.get((caller_item["module"], spelling), [])
            if not candidates:
                candidates = by_name.get(spelling, [])
        else:
            candidates = by_name.get(spelling.rsplit(".", 1)[-1], [])
        if len(candidates) == 1:
            target = candidates[0]["id"]
            call_edges.add((caller, target))

    return {
        "root": str(root_path),
        "modules": modules,
        "functions": functions,
        "call_edges": [
            {"caller": caller, "callee": callee, "kind": "call"}
            for caller, callee in sorted(call_edges)
        ],
        "import_edges": [
            {"source": source, "target": target, "kind": "import"}
            for source, target in sorted(import_edges)
        ],
        "errors": errors,
        "stats": {
            "files_scanned": len(modules) + len(errors),
            "modules": len(modules),
            "functions": len(functions),
            "call_edges": len(call_edges),
            "import_edges": len(import_edges),
            "parse_errors": len(errors),
        },
    }
