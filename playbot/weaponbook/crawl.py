import json
import os
import re
import time
from dataclasses import asdict
from typing import Tuple, List, Dict, Optional, Set
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from playbot.types import WeaponInfo

BASE = "https://collection.playbot.co.kr"
_ALT_RE = re.compile(
    r"^\s*\[\+(?P<plus>\d+)\]\s*(?P<name>.*?)\s*Lv\.(?P<lv>\d+)\s*$"
)
_H1_RE = re.compile(r"^\s*\+(\d+)\s*(.+?)\s*$")


def parse_weapon_hierarchy_from_html(html: str, hid: int) -> Tuple[List[WeaponInfo], Dict[int, WeaponInfo]]:
    """
    Parse the 'crawlbook crawlbook detail' HTML and return:
      - nodes: list of WeaponNode sorted by level ascending
      - by_level: dict level -> WeaponNode

    This uses <img alt="...[+k] ... Lv.k"> entries inside the grid.
    Locked slots are ignored.
    """
    soup = BeautifulSoup(html, "html.parser")

    nodes: List[WeaponInfo] = []

    # All weapon slots have an <img alt="... Lv.X"> with src = image.
    for img in soup.find_all("img"):
        alt = (img.get("alt") or "").strip()
        m = _ALT_RE.match(alt)
        if not m:
            continue

        plus = int(m.group("plus"))
        name = m.group("name").strip()
        lv = int(m.group("lv"))

        full_name = f"[+{plus}] {name}"
        src = img.get("src")
        nodes.append(
            WeaponInfo(
                level=lv,
                name=name,
                id=hid,
            )
        )

    by_level: Dict[int, WeaponInfo] = {}
    for n in nodes:
        prev = by_level.get(n.level)
        if prev is None:
            by_level[n.level] = n
        else:
            if prev != n:
                raise ValueError(f"Conflicting nodes for level {n.level}: {prev} vs {n}")

    # Sorted list
    ordered = [by_level[k] for k in sorted(by_level.keys())]
    return ordered, by_level


def is_invalid_weapon_page(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")

    # explicit error message
    if soup.find(string=lambda s: s and "검 정보가 없습니다" in s):
        return True

    # or: no Lv.X items at all
    has_lv = any(
        (img.get("alt") or "").find("Lv.") != -1
        for img in soup.find_all("img")
    )
    return not has_lv


def get_hierarchy(hierarchy_id: int, bot_user_key: str, driver: WebDriver):
    url = BASE + f"/sword?id={hierarchy_id}&botUserKey={bot_user_key}"
    driver.get(url)
    html = driver.page_source
    if is_invalid_weapon_page(html):
        return None
    else:
        return parse_weapon_hierarchy_from_html(html)


def _extract_hierarchy_id(url: str) -> Optional[int]:
    try:
        qs = parse_qs(urlparse(url).query)
        if "id" not in qs:
            return None
        return int(qs["id"][0])
    except Exception:
        return None


def _is_special_tile(tile_el) -> bool:
    """
    A tile is 'special' if it contains a badge span with text '특수'.
    This matches your collection HTML: <span class="_rareBadge_...">특수</span>
    """
    try:
        badges = tile_el.find_elements(By.XPATH, ".//span[normalize-space()='특수']")
        return len(badges) > 0
    except Exception:
        return False


def _wait_collection_grid(driver, timeout=15):
    """
    Wait until the collection grid is present.
    The page uses a grid with many <div class="_gridItem_..."> tiles.
    """
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, "//div[contains(@class,'_grid_') or contains(@class,'_grid')]"))
    )
    WebDriverWait(driver, timeout).until(
        EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@class,'_gridItem_')]"))
    )


def _wait_detail_page_loaded(driver, timeout=15):
    """
    Wait for detail page to load enough that the grid of levels appears.
    In your detail HTML, the level slots are also _gridItem_...
    """
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, "//main"))
    )
    # Either the detail grid exists, or an error message exists.
    WebDriverWait(driver, timeout).until(
        lambda d: ("검 정보가 없습니다" in d.page_source) or ("Lv." in d.page_source)
    )


