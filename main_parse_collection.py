import json
import os
from typing import Set, Tuple, Dict

from selenium import webdriver

from config import load_botuserkey, load_botgroupkey
from crawlbook.parse_collection import crawl_all_hierarchies_by_clicking

BOT_USER_KEY = load_botuserkey()
BOT_GROUP_KEY = load_botgroupkey()

OUT_DIR = "data"
OUT_PKL = os.path.join(OUT_DIR, "weapon_trees.pkl")
OUT_JSON = os.path.join(OUT_DIR, "weapon_trees.json")  # optional


def report_duplicates(appearance: Dict[Tuple[str, int], Set[int]]):
    dup = {k: v for k, v in appearance.items() if len(v) >= 2}
    print(f"\n[REPORT] Duplicated (name, level) across different trees: {len(dup)}")
    for (name, lv), hids in sorted(dup.items(), key=lambda kv: (-len(kv[1]), kv[0][1], kv[0][0])):
        hids_sorted = sorted(hids)
        print(f"  - (level={lv}, name='{name}') appears in {len(hids_sorted)} trees: {hids_sorted}")


def main():
    driver = webdriver.Chrome()
    try:
        trees, special_ids, appearance = crawl_all_hierarchies_by_clicking(
            driver=driver,
            bot_user_key=BOT_USER_KEY,
            bot_group_key=BOT_GROUP_KEY,
            out_dir="weapon_trees",
            sort="enhancement",
            max_tiles=None,  # set e.g. 30 for testing
        )

        print(f"\n[SUMMARY] Parsed trees: {len(trees)}")
        print(f"[SUMMARY] Special hierarchy ids: {sorted(special_ids)}")

        report_duplicates(appearance)

        # Also write an index file
        index = {
            "tree_count": len(trees),
            "special_ids": sorted(special_ids),
            "tree_ids": sorted(trees.keys()),
        }
        with open("weapon_trees/index.json", "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        print("[OK] Wrote weapon_trees/index.json")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
