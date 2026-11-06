import ast
from pathlib import Path


def test_dependency_direction():
    root = Path(__file__).parents[1] / 'urbex'
    for layer in ('domain', 'application', 'presentation'):
        for path in (root / layer).rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                imports = [node.module or ''] if isinstance(node, ast.ImportFrom) else [n.name for n in node.names] if isinstance(node, ast.Import) else []
                for module in imports:
                    forbidden = ['sqlalchemy', 'urbex.infrastructure', 'urbex.bootstrap']
                    if layer in ('domain', 'application'):
                        forbidden += ['fastapi', 'urbex.presentation']
                    assert not any(module == name or module.startswith(name+'.') for name in forbidden), f'{path}: {module}'
