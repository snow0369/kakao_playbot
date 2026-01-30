import re
import datetime as dt
import pandas as pd

# ---------- (A-1) 내보내기(export) 포맷 ----------
# 예: 2026. 1. 9. 오전 3:02, 플레이봇 : @사용자 ...

MOBILE_EXPORT_MSG_RE = re.compile(
    r"^(\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.)\s*(오전|오후)\s*([0-9]{1,2}:[0-9]{2}),\s*([^:]+)\s*:\s*(.*)$",
    re.M
)


def _parse_mobile_export_dt(date_str: str, ampm: str, time_str: str) -> dt.datetime:
    parts = [p.strip() for p in date_str.replace(".", " ").split() if p.strip()]
    y, m, d = map(int, parts[:3])
    hh, mm = map(int, time_str.split(":"))
    if ampm == "오후" and hh != 12:
        hh += 12
    if ampm == "오전" and hh == 12:
        hh = 0
    return dt.datetime(y, m, d, hh, mm)


def parse_mobile_export_format(text: str, prev_seq: int = 0) -> pd.DataFrame:
    text = text.replace("\r\n", "\n")
    matches = list(MOBILE_EXPORT_MSG_RE.finditer(text))
    msgs = []

    for i, m in enumerate(matches):
        seq = prev_seq + i

        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        date_str, ampm, tstr = m.group(1), m.group(2), m.group(3)
        sender = m.group(4).strip()
        first_line = m.group(5)

        body = text[m.end():end].strip("\n")
        content = (first_line + ("\n" + body if body else "")).strip()

        msgs.append({
            "dt": _parse_mobile_export_dt(date_str, ampm, tstr),
            "seq": seq,
            "sender": sender,
            "content": content,
        })

    return pd.DataFrame(msgs).sort_values(["dt", "seq"]).reset_index(drop=True)