def crawl_all_hierarchies_by_clicking(
        driver: webdriver.Chrome,
        bot_user_key: str,
        bot_group_key: str,
        out_dir: str = "data/weapon_trees",
        sort: str = "enhancement",
        max_tiles: Optional[int] = None,  # for debugging, limit how many tiles to click
) -> Tuple[
    Dict[int, dict],  # hierarchy_id -> {"nodes":[...], "by_level":{...}}
    Set[int],  # special hierarchy ids
    Dict[Tuple[str, int], Set[int]],  # (name,level)->set(hierarchy_id)
]:
    os.makedirs(out_dir, exist_ok=True)

    # Open the collection page
    collection_url = f"{BASE}/?botGroupKey={bot_group_key}&botUserKey={bot_user_key}&sort={sort}"
    driver.get(collection_url)
    _wait_collection_grid(driver)

    hierarchies: Dict[int, dict] = {}
    special_ids: Set[int] = set()
    appearance: Dict[Tuple[str, int], Set[int]] = {}

    # Determine tile count once; but re-query each iteration to avoid stale elements.
    tiles = driver.find_elements(By.XPATH, "//div[contains(@class,'_gridItem_')]")
    total_tiles = len(tiles)
    if max_tiles is not None:
        total_tiles = min(total_tiles, max_tiles)

    print(f"[INFO] Found {len(tiles)} tiles on collection page; will process {total_tiles} tiles.")

    for idx in range(total_tiles):
        # Re-query tiles each iteration (prevents StaleElementReferenceException after back navigation)
        _wait_collection_grid(driver)
        tiles = driver.find_elements(By.XPATH, "//div[contains(@class,'_gridItem_')]")
        if idx >= len(tiles):
            print(f"[WARN] Tile index {idx} out of range after refresh; stopping.")
            break

        tile = tiles[idx]
        is_special = _is_special_tile(tile)

        # Click the tile (ensure clickable)
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable(tile))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", tile)
        time.sleep(0.1)
        tile.click()

        _wait_detail_page_loaded(driver)
        current_url = driver.current_url
        hid = _extract_hierarchy_id(current_url)

        if hid is None:
            print(f"[WARN] Could not extract id from URL after clicking tile {idx}: {current_url}")
            driver.back()
            continue

        if is_special:
            special_ids.add(hid)

        html = driver.page_source
        if is_invalid_weapon_page(html):
            print(f"[WARN] Invalid weapon detail page for id={hid} (tile {idx}).")
            driver.back()
            continue

        # Parse hierarchy
        ordered_nodes, by_level = parse_weapon_hierarchy_from_html(html, hid)

        # Store in-memory
        hierarchies[hid] = {
            "id": hid,
            "special": is_special,
            "nodes": [asdict(n) for n in ordered_nodes],
            "by_level": {lv: asdict(wi) for lv, wi in by_level.items()},
        }

        # Update (name, level) appearance map for duplicate detection across trees
        for n in ordered_nodes:
            key = (n.name, n.level)
            appearance.setdefault(key, set()).add(hid)

        # Save per-tree JSON
        out_path = os.path.join(out_dir, f"hierarchy_{hid}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(hierarchies[hid], f, ensure_ascii=False, indent=2)

        print(f"[OK] Saved id={hid} (special={is_special}) with {len(ordered_nodes)} nodes -> {out_path}")

        # Also write an index file
        index = {
            "tree_count": len(hierarchies),
            "special_ids": sorted(special_ids),
            "tree_ids": sorted(hierarchies.keys()),
        }
        idx_path = os.path.join(out_dir, "index.json")
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        print(f"[OK] Wrote {idx_path}")

        # Go back to the collection page
        driver.back()

    return hierarchies, special_ids, appearance
