import re
from pathlib import Path
from typing import List

import pandas as pd

from config import load_username
from parse import parse_kakao, extract_triplets
from statistics import load_dictionary, RawData, add_to_statistics, save_dictionary

# =========================
# Settings
# =========================
PATH_EXPORTED_CHAT = "chat_log/"
USER_NAME = load_username()
BOT_SENDER_NAME = "플레이봇"  # 복사 텍스트에서 [플레이봇] 형태로 나타나는 발화자

FILENAME_RE = re.compile(
    r"^Talk_(\d{4}\.\d{1,2}\.\d{1,2}\s+\d{1,2}:\d{2})-(\d+)\.txt$"
)


# =========================
# Collect files
# =========================
def collect_and_validate_files() -> List[str]:
    """
    Returns a list of filenames sorted by trailing number.
    Raises ValueError if datetime part differs.
    """
    folder = Path(PATH_EXPORTED_CHAT)
    records = []

    for p in folder.iterdir():
        if not p.is_file():
            continue

        m = FILENAME_RE.match(p.name)
        if not m:
            continue  # ignore unrelated files

        datetime_part = m.group(1)
        seq = int(m.group(2))
        records.append((datetime_part, seq, p.name))

    if not records:
        return []

    # Validate all datetime parts are identical
    datetime_set = {dt for dt, _, _ in records}
    if len(datetime_set) != 1:
        raise ValueError(
            f"Inconsistent datetime in filenames: {sorted(datetime_set)}"
        )

    # Sort by sequence number
    records.sort(key=lambda x: x[1])

    return [name for _, _, name in records]


# =========================
# Main
# =========================
def main():
    chat_files = collect_and_validate_files()
    if not chat_files:
        raise ValueError("No chat files found.")

    # -----------------------------
    # 0) Load existing dictionaries (optional; start fresh if missing)
    # -----------------------------
    try:
        weapon_root_map, start_ts_wr, end_ts_wr = load_dictionary(RawData.WEAPON_ROOT_MAP)
    except FileNotFoundError:
        weapon_root_map, start_ts_wr, end_ts_wr = {}, None, None

    try:
        upgrade_cost, start_ts_uc, end_ts_uc = load_dictionary(RawData.UPGRADE_COST)
    except FileNotFoundError:
        upgrade_cost, start_ts_uc, end_ts_uc = {}, None, None

    try:
        enhance_events, start_ts_en, end_ts_en = load_dictionary(RawData.ENHANCE_EVENTS)
    except FileNotFoundError:
        enhance_events, start_ts_en, end_ts_en = {}, None, None

    try:
        sell_events, start_ts_se, end_ts_se = load_dictionary(RawData.SELL_EVENTS)
    except FileNotFoundError:
        sell_events, start_ts_se, end_ts_se = {}, None, None

    # Merge timestamps from loaded payloads (if present)
    loaded_starts = [t for t in (start_ts_wr, start_ts_uc, start_ts_en, start_ts_se) if t is not None]
    loaded_ends = [t for t in (end_ts_wr, end_ts_uc, end_ts_en, end_ts_se) if t is not None]
    overall_start = min(loaded_starts) if loaded_starts else None
    overall_end = max(loaded_ends) if loaded_ends else None

    # -----------------------------
    # 1) Parse chat files into one DataFrame
    # -----------------------------
    prev_seq = 0
    dfs = []

    for fname in chat_files:
        with open(fname, "r", encoding="utf-8") as f:
            plain_text = f.read()

        kakao_chat = parse_kakao(plain_text, prev_seq)
        dfs.append(kakao_chat)

        if not kakao_chat.empty:
            prev_seq = int(kakao_chat["seq"].iloc[-1]) + 1

    all_chat = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    if all_chat.empty:
        raise ValueError("Parsed chat DataFrame is empty.")

    # Ensure dt is datetime
    if "dt" not in all_chat.columns:
        raise ValueError("parse_kakao output must contain 'dt' column as datetime.")
    if not pd.api.types.is_datetime64_any_dtype(all_chat["dt"]):
        all_chat["dt"] = pd.to_datetime(all_chat["dt"], errors="raise")

    stored_start = overall_start
    stored_end = overall_end

    if stored_start is not None and stored_end is not None:
        s = pd.Timestamp(stored_start)
        e = pd.Timestamp(stored_end)
        # inclusive: drop rows whose dt is within [s, e]
        mask_dup = (all_chat["dt"] >= s) & (all_chat["dt"] <= e)
        all_chat = all_chat.loc[~mask_dup].copy()

    # Determine timestamps for this run (Python datetime)
    run_start = all_chat["dt"].iloc[0].to_pydatetime()
    run_end = all_chat["dt"].iloc[-1].to_pydatetime()

    # Update overall time range
    overall_start = run_start if overall_start is None else min(overall_start, run_start)
    overall_end = run_end if overall_end is None else max(overall_end, run_end)

    # -----------------------------
    # 2) Extract replies and update statistics
    # -----------------------------
    reply_list, _, _ = extract_triplets(all_chat, USER_NAME, BOT_SENDER_NAME)

    for reply in reply_list:
        add_to_statistics(
            reply,
            weapon_root_map=weapon_root_map,
            upgrade_cost=upgrade_cost,
            enhance_events=enhance_events,
            sell_events=sell_events,
        )

    # -----------------------------
    # 3) Save updated dictionaries with merged timestamps
    # -----------------------------
    save_dictionary(RawData.WEAPON_ROOT_MAP, weapon_root_map, overall_start, overall_end)
    save_dictionary(RawData.UPGRADE_COST, upgrade_cost, overall_start, overall_end)
    save_dictionary(RawData.ENHANCE_EVENTS, enhance_events, overall_start, overall_end)
    save_dictionary(RawData.SELL_EVENTS, sell_events, overall_start, overall_end)

    return weapon_root_map, upgrade_cost, enhance_events, sell_events, overall_start, overall_end
