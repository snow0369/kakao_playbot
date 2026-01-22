from typing import Set, Tuple, Dict, List

from selenium import webdriver

from config import load_botuserkey, load_botgroupkey
from playbot.weaponbook import crawl_all_hierarchies_by_clicking

BOT_USER_KEY = load_botuserkey()
BOT_GROUP_KEY = load_botgroupkey()

OUT_DIR = "data/weapon_trees/"


def report_duplicates(appearance: Dict[Tuple[str, int], Set[int]]):
    dup = {k: v for k, v in appearance.items() if len(v) >= 2}
    print(f"\n[REPORT] Duplicated (name, level) across different trees: {len(dup)}")
    for (name, lv), hids in sorted(dup.items(), key=lambda kv: (-len(kv[1]), kv[0][1], kv[0][0])):
        hids_sorted = sorted(hids)
        print(f"  - (level={lv}, name='{name}') appears in {len(hids_sorted)} trees: {hids_sorted}")


def _node_signature_list(tree_dict: dict) -> List[Tuple[int, str]]:
    """
    Convert a saved tree dict to an ordered signature list for prefix comparison.
    Uses (level, name) to avoid false matches between same name at different levels.
    """
    sig: List[Tuple[int, str]] = []
    for n in tree_dict.get("nodes", []):
        if not isinstance(n, dict):
            continue
        name = n.get("name")
        level = n.get("level")
        if isinstance(name, str):
            try:
                lv = int(level)
            except Exception:
                continue
            sig.append((lv, name))
    return sig


def _common_prefix_len(a: List[Tuple[int, str]], b: List[Tuple[int, str]]) -> int:
    m = min(len(a), len(b))
    k = 0
    while k < m and a[k] == b[k]:
        k += 1
    return k


def report_max_coinciding_depth(trees: Dict[int, dict], top_k: int = 10) -> None:
    """
    Print the maximum depth of coinciding consecutive nodes among trees,
    interpreted as the longest common PREFIX among any pair of trees.
    """
    ids = sorted(trees.keys())
    if len(ids) < 2:
        print("\n[REPORT] Not enough trees to compare for coinciding depth.")
        return

    sigs: Dict[int, List[Tuple[int, str]]] = {hid: _node_signature_list(trees[hid]) for hid in ids}

    max_depth = 0
    best_pairs: List[Tuple[int, int]] = []

    for i, hid1 in enumerate(ids):
        s1 = sigs[hid1]
        for hid2 in ids[i + 1:]:
            d = _common_prefix_len(s1, sigs[hid2])
            if d > max_depth:
                max_depth = d
                best_pairs = [(hid1, hid2)]
            elif d == max_depth and d > 0:
                best_pairs.append((hid1, hid2))

    print("\n[REPORT] Maximum coinciding consecutive depth (common prefix)")
    print(f"  - max_depth = {max_depth}")

    if max_depth == 0:
        print("  - No pair shares a common starting node sequence.")
        return

    # Print a few best pairs and the shared prefix sequence
    shown = 0
    for hid1, hid2 in best_pairs:
        if shown >= top_k:
            remaining = len(best_pairs) - shown
            if remaining > 0:
                print(f"  - ... and {remaining} more pair(s) with the same max_depth")
            break

        prefix = sigs[hid1][:max_depth]  # same as sigs[hid2][:max_depth]
        print(f"\n  Pair: {hid1} <-> {hid2}")
        for lv, name in prefix:
            print(f"    * level={lv}, name='{name}'")
        shown += 1


def main():
    driver = webdriver.Chrome()
    try:
        trees, special_ids, appearance = crawl_all_hierarchies_by_clicking(
            driver=driver,
            bot_user_key=BOT_USER_KEY,
            bot_group_key=BOT_GROUP_KEY,
            out_dir=OUT_DIR,
            sort="enhancement",
            max_tiles=None,  # set e.g. 30 for testing
        )

        print(f"\n[SUMMARY] Parsed trees: {len(trees)}")
        print(f"[SUMMARY] Special hierarchy ids: {sorted(special_ids)}")

        report_duplicates(appearance)
        report_max_coinciding_depth(trees, top_k=10)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
