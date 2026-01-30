from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple, Any
from collections import defaultdict
import math

from playbot.analysis import select_probs_with_backoff
from playbot.types import ReplyType, WeaponInfo, EnhanceCounts, EnhanceProbs, SellStats

# Reuse your enums / dataclasses
# ReplyType, WeaponInfo assumed defined as in your project

# ----------------------------
# Cost table (your last list)
# ----------------------------

UPGRADE_COST_BY_LEVEL = {
    0: 10,
    1: 20,
    2: 50,
    3: 100,
    4: 200,
    5: 500,
    6: 1000,
    7: 2000,
    8: 5000,
    9: 10000,
    10: 20000,
    11: 30000,
    12: 40000,
    13: 50000,
    14: 70000,
    15: 100000,
    16: 150000,
    17: 200000,
    18: 300000,
}

OUTCOMES = (ReplyType.ENHANCE_SUCCESS, ReplyType.ENHANCE_KEEP, ReplyType.ENHANCE_BREAK)


#TODO: Generalize dataclass after building more strategies.
@dataclass(frozen=True)
class Decision:
    action: str                  # "SELL" or "ENHANCE"
    V: float                     # optimal value at this level
    V_enh: float                 # enhance value (if chosen)
    S: float                     # sell mean
    ps: float
    pk: float
    pb: float
    n_prob: int
    n_sell: int


# ----------------------------
# Build probability tables
# ----------------------------

def build_prob_tables(
    enhance_events: Dict[WeaponInfo, Dict[ReplyType, List[Tuple[int, Any]]]],
    *,
    special_ids: Set[int],
) -> Tuple[
    Dict[Tuple[int, int], EnhanceProbs],          # (id, level) -> probs
    Dict[Tuple[str, int], EnhanceProbs],          # (group, level) -> probs, group in {"special","normal"}
    Dict[int, EnhanceProbs],                      # level -> probs (global)
]:
    # counts for id-level
    idlvl_counts = defaultdict(lambda: defaultdict(int))   # (id, lvl) -> rtype -> k
    idlvl_total = defaultdict(int)

    # counts for group-level
    grplvl_counts = defaultdict(lambda: defaultdict(int))  # (group, lvl) -> rtype -> k
    grplvl_total = defaultdict(int)

    # counts for global
    lvl_counts = defaultdict(lambda: defaultdict(int))     # lvl -> rtype -> k
    lvl_total = defaultdict(int)

    for w, evs in enhance_events.items():
        if w.id is None:
            continue
        lvl = w.level
        group = "special" if w.id in special_ids else "normal"

        for rt in OUTCOMES:
            k = len(evs.get(rt, []))
            if k <= 0:
                continue
            idlvl_counts[(w.id, lvl)][rt] += k
            idlvl_total[(w.id, lvl)] += k

            grplvl_counts[(group, lvl)][rt] += k
            grplvl_total[(group, lvl)] += k

            lvl_counts[lvl][rt] += k
            lvl_total[lvl] += k

    def to_probs(counts_map, total_map, key) -> Optional[EnhanceProbs]:
        n = total_map.get(key, 0)
        if n <= 0:
            return None
        ps = counts_map[key].get(ReplyType.ENHANCE_SUCCESS, 0) / n
        pk = counts_map[key].get(ReplyType.ENHANCE_KEEP, 0) / n
        pb = counts_map[key].get(ReplyType.ENHANCE_BREAK, 0) / n
        return EnhanceProbs(ps=ps, pk=pk, pb=pb, n=n)

    idlvl = {}
    for key in idlvl_total:
        p = to_probs(idlvl_counts, idlvl_total, key)
        if p:
            idlvl[key] = p

    grplvl = {}
    for key in grplvl_total:
        p = to_probs(grplvl_counts, grplvl_total, key)
        if p:
            grplvl[key] = p

    lvl = {}
    for key in lvl_total:
        p = to_probs(lvl_counts, lvl_total, key)
        if p:
            lvl[key] = p

    return idlvl, grplvl, lvl


# ----------------------------
# Build SELL mean/std tables
# ----------------------------

