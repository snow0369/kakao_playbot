def _norm(s: str) -> str:
    return (s or "").replace("\r\n", "\n").strip()
