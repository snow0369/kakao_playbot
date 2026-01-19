from enum import Enum
from typing import Dict, Tuple, List, Optional

from parse import ReplyInfo, WeaponInfo, ReplyType


# Raw data dictionaries
class RawData(str, Enum):
    WEAPON_ROOT_MAP = "weapon_root_map"
    UPGRADE_COST = "upgrade_cost"
    ENHANCE_EVENTS = "enhance_events"
    SELL_EVENTS = "sell_events"


def add_to_statistics(
        reply: ReplyInfo,
        weapon_root_map: Dict[str, Tuple[WeaponInfo, WeaponInfo]],
        upgrade_cost: Dict[int, int],  # before level -> cost (for lv -> lv+1 attempt)
        enhance_events: Dict[str, Dict[ReplyType, List[int]]],  # before weapon name -> ReplyType -> list[before_gold]
        sell_events: Dict[str, List[int]],  # before weapon name -> list[sold_gold]
):
    """
    Update:
      - weapon_root_map: weapon_name -> (weapon_info, root_weapon_info(level=1))
      - upgrade_cost: before_level -> cost (for an attempt from lv to lv+1)
      - enhance_events: before_weapon_name -> {ReplyType: [before_gold, ...]}
      - sell_events: before_weapon_name -> [sold_gold, ...]

    Notes:
      - Ignores level-0 weapons in weapon_root_map.
      - For enhance events, aggregates by weapon_before.name (level-dependent names are treated distinctly).
      - upgrade_cost depends only on the attempted level (lv -> lv+1), not on success/keep/break.
      - Raises on mismatch if an existing mapping conflicts.
    """

    def _put_weapon_root(name: str, wi: WeaponInfo, root: WeaponInfo) -> None:
        """Insert (wi, root) into weapon_root_map with mismatch checks. Ignores level 0."""
        if wi.level == 0:
            return
        prev = weapon_root_map.get(name)
        if prev is None:
            weapon_root_map[name] = (wi, root)
            return
        prev_wi, prev_root = prev
        if prev_wi != wi or prev_root != root:
            raise ValueError(
                f"weapon_root_map mismatch for '{name}': stored={(prev_wi, prev_root)} new={(wi, root)}"
            )

    def _root_of(name: str) -> Optional[WeaponInfo]:
        """Return root WeaponInfo(level=1) for a weapon name if known."""
        entry = weapon_root_map.get(name)
        return entry[1] if entry else None

    def _set_upgrade_cost(lv: int, cost: int) -> None:
        """Set cost for before-level lv with mismatch checks."""
        prev = upgrade_cost.get(lv)
        if prev is None:
            upgrade_cost[lv] = cost
            return
        if prev != cost:
            raise ValueError(f"upgrade_cost mismatch for lv={lv}: stored={prev} new={cost}")

    def _before_gold(r: ReplyInfo) -> int:
        """Compute gold before spending."""
        if r.gold_after is None or r.cost is None:
            raise AssertionError("gold_after and cost must exist for enhance events")
        return int(r.gold_after) + int(r.cost)

    # ------------------------------------------------------------
    # 1) Update weapon_root_map (only from SUCCESS transitions)
    # ------------------------------------------------------------
    if reply.type == ReplyType.ENHANCE_SUCCESS:
        wb = reply.weapon_before
        wa = reply.weapon_after
        assert wb is not None and wa is not None
        assert wb.level + 1 == wa.level

        root: Optional[WeaponInfo] = None
        if wa.level == 1:
            root = wa
        else:
            if wb.level >= 1:
                root = _root_of(wb.name)
            if root is None and wb.level == 0 and wa.level == 1:
                root = wa

        if root is not None:
            if wb.level >= 1:
                _put_weapon_root(wb.name, wb, root)
            _put_weapon_root(wa.name, wa, root)

    # ------------------------------------------------------------
    # 2) Update upgrade_cost and enhance_list (enhance events only)
    # ------------------------------------------------------------
    if reply.type in (ReplyType.ENHANCE_SUCCESS, ReplyType.ENHANCE_KEEP, ReplyType.ENHANCE_BREAK):
        wb = reply.weapon_before
        assert wb is not None
        lv = wb.level

        # cost is for attempt lv -> lv+1 regardless of outcome
        assert reply.cost is not None
        _set_upgrade_cost(lv, int(reply.cost))

        # Ignore level-0 weapons in enhance_list
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
    # 3) Update sell_list
    # ------------------------------------------------------------
    if reply.type == ReplyType.SELL:
        wb = reply.weapon_before
        assert wb is not None
        assert reply.reward is not None

        w_key = wb.name
        if w_key not in sell_events:
            sell_events[w_key] = []
        sell_events[w_key].append(int(reply.reward))
        return
