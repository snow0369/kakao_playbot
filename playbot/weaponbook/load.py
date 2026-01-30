import json
import os
from dataclasses import dataclass
from typing import Dict, Set, Tuple, Any, Union

from playbot.types import WeaponInfo


@dataclass
class WeaponBook:
    hierarchies: Dict[int, dict]
    weapon_index: Dict[Tuple[str, int], Set[int]]
    special_ids: Set[int]

    def update(self,
               hierarchies: Dict[int, dict],
               weapon_index: Dict[Tuple[str, int], Set[int]],
               special_ids: Set[int]) -> None:
        self.hierarchies = hierarchies
        self.weapon_index = weapon_index
        self.special_ids = set(special_ids)


def load_weapon_book(
        out_dir: str = "data/weapon_trees",
) -> Union[WeaponBook, Tuple[WeaponBook, Dict[int, dict]]]:
    """
    Load hierarchy_*.json files produced by crawl_all_hierarchies_by_clicking().

    Returns:
      hierarchies: {hid: {"id", "special", "nodes", "by_level", ...}}
      special_ids: set of hierarchy ids marked special
      appearance:  (name, level) -> {hid, ...}  (for duplicate detection across trees)

    Args:
      out_dir: directory where hierarchy_*.json and index.json are saved
    """
    if not os.path.isdir(out_dir):
        raise FileNotFoundError(f"out_dir not found: {out_dir}")

    # index_path = os.path.join(out_dir, "index.json")
    # with open(index_path, "r", encoding="utf-8") as f:
    #     json_index = json.load(f)

    # Discover hierarchy JSON files
    files = []
    for name in os.listdir(out_dir):
        if name.startswith("hierarchy_") and name.endswith(".json"):
            files.append(os.path.join(out_dir, name))
    files.sort()

    hierarchies: Dict[int, dict] = {}
    special_ids: Set[int] = set()
    weapon_index: Dict[Tuple[str, int], Set[int]] = {}

    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            data: Any = json.load(f)
        hid_int = int(data["id"])
        nodes = data["nodes"]
        # Track special
        if bool(data["special"]):
            special_ids.add(hid_int)
        new_bylevel = dict()
        for k, v in data["by_level"].items():
            new_bylevel[int(k)] = WeaponInfo(**v)
        data["by_level"] = new_bylevel

        # Build appearance map: (name, level) -> set(hid)
        for n in nodes:
            if not isinstance(n, dict):
                continue
            name = n.get("name")
            level = n.get("level")
            level_int = int(level)
            weapon_index.setdefault((name, level_int), set()).add(hid_int)

        # Store
        hierarchies[hid_int] = data

    wpb = WeaponBook(hierarchies=hierarchies,
                     weapon_index=weapon_index,
                     special_ids=special_ids)

    return wpb
