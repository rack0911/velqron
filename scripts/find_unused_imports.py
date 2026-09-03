import ast
import os
import sys


def get_unused_imports(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    imported_names = {}
    used_names = set()

    class ImportVisitor(ast.NodeVisitor):
        def visit_Import(self, node):
            for alias in node.names:
                name = alias.asname or alias.name
                imported_names[name] = (node.lineno, name)
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            for alias in node.names:
                name = alias.asname or alias.name
                imported_names[name] = (node.lineno, name)
            self.generic_visit(node)

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load):
                used_names.add(node.id)
            self.generic_visit(node)

    ImportVisitor().visit(tree)

    unused = []
    for name, (line, display_name) in imported_names.items():
        if name not in used_names:
            unused.append((line, display_name))
    return unused


def main():
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    has_unused = False

    # We only enforce code health inside the src/ core directory
    src_dir = os.path.join(target_dir, "src")
    if not os.path.exists(src_dir):
        src_dir = target_dir

    for root, _, files in os.walk(src_dir):
        if "venv" in root or ".git" in root or ".pytest_cache" in root or "__pycache__" in root:
            continue
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                unused = get_unused_imports(path)
                if unused:
                    print(f"File: {path}")
                    for line, name in sorted(unused):
                        print(f"  Line {line}: Unused import '{name}'")
                    has_unused = True

    if has_unused:
        print("\n[ERROR] Unused imports found in core source directory. Please clean them up.")
        sys.exit(1)
    else:
        print("[SUCCESS] No unused imports found in core source directory.")
        sys.exit(0)


if __name__ == "__main__":
    main()
