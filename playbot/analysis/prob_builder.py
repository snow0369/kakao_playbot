from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any, Set, Literal, Optional

from .stat_utils import counts_break_halfwidth, counts_to_probs
from playbot.types import WeaponInfo, ReplyType, EnhanceCounts, EnhanceProbs


def build_count_tables(
        enhance_events: Dict[WeaponInfo, Dict[ReplyType, List[Tuple[int, Any]]]],
        *,
        special_ids: Set[int],
) -> Tuple[
    Dict[Tuple[int, int], EnhanceCounts],  # (id, level)
    Dict[Tuple[str, int], EnhanceCounts],  # (group, level)
    Dict[int, EnhanceCounts],  # level
]:
    idlvl = defaultdict(lambda: defaultdict(int))
    grplvl = defaultdict(lambda: defaultdict(int))
    lvl = defaultdict(lambda: defaultdict(int))

    for w, evs in enhance_events.items():
        if w.id is None:
            continue
        L = w.level
        grp = "special" if w.id in special_ids else "normal"

        id_key = (w.id, L)
        grp_key = (grp, L)
        lvl_key = L

        idlvl[id_key]["success"] += len(evs.get(ReplyType.ENHANCE_SUCCESS, []))
        idlvl[id_key]["keep"] += len(evs.get(ReplyType.ENHANCE_KEEP, []))
        idlvl[id_key]["break"] += len(evs.get(ReplyType.ENHANCE_BREAK, []))

        grplvl[grp_key]["success"] += len(evs.get(ReplyType.ENHANCE_SUCCESS, []))
        grplvl[grp_key]["keep"] += len(evs.get(ReplyType.ENHANCE_KEEP, []))
        grplvl[grp_key]["break"] += len(evs.get(ReplyType.ENHANCE_BREAK, []))

        lvl[lvl_key]["success"] += len(evs.get(ReplyType.ENHANCE_SUCCESS, []))
        lvl[lvl_key]["keep"] += len(evs.get(ReplyType.ENHANCE_KEEP, []))
        lvl[lvl_key]["break"] += len(evs.get(ReplyType.ENHANCE_BREAK, []))

    def to_counts(d) -> EnhanceCounts:
        ks = int(d.get("success", 0))
        kk = int(d.get("keep", 0))
        kb = int(d.get("break", 0))
        n = ks + kk + kb
        return EnhanceCounts(n=n, k_success=ks, k_keep=kk, k_break=kb)

    idlvl_cnt = {k: to_counts(v) for k, v in idlvl.items()}
    grplvl_cnt = {k: to_counts(v) for k, v in grplvl.items()}
    lvl_cnt = {k: to_counts(v) for k, v in lvl.items()}

    return idlvl_cnt, grplvl_cnt, lvl_cnt


@dataclass(frozen=True)
class ProbSource:
    source: Literal["id_level", "group_level", "level", "fallback"]
    n: int
    break_err: float


def select_probs_with_backoff(
    *,
    weapon_id: Optional[int],
    group: str,  # "special" or "normal"
    level: int,
    idlvl_cnt: Dict[Tuple[int, int], EnhanceCounts],
    grplvl_cnt: Dict[Tuple[str, int], EnhanceCounts],
    lvl_cnt: Dict[int, EnhanceCounts],
    min_n: int = 200,
    max_break_err: float = 0.02,  # 95% CI half-width threshold for BREAK
) -> Tuple[EnhanceProbs, ProbSource]:
    # 1) id-level
    if weapon_id is not None:
        cnt = idlvl_cnt.get((weapon_id, level))
        if cnt is not None and cnt.n >= min_n:
            berr = counts_break_halfwidth(cnt)
            if berr <= max_break_err:
                return counts_to_probs(cnt), ProbSource("id_level", cnt.n, berr)

    # 2) group-level (special/normal)
    cnt = grplvl_cnt.get((group, level))
    if cnt is not None and cnt.n >= min_n:
        berr = counts_break_halfwidth(cnt)
        if berr <= max_break_err:
            return counts_to_probs(cnt), ProbSource("group_level", cnt.n, berr)

    # 3) global level
    cnt = lvl_cnt.get(level)
    if cnt is not None and cnt.n > 0:
        berr = counts_break_halfwidth(cnt) if cnt.n >= 1 else 1.0
        # Even if not meeting threshold, this is the best remaining estimate
        return counts_to_probs(cnt), ProbSource("level", cnt.n, berr)

    # 4) ultimate fallback
    return EnhanceProbs(ps=1.0, pk=0.0, pb=0.0, n=0), ProbSource("fallback", 0, 1.0)
