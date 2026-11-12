import ast
import sys
from pathlib import Path


def test_inner_layers_do_not_depend_on_frameworks_or_adapters():
    root = Path(__file__).parents[1] / "src" / "ucts"
    for layer in ("domain", "application"):
        for file in (root / layer).glob("*.py"):
            tree = ast.parse(file.read_text())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name.split(".")[0] in sys.stdlib_module_names:
                        continue
                    allowed = (
                        ("ucts.domain",)
                        if layer == "domain"
                        else ("ucts.domain", "ucts.application")
                    )
                    assert name.startswith(allowed), f"{file.name} imports {name}"
