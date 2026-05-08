"""Simple zero-padded integer positions for MVP ordering.

Spaced by 10 to leave room for inserts. When a slot is too tight to bisect,
upgrade to a fractional-indexing scheme (Phase 6 if needed).
"""

POSITION_WIDTH = 6
STEP = 10


def _format(value: int) -> str:
    return str(value).zfill(POSITION_WIDTH)


def append_position(existing: list[str]) -> str:
    if not existing:
        return _format(STEP)
    last = max(int(p) for p in existing)
    return _format(last + STEP)


def midpoint(before: str | None, after: str | None) -> str:
    lo = int(before) if before is not None else 0
    if after is None:
        return _format(lo + STEP)
    hi = int(after)
    if hi - lo <= 1:
        raise ValueError("No room between positions; rebalance required")
    return _format((lo + hi) // 2)
