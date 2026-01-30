import datetime
import os
import re
from pathlib import Path
from typing import Tuple, List, Optional

import pandas as pd

from playbot.parse import parse_kakao
from playbot.types import TimestampT

FILENAME_MOBILE_RE = re.compile(
    r"^Talk_(?P<dt>\d{4}\.\d{1,2}\.\d{1,2}\s+\d{1,2}_\d{2})-(?P<seq>\d+)\.txt$"
)
FILENAME_PC_RE = re.compile(
    r"^KakaoTalk_"
    r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})_"
    r"(?P<hour>\d{2})(?P<minute>\d{2})_"
    r"(?P<second>\d{2})_(?P<msec>\d{3})"
    r"(?:_.*)?\.txt$"
)


def _mobile_dt_key(dt: str) -> Tuple[int, int, int, int, int]:
    """
    dt like '2026.1.30 18_51' -> (2026, 1, 30, 18, 51)
    """
    # split "YYYY.M.D HH_MM"
    date_s, time_s = dt.split()
    y, mo, d = map(int, date_s.split("."))
    h, mi = map(int, time_s.split("_"))
    return (y, mo, d, h, mi)


def _pc_dt_key(m: re.Match) -> Tuple[int, int, int, int, int, int, int]:
    """
    from named groups -> (Y, M, D, h, m, s, ms)
    """
    return (
        int(m.group("year")),
        int(m.group("month")),
        int(m.group("day")),
        int(m.group("hour")),
        int(m.group("minute")),
        int(m.group("second")),
        int(m.group("msec")),
    )


def collect_and_validate_files(chat_log_path) -> List[str]:
    """
    Accepts both:
      - Mobile export: multiple Talk_...-<seq>.txt files (pick the most recent dt group, then sort by seq)
      - PC export: single KakaoTalk_YYYYMMDD_HHMM_SS_mmm*.txt file (pick the most recent if multiple exist)

    Rule:
      - If multiple distinct datetimes exist (either format), choose the MOST RECENT datetime set.
      - For mobile: return all parts for that most recent dt, sorted by seq.
      - For PC: return the single most recent file (if multiple PC files).
    """
    folder = Path(chat_log_path)

    mobile_records: List[Tuple[Tuple[int, int, int, int, int], str, int, str]] = []
    # (dt_key, dt_str, seq, filename)

    pc_records: List[Tuple[Tuple[int, int, int, int, int, int, int], str]] = []
    # (dt_key, filename)

    for p in folder.iterdir():
        if not p.is_file():
            continue

        name = p.name

        mm = FILENAME_MOBILE_RE.match(name)
        if mm:
            dt_str = mm.group("dt")
            seq = int(mm.group("seq"))
            dt_key = _mobile_dt_key(dt_str)
            mobile_records.append((dt_key, dt_str, seq, name))
            continue

        mp = FILENAME_PC_RE.match(name)
        if mp:
            dt_key = _pc_dt_key(mp)
            pc_records.append((dt_key, name))
            continue

        # ignore unrelated files

    if not mobile_records and not pc_records:
        return []

    # Pick most recent datetime across both formats
    # (mobile dt_key has 5 fields; pc dt_key has 7 fields) -> compare by normalizing to 7 fields
    def mobile_key_to_7(k5: Tuple[int, int, int, int, int]) -> Tuple[int, int, int, int, int, int, int]:
        y, mo, d, h, mi = k5
        return (y, mo, d, h, mi, 0, 0)

    latest_mobile_dt7: Optional[Tuple[int, int, int, int, int, int, int]] = None
    latest_mobile_dt_str: Optional[str] = None
    if mobile_records:
        # choose most recent dt among mobile sets
        dt5_max, dt_str_max = max({(dt_key, dt_str) for dt_key, dt_str, _, _ in mobile_records},
                                  key=lambda x: x[0])
        latest_mobile_dt7 = mobile_key_to_7(dt5_max)
        latest_mobile_dt_str = dt_str_max

    latest_pc_dt7: Optional[Tuple[int, int, int, int, int, int, int]] = None
    latest_pc_name: Optional[str] = None
    if pc_records:
        latest_pc_dt7, latest_pc_name = max(pc_records, key=lambda x: x[0])

    # Decide which export to use by most recent datetime
    use_pc = False
    if latest_pc_dt7 is not None and (latest_mobile_dt7 is None or latest_pc_dt7 >= latest_mobile_dt7):
        use_pc = True

    if use_pc:
        # PC export: single file (most recent)
        return [os.path.join(chat_log_path, latest_pc_name)]  # type: ignore[arg-type]

    # Mobile export: collect all parts for the most recent dt_str, sort by seq
    assert latest_mobile_dt_str is not None
    selected = [(seq, name) for _, dt_str, seq, name in mobile_records if dt_str == latest_mobile_dt_str]
    selected.sort(key=lambda x: x[0])
    return [os.path.join(chat_log_path, name) for _, name in selected]


def load_chat_log(
    chat_log_path: str,
    start_time: Optional[TimestampT] = None,
    end_time: Optional[TimestampT] = None,
    prev_seq: int = 0,
):
    dfs = []
    chat_files = collect_and_validate_files(chat_log_path)
    if not chat_files:
        raise ValueError("No chat files found.")

    for fname in chat_files:
        with open(fname, "r", encoding="utf-8") as f:
            plain_text = f.read()

        kakao_chat = parse_kakao(plain_text, prev_seq)
        dfs.append(kakao_chat)

        if not kakao_chat.empty:
            prev_seq = int(kakao_chat["seq"].iloc[-1]) + 1

    all_chat = pd.concat(dfs, ignore_index=True)
    if all_chat.empty:
        raise ValueError("Parsed chat DataFrame is empty.")

    if "dt" not in all_chat.columns:
        raise ValueError("parse_kakao output must contain 'dt' column.")

    # Convert once: pandas → python datetime
    all_chat["dt"] = pd.to_datetime(all_chat["dt"], errors="raise")
    all_chat["dt"] = all_chat["dt"].apply(
        lambda x: x.to_pydatetime()
    )

    # ---- Time filtering (drop rows in window) ----
    if start_time is not None and end_time is not None:
        in_window = (all_chat["dt"] >= start_time) & (all_chat["dt"] <= end_time)
        all_chat = all_chat.loc[~in_window].copy()

    elif start_time is not None:
        all_chat = all_chat.loc[all_chat["dt"] < start_time].copy()

    elif end_time is not None:
        all_chat = all_chat.loc[all_chat["dt"] > end_time].copy()

    return all_chat
