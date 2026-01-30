import re
import datetime as dt
import pandas as pd

# ---------- (A-2) 내보내기(export) 포맷 ----------
# 예:
# --------------- 2026년 1월 8일 목요일 ---------------
# [플레이봇] [오후 3:41] ...
# (메시지 본문 여러 줄)
# [이권학] [오후 3:41] ...

PC_EXPORT_DAY_RE = re.compile(
    r"^-{3,}\s*(?P<y>\d{4})년\s*(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일.*?-{3,}\s*$",
    re.M
)

PC_EXPORT_MSG_RE = re.compile(
    r"^\[(?P<sender>[^\]]+)\]\s*\[(?P<ampm>오전|오후)\s*(?P<time>\d{1,2}:\d{2})\]\s*(?P<first>.*)$",
    re.M
)

PC_EXPORT_SAVED_AT_RE = re.compile(
    r"^저장한 날짜\s*:\s*(?P<iso>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*$",
    re.M
)


def _parse_korean_ampm_dt(date_: dt.date, ampm: str, time_str: str) -> dt.datetime:
    hh, mm = map(int, time_str.split(":"))
    if ampm == "오후" and hh != 12:
        hh += 12
    if ampm == "오전" and hh == 12:
        hh = 0
    return dt.datetime(date_.year, date_.month, date_.day, hh, mm)


def parse_pc_export_format(text: str, prev_seq: int = 0) -> pd.DataFrame:
    """
    PC 내보내기 텍스트를 (dt, seq, sender, content) DataFrame으로 변환.
    - 날짜 구분선(---- 2026년 1월 8일 ----)로 현재 날짜 컨텍스트를 설정
    - [보낸이] [오전/오후 HH:MM] 로 시작하는 라인을 메시지 헤더로 간주
    - 헤더 이후 다음 메시지 헤더/날짜 구분선 전까지를 본문으로 합침
    - 시간정보 없는 시스템 라인(예: "이권학님이 ... 추가했습니다.")도 날짜 컨텍스트 하에서 레코드로 포함
      (sender="SYSTEM", dt=해당 날짜 00:00, content=해당 블록)
    """
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")

    msgs = []
    seq = prev_seq

    current_date: dt.date | None = None

    # 현재 누적 중인 레코드
    cur_sender: str | None = None
    cur_dt: dt.datetime | None = None
    cur_buf: list[str] = []
    cur_is_system = False

    def flush():
        nonlocal seq, cur_sender, cur_dt, cur_buf, cur_is_system
        if cur_sender is None or cur_dt is None:
            cur_sender, cur_dt, cur_buf, cur_is_system = None, None, [], False
            return
        content = "\n".join(cur_buf).strip("\n")
        if content.strip() == "":
            cur_sender, cur_dt, cur_buf, cur_is_system = None, None, [], False
            return
        msgs.append({"dt": cur_dt, "seq": seq, "sender": cur_sender, "content": content})
        seq += 1
        cur_sender, cur_dt, cur_buf, cur_is_system = None, None, [], False

    # PC 파일 헤더(대화상대 없음..., 저장한 날짜...)는 무시하되,
    # "저장한 날짜"는 파싱에 필요하면 활용 가능. 여기서는 단순 무시.
    # saved_at = None
    # m_saved = PC_EXPORT_SAVED_AT_RE.search(text)
    # if m_saved:
    #     saved_at = dt.datetime.fromisoformat(m_saved.group("iso"))

    for raw in lines:
        line = raw.rstrip("\n")

        # 날짜 구분선
        m_day = PC_EXPORT_DAY_RE.match(line.strip())
        if m_day:
            flush()
            y = int(m_day.group("y"))
            m = int(m_day.group("m"))
            d = int(m_day.group("d"))
            current_date = dt.date(y, m, d)
            continue

        # 메시지 헤더
        m_msg = PC_EXPORT_MSG_RE.match(line)
        if m_msg:
            flush()
            if current_date is None:
                raise ValueError("PC 포맷 파싱 실패: 날짜 헤더를 찾지 못했습니다.")

            sender = m_msg.group("sender").strip()
            ampm = m_msg.group("ampm")
            tstr = m_msg.group("time")
            first = m_msg.group("first")

            cur_sender = sender
            cur_dt = _parse_korean_ampm_dt(current_date, ampm, tstr)
            cur_buf = [first] if first is not None else [""]
            cur_is_system = False
            continue

        # 그 외 라인(본문 누적 / 시스템 블록)
        if cur_sender is not None:
            # 메시지 본문 누적
            cur_buf.append(line)
            continue

        # 아직 어떤 메시지도 시작 안 했는데 날짜 컨텍스트 아래에 텍스트가 있다면 시스템 블록으로 취급
        if current_date is not None and line.strip() != "":
            flush()
            cur_sender = "SYSTEM"
            cur_dt = dt.datetime(current_date.year, current_date.month, current_date.day, 0, 0, 0)
            cur_buf = [line]
            cur_is_system = True
            continue

        # 완전 무의미한 공백/헤더 라인들은 그냥 패스
        # (예: 파일 상단 "대화상대 없음..." 등)
        continue

    flush()

    return pd.DataFrame(msgs).sort_values(["dt", "seq"]).reset_index(drop=True)
