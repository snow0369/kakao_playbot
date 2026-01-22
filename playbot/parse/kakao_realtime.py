import re
import datetime as dt
import pandas as pd


# ---------- (B) 실시간 Ctrl+A 복사(copy) 포맷 ----------
# 날짜 헤더 예: 2026년 1월 10일 토요일
COPY_DATE_RE = re.compile(r"^(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s+\S+$", re.M)

# 메시지 헤더 예: [플레이봇] [오후 10:44] ...
COPY_MSG_RE = re.compile(
    r"^\[([^\]]+)\]\s*\[(오전|오후)\s*([0-9]{1,2}:[0-9]{2})\]\s*(.*)$",
    re.M
)


def _parse_copy_dt(current_date: dt.date, ampm: str, time_str: str) -> dt.datetime:
    hh, mm = map(int, time_str.split(":"))
    if ampm == "오후" and hh != 12:
        hh += 12
    if ampm == "오전" and hh == 12:
        hh = 0
    return dt.datetime(current_date.year, current_date.month, current_date.day, hh, mm)


def parse_copy_format(text: str, prev_seq: int = 0) -> pd.DataFrame:
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")

    current_date = None
    msgs = []
    seq = prev_seq   # ← 시작값 변경
    i = 0

    def flush_msg(sender, dt_val, content_lines, seq_val):
        content = "\n".join(content_lines).strip()
        msgs.append({
            "dt": dt_val,
            "seq": seq_val,
            "sender": sender,
            "content": content
        })

    while i < len(lines):
        line = lines[i].rstrip("\n")

        md = COPY_DATE_RE.match(line.strip())
        if md:
            y, m, d = int(md.group(1)), int(md.group(2)), int(md.group(3))
            current_date = dt.date(y, m, d)
            i += 1
            continue

        mh = COPY_MSG_RE.match(line)
        if mh:
            if current_date is None:
                raise ValueError("copy 포맷 파싱 실패: 날짜 헤더를 찾지 못했습니다.")

            sender = mh.group(1).strip()
            ampm = mh.group(2)
            tstr = mh.group(3)
            first = mh.group(4)

            dt_val = _parse_copy_dt(current_date, ampm, tstr)
            content_lines = [first] if first else []

            i += 1
            while i < len(lines):
                nxt = lines[i]
                if COPY_DATE_RE.match(nxt.strip()) or COPY_MSG_RE.match(nxt):
                    break
                content_lines.append(nxt)
                i += 1

            flush_msg(sender, dt_val, content_lines, seq)
            seq += 1
            continue

        i += 1

    return pd.DataFrame(msgs).sort_values(["dt", "seq"]).reset_index(drop=True)
