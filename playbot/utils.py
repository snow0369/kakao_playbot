def _norm(s: str) -> str:
    return (s or "").replace("\r\n", "\n").strip()


def _to_int(s: str) -> int:
    return int(s.replace(",", "").strip())