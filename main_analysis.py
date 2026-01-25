import os
import re
from pathlib import Path
from typing import List

import pandas as pd

from config import load_username, load_botuserkey, load_botgroupkey
from playbot.parse import parse_kakao, extract_triplets, make_reload_cb, WeaponIdPolicy, assign_weapon_ids, \
    save_unresolved_replies_log
from playbot.statistics import load_dictionary, RawData, add_to_statistics, save_dictionary, export_enhance_stats_xlsx, \
    compute_probs_by_weapon_id, compute_probs_by_gold, summarize_weapon_risk, print_gold_table, plot_weapon_id_pca, \
    plot_weapon_prob_heatmap, compute_level_group_stats, print_level_group_stats_side_by_side, \
    compute_sell_stats_by_level_and_special, print_sell_stats_side_by_side, build_count_tables

# =========================
# Settings
# =========================
from playbot.strategy.strategy import build_prob_tables, build_sell_tables, optimal_strategy_for_weapon, print_strategy
from playbot.weaponbook import load_saved_hierarchies

PATH_EXPORTED_CHAT = "chat_log/"
WEAPON_TREE_DIR = "data/weapon_trees"
STAT_PATH = "enhance_statistics.xlsx"

USER_NAME = load_username()
BOT_SENDER_NAME = "플레이봇"  # 복사 텍스트에서 [플레이봇] 형태로 나타나는 발화자
BOT_USER_KEY = load_botuserkey()
BOT_GROUP_KEY = load_botgroupkey()

WB_OUT_DIR = "data/weapon_trees/"


FILENAME_RE = re.compile(
    r"^Talk_(\d{4}\.\d{1,2}\.\d{1,2}\s+\d{1,2}_\d{2})-(\d+)\.txt$"
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

    return [os.path.join(PATH_EXPORTED_CHAT, name) for _, _, name in records]


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
    loaded_starts = [t for t in (start_ts_uc, start_ts_en, start_ts_se) if t is not None]
    loaded_ends = [t for t in (end_ts_uc, end_ts_en, end_ts_se) if t is not None]
    overall_start = min(loaded_starts) if loaded_starts else None
    overall_end = max(loaded_ends) if loaded_ends else None

    # Load weapon book
    weapon_book = load_saved_hierarchies(WEAPON_TREE_DIR)

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

    if not all_chat.empty:
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

        # infer id
        reload_fn = make_reload_cb(
            bot_user_key=BOT_USER_KEY,
            bot_group_key=BOT_GROUP_KEY,
            tree_out_dir=WB_OUT_DIR,
            cache=weapon_book
        )

        infer_policy = WeaponIdPolicy(
            mode="batch",
            enable_reload=False,
            reload_on_missing_key=False,
            reload_on_termination_then_missing=True,
        )

        reply_list = assign_weapon_ids(
            replies=reply_list,
            book=weapon_book,
            previous_weapon_id=None,
            reload_weapon_book=reload_fn,
            policy=infer_policy
        )

        save_unresolved_replies_log(reply_list, "unresolved_weapon_id.log")

        for reply_idx, reply in enumerate(reply_list):
            add_to_statistics(
                reply,
                weapon_book=weapon_book,
                upgrade_cost=upgrade_cost,
                enhance_events=enhance_events,
                sell_events=sell_events,
            )

        # -----------------------------
        # 3) Save updated dictionaries with merged timestamps
        # -----------------------------
        save_dictionary(RawData.UPGRADE_COST, upgrade_cost, overall_start, overall_end)
        save_dictionary(RawData.ENHANCE_EVENTS, enhance_events, overall_start, overall_end)
        save_dictionary(RawData.SELL_EVENTS, sell_events, overall_start, overall_end)

    # -----------------------------
    # 4) Export to Excel
    # -----------------------------
    export_enhance_stats_xlsx(STAT_PATH, weapon_book, enhance_events)

    # -----------------------------
    # 5) Advanced Analysis
    # -----------------------------

    prob_by_id = compute_probs_by_weapon_id(enhance_events)
    prob_by_gold = compute_probs_by_gold(enhance_events, bin_size=1_000_000)
    prob_by_level_special = compute_level_group_stats(
        enhance_events,
        special_ids=set(weapon_book.special_ids),
    )

    print(f"Loaded enhance_events keys: {len(enhance_events)}")
    print(f"Weapon ids with stats      : {len(prob_by_id)}")
    print(f"Gold bins with stats       : {len(prob_by_gold)}")

    summarize_weapon_risk(prob_by_id, top_k=10)

    print_gold_table(prob_by_gold, top_n=30)

    plot_weapon_id_pca(prob_by_id)

    plot_weapon_prob_heatmap(prob_by_id, top_n=None)

    print_level_group_stats_side_by_side(prob_by_level_special)

    sell_stats = compute_sell_stats_by_level_and_special(
        sell_events,
        special_ids=set(weapon_book.special_ids),
    )
    print_sell_stats_side_by_side(sell_stats)

    for k in sorted(upgrade_cost.keys()):
        print(k, upgrade_cost[k])

    # -----------------------------
    # 6) Strategy test
    # -----------------------------
    special_set = set(weapon_book.special_ids)

    idlvl_cnt, grplvl_cnt, lvl_cnt = build_count_tables(enhance_events, special_ids=special_set)
    sell_idlvl, sell_grplvl, sell_lvl = build_sell_tables(sell_events, special_ids=special_set)

    # Example query: given weapon name & level & resolved id
    start_level = 9
    weapon_id = 1  # resolved tree id if known (recommended)

    # Confidence thresholds (tune as needed)
    MIN_N = 200
    MAX_BREAK_ERR = 0.02  # Wilson 95% CI half-width for BREAK

    decisions = optimal_strategy_for_weapon(
        start_level=start_level,
        weapon_id=weapon_id,
        special_ids=special_set,

        # NEW: counts for hierarchical backoff
        idlvl_cnt=idlvl_cnt,
        grplvl_cnt=grplvl_cnt,
        lvl_cnt=lvl_cnt,

        # SELL stats
        sell_idlvl=sell_idlvl,
        sell_grplvl=sell_grplvl,
        sell_lvl=sell_lvl,

        min_n=MIN_N,
        max_break_err=MAX_BREAK_ERR,

        max_level=18,
    )

    print_strategy(decisions, start_level=start_level)
    print("Expected gold from current state:", decisions[start_level].V)

    return upgrade_cost, enhance_events, sell_events, overall_start, overall_end


if __name__ == "__main__":
    main()