def build_sell_tables(
    sell_events: Dict[WeaponInfo, List[Tuple[int, Any]]],
    *,
    special_ids: Set[int],
) -> Tuple[
    Dict[Tuple[int, int], SellStats],             # (id, level) -> stats
    Dict[Tuple[str, int], SellStats],             # (group, level) -> stats
    Dict[int, SellStats],                         # level -> stats (global)
]:
    idlvl_vals = defaultdict(list)    # (id,lvl) -> [revenue]
    grplvl_vals = defaultdict(list)   # (group,lvl) -> [revenue]
    lvl_vals = defaultdict(list)      # lvl -> [revenue]

    for w, xs in sell_events.items():
        if w.id is None:
            continue
        lvl = w.level
        group = "special" if w.id in special_ids else "normal"
        for rev, _ts in xs:
            v = float(rev)
            idlvl_vals[(w.id, lvl)].append(v)
            grplvl_vals[(group, lvl)].append(v)
            lvl_vals[lvl].append(v)

    def stats(arr: List[float]) -> Optional[SellStats]:
        n = len(arr)
        if n == 0:
            return None
        mean = sum(arr) / n
        if n >= 2:
            var = sum((x - mean) ** 2 for x in arr) / (n - 1)
            std = math.sqrt(var)
        else:
            std = 0.0
        return SellStats(mean=mean, std=std, n=n)

    idlvl = {k: stats(v) for k, v in idlvl_vals.items() if stats(v) is not None}
    grplvl = {k: stats(v) for k, v in grplvl_vals.items() if stats(v) is not None}
    lvl = {k: stats(v) for k, v in lvl_vals.items() if stats(v) is not None}

    return idlvl, grplvl, lvl


# ----------------------------
# Strategy DP
# ----------------------------

def optimal_strategy_for_weapon(
    *,
    start_level: int,
    weapon_id: int,
    special_ids: Set[int],

    idlvl_cnt: Dict[Tuple[int, int], EnhanceCounts],
    grplvl_cnt: Dict[Tuple[str, int], EnhanceCounts],
    lvl_cnt: Dict[int, EnhanceCounts],

    sell_idlvl: Dict[Tuple[int, int], SellStats],
    sell_grplvl: Dict[Tuple[str, int], SellStats],
    sell_lvl: Dict[int, SellStats],

    # confidence policy
    min_n: int = 200,
    max_break_err: float = 0.02,

    max_level: int = 18,
    cost_by_level: Dict[int, int] = UPGRADE_COST_BY_LEVEL,
) -> Dict[int, Decision]:
    """
    Returns: decisions[level] = Decision(...)
    """

    def get_group(wid: Optional[int]) -> str:
        if wid is not None and wid in special_ids:
            return "special"
        return "normal"

    group = get_group(weapon_id)

    def probs_at(lvl: int) -> EnhanceProbs:
        p, src = select_probs_with_backoff(
            weapon_id=weapon_id,
            group=group,
            level=lvl,
            idlvl_cnt=idlvl_cnt,
            grplvl_cnt=grplvl_cnt,
            lvl_cnt=lvl_cnt,
            min_n=min_n,
            max_break_err=max_break_err,
        )
        return p

    def sell_at(lvl: int) -> SellStats:
        if weapon_id is not None:
            s = sell_idlvl.get((weapon_id, lvl))
            if s is not None:
                return s
        s = sell_grplvl.get((group, lvl))
        if s is not None:
            return s
        s = sell_lvl.get(lvl)
        if s is not None:
            return s
        return SellStats(mean=0.0, std=0.0, n=0)

    # DP arrays
    V = {max_level: sell_at(max_level).mean}
    decisions: Dict[int, Decision] = {}

    # Backward induction
    for lvl in range(max_level - 1, -1, -1):
        s = sell_at(lvl)
        p = probs_at(lvl)

        S = s.mean
        C = float(cost_by_level.get(lvl, 0))

        # Enhance value with KEEP self-loop:
        # V_enh = (-C + ps*V[l+1]) / (1 - pk)   (pb goes to 0 terminal)
        denom = 1.0 - p.pk
        if denom <= 1e-12:
            V_enh = float("-inf")  # cannot escape KEEP loop
        else:
            V_enh = (-C + p.ps * V[lvl + 1]) / denom

        if V_enh > S:
            action = "ENHANCE"
            V_opt = V_enh
        else:
            action = "SELL"
            V_opt = S

        V[lvl] = V_opt
        decisions[lvl] = Decision(
            action=action,
            V=V_opt,
            V_enh=V_enh,
            S=S,
            ps=p.ps, pk=p.pk, pb=p.pb,
            n_prob=p.n,
            n_sell=s.n,
        )

    # Return only from start_level upward (optional)
    return {lvl: decisions[lvl] for lvl in range(start_level, max_level + 1) if lvl in decisions}


def print_strategy(decisions: Dict[int, Decision], *, start_level: int) -> None:
    print("\n===== Optimal strategy (expected gold maximization) =====")
    print("lvl | action   |   V(opt)    |  SELL_mean  |  ENH_value  | ps   pk   pb | n_prob n_sell")
    print("---------------------------------------------------------------------------------------")
    for lvl in sorted(decisions):
        d = decisions[lvl]
        if lvl < start_level:
            continue
        print(
            f"{lvl:3d} | {d.action:7s} | {d.V:10.1f} | {d.S:10.1f} | {d.V_enh:10.1f} | "
            f"{d.ps:0.3f} {d.pk:0.3f} {d.pb:0.3f} | {d.n_prob:6d} {d.n_sell:6d}"
        )
    print("---------------------------------------------------------------------------------------\n")
