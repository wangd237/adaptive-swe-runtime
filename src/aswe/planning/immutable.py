"""Deeply immutable JSON-like authority payloads, without schema duplication.

Only compiler-owned mapping/list payloads cross this trust boundary. Pydantic
frozen=True alone prevents attribute reassignment, not nested dict mutation.
"""
from __future__ import annotations
from typing import Any

class FrozenDict(dict):
    def _deny(self, *_args, **_kwargs):
        raise TypeError("compiled authority payload is deeply immutable")
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _deny
    def __ior__(self, value):
        self._deny(value)

def deep_freeze(value:Any)->Any:
    if isinstance(value,dict):
        # Use dict.__init__ during construction; never mutate after exposure.
        return FrozenDict({deep_freeze(k):deep_freeze(v) for k,v in value.items()})
    if isinstance(value,(tuple,list)):
        return tuple(deep_freeze(x) for x in value)
    if isinstance(value,(set,frozenset)):
        return frozenset(deep_freeze(x) for x in value)
    return value
