"""Load api.py/const.py without Home Assistant (they do not depend on it)."""
import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "mobidziennik"
FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _load():
    pkg = types.ModuleType("mdz")
    pkg.__path__ = [str(ROOT)]
    sys.modules["mdz"] = pkg
    for name in ("const", "api"):
        spec = importlib.util.spec_from_file_location(f"mdz.{name}", ROOT / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"mdz.{name}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["mdz.api"]


api = _load()
