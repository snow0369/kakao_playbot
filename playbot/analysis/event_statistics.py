from typing import Dict, Optional

from playbot.types import ReplyInfo, WeaponInfo, ReplyType, EnhanceEvents, SellEvents
from playbot.weaponbook import WeaponBook


def add_to_statistics(
        reply: ReplyInfo,
        weapon_book: WeaponBook,
        upgrade_cost: Dict[int, int],  # before level -> cost (lv -> lv+1 attempt)
        enhance_events: EnhanceEvents,
        sell_events: SellEvents,
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

    def _infer_before_from_after(wa) -> Optional[WeaponInfo]:
        if wa is None or wa.level <= 0:
            return None

        key = (wa.name, wa.level)
        hid_set = weapon_book.weapon_index.get(key)
        if not hid_set or len(hid_set) != 1:
            return None

        hid = next(iter(hid_set))
        hier = weapon_book.hierarchies.get(hid)
        if hier is None:
            return None

        by_level = hier.get("by_level")
        if by_level is None or (wa.level - 1) not in by_level:
            return None

        wb = by_level[wa.level - 1]
        # wb가 WeaponInfo이거나 최소한 name/level을 가진다고 가정
        return WeaponInfo(level=wa.level - 1, name=wb.name, id=hid)

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

        bg = _before_gold(reply)

        if wb not in enhance_events:
            enhance_events[wb] = {
                ReplyType.ENHANCE_SUCCESS: [],
                ReplyType.ENHANCE_BREAK: [],
                ReplyType.ENHANCE_KEEP: [],
            }
        enhance_events[wb][reply.type].append((bg, reply.timestamp))
        return

    # ------------------------------------------------------------
    # Sell events
    # ------------------------------------------------------------
    if reply.type == ReplyType.SELL:
        wb = reply.weapon_before
        if wb is None or reply.reward is None:
            return
        sell_events.setdefault(wb, []).append((int(reply.reward), reply.timestamp))
        return
