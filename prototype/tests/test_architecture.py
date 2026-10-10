"""Guards the module boundaries.

* A library may import only ``zingly_core`` and itself; it reaches other modules through
  ports it declares. Only the voice_agent service wires libraries together.
* ``zingly_core`` imports no other Zingly module.
* Libraries never import the service, the simulators or a web framework.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBS = sorted(p for p in (ROOT / "libs").iterdir() if (p / "pyproject.toml").exists())
FORBIDDEN = {"voice_agent", "mock_pss", "genesys_sim", "fastapi", "uvicorn"}


def imports(package_dir: Path) -> set[str]:
    found = set()
    for path in package_dir.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                found |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])
    return found


def test_libraries_depend_only_on_core():
    assert len(LIBS) == 9
    for lib in LIBS:
        own = f"zingly_{lib.name}"
        used = imports(lib / "src" / own)
        zingly = {m for m in used if m.startswith("zingly_")} - {own}
        allowed = set() if lib.name == "core" else {"zingly_core"}
        assert zingly <= allowed, f"{own} imports {zingly - allowed}"
        assert not used & FORBIDDEN, f"{own} imports {used & FORBIDDEN}"


def test_every_library_declares_its_dependencies():
    for lib in LIBS:
        text = (lib / "pyproject.toml").read_text()
        if lib.name != "core":
            assert '"zingly-core"' in text, lib.name
