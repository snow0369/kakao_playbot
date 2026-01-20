from enum import Enum
from typing import Dict, Tuple, Optional, List
from parse import ReplyInfo, WeaponInfo, ReplyType


# Raw data dictionaries
class RawData(str, Enum):
    WEAPON_ROOT_MAP = "weapon_root_map"
    UPGRADE_COST = "upgrade_cost"
    ENHANCE_EVENTS = "enhance_events"
    SELL_EVENTS = "sell_events"
    ROOT_LEVEL_INDEX = "root_level_index"


def update_weapon_root_map(
        reply: ReplyInfo,
        weapon_root_map: Dict[str, Tuple[WeaponInfo, WeaponInfo]],
        root_level_index: Dict[Tuple[str, int], WeaponInfo],  # (root_name, level) -> weapon_info
):
    """
    Update:
      - weapon_root_map: weapon_name -> (weapon_info, root_weapon_info(level=1))
      - root_level_index: (root_name, level) -> weapon_info

    Notes:
      - Ignores level-0 weapons.
      - Only uses ENHANCE_SUCCESS transitions where weapon_before is present,
        because those reliably define level linkage and chain.
      - Raises on mismatches.
    """

    def _put_weapon_root(name: str, wi: WeaponInfo, root: WeaponInfo) -> None:
        if wi.level == 0:
            return

        prev = weapon_root_map.get(name)
        if prev is None:
            weapon_root_map[name] = (wi, root)
        else:
            prev_wi, prev_root = prev
            if prev_wi != wi or prev_root != root:
                raise ValueError(
                    f"weapon_root_map mismatch for '{name}': stored={(prev_wi, prev_root)} new={(wi, root)}"
                )

        key = (root.name, wi.level)
        prev_wi = root_level_index.get(key)
        if prev_wi is None:
            root_level_index[key] = wi
        elif prev_wi != wi:
            raise ValueError(f"root_level_index mismatch for {key}: stored={prev_wi} new={wi}")

    def _root_of(name: str) -> Optional[WeaponInfo]:
        entry = weapon_root_map.get(name)
        return entry[1] if entry else None

    # Only success transitions define the chain structure
    if reply.type != ReplyType.ENHANCE_SUCCESS:
        return

    wb = reply.weapon_before
    wa = reply.weapon_after
    if wb is None or wa is None:
        return

    # Structural sanity
    if wb.level + 1 != wa.level:
        raise ValueError(f"Invalid success level transition: {wb.level} -> {wa.level}")

    # Determine root
    root: Optional[WeaponInfo] = None
    if wa.level == 1:
        root = wa
    else:
        if wb.level >= 1:
            root = _root_of(wb.name)
        if root is None and wb.level == 0 and wa.level == 1:
            root = wa

    if root is None:
        return

    if wb.level >= 1:
        _put_weapon_root(wb.name, wb, root)
    _put_weapon_root(wa.name, wa, root)


def add_to_statistics(
        reply: ReplyInfo,
        weapon_root_map: Dict[str, Tuple[WeaponInfo, WeaponInfo]],
        root_level_index: Dict[Tuple[str, int], WeaponInfo],
        upgrade_cost: Dict[int, int],  # before level -> cost (lv -> lv+1 attempt)
        enhance_events: Dict[str, Dict[ReplyType, List[int]]],  # before weapon name -> ReplyType -> list[before_gold]
        sell_events: Dict[str, List[int]],  # before weapon name -> list[sold_gold]
):
    """
    Update:
      - upgrade_cost: before_level -> cost (for lv -> lv+1 attempt)
      - enhance_events: before_weapon_name -> {ReplyType: [before_gold, ...]}
      - sell_events: before_weapon_name -> [sold_gold, ...]

    Notes:
      - weapon_before may be missing for ENHANCE_SUCCESS; in that case infer from weapon_after
        using weapon_root_map + root_level_index.
      - Ignores level-0 weapons for enhance_events.
      - Raises on mismatch for upgrade_cost.
    """

    def _set_upgrade_cost(lv: int, cost: int) -> None:
        prev = upgrade_cost.get(lv)
        if prev is None:
            upgrade_cost[lv] = cost
        elif prev != cost:
            raise ValueError(f"upgrade_cost mismatch for lv={lv}: stored={prev} new={cost}")

    def _before_gold(r: ReplyInfo) -> int:
        if r.gold_after is None or r.cost is None:
            raise AssertionError("gold_after and cost must exist for enhance events")
        return int(r.gold_after) + int(r.cost)

    def _infer_before_from_after(wa: WeaponInfo) -> Optional[WeaponInfo]:
        """
        Infer weapon_before for a success event when missing.
        Needs wa present in weapon_root_map and previous level present in root_level_index.
        """
        entry = weapon_root_map.get(wa.name)
        if entry is None:
            return None

        wa_info, root = entry
        if wa_info.level <= 1:
            return None  # previous is level 0 (ignored)

        prev_weapon = root_level_index.get((root.name, wa_info.level - 1))
        return prev_weapon  # already WeaponInfo

    # ------------------------------------------------------------
    # Enhance events: update upgrade_cost + enhance_events
    # ------------------------------------------------------------
    if reply.type in (ReplyType.ENHANCE_SUCCESS, ReplyType.ENHANCE_KEEP, ReplyType.ENHANCE_BREAK):
        wb = reply.weapon_before
        wa = reply.weapon_after

        # If wb missing, only infer for success; keep/break cannot be safely inferred here.
        if wb is None:
            if reply.type == ReplyType.ENHANCE_SUCCESS and wa is not None:
                wb = _infer_before_from_after(wa)
            if wb is None:
                return  # cannot attribute stats to a weapon name

        lv = wb.level

        # cost per attempt depends only on lv -> lv+1
        if reply.cost is None:
            return
        _set_upgrade_cost(lv, int(reply.cost))

        # ignore level 0 in enhance_events
        if lv == 0:
            return

        bg = _before_gold(reply)
        w_key = wb.name

        if w_key not in enhance_events:
            enhance_events[w_key] = {
                ReplyType.ENHANCE_SUCCESS: [],
                ReplyType.ENHANCE_BREAK: [],
                ReplyType.ENHANCE_KEEP: [],
            }
        enhance_events[w_key][reply.type].append(bg)
        return

    # ------------------------------------------------------------
    # Sell events
    # ------------------------------------------------------------
    if reply.type == ReplyType.SELL:
        wb = reply.weapon_before
        if wb is None or reply.reward is None:
            return

        w_key = wb.name
        sell_events.setdefault(w_key, []).append(int(reply.reward))
        return
