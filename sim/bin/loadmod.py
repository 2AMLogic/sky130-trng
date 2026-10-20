"""Load a Python source file as a module by path (stdlib only).

Many sim scripts have hyphenated filenames (``fv-cosim.py``,
``make-requests.py``) and cannot be imported normally. Scripts that need one
put ``sim/bin`` on ``sys.path`` (as they already do for ``evidence_record``)
and call :func:`load_module`.
"""

from __future__ import annotations

import importlib.util
import sys


def load_module(name, path, register=False):
    """Import the file at ``path`` as a module called ``name`` and return it.

    ``register=True`` also records it in ``sys.modules`` before executing it,
    which dataclass/pickle-style users of the loaded module need; it is off by
    default so loading never shadows another module of the same name.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
