"""Review-location formatting helpers."""

def location_label(start: int | None, end: int | None = None) -> str:
    if start is None:
        return "Location unavailable"
    if end is None or end == start:
        return f"Line {start}"
    return f"Lines {start}–{end}"
