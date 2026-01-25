import math
from collections import defaultdict
from typing import Dict, Set, Tuple, List

import matplotlib
matplotlib.use("Agg")
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.decomposition import PCA

from .stat_utils import wilson_ci
from playbot.types import WeaponInfo, ReplyType


def compute_probs_by_weapon_id(
        enhance_events: Dict[WeaponInfo, Dict[ReplyType, list]]
) -> Dict[int, Dict[ReplyType, float]]:
    """
    반환:
      {
        weapon_id: {
            ReplyType.ENHANCE_SUCCESS: p_s,
            ReplyType.ENHANCE_KEEP: p_k,
            ReplyType.ENHANCE_BREAK: p_b,
        }
      }
    """
    counts = defaultdict(lambda: defaultdict(int))

    for w, events in enhance_events.items():
        if w.id is None:
            continue  # unresolved 제외

        for rtype in (
                ReplyType.ENHANCE_SUCCESS,
                ReplyType.ENHANCE_KEEP,
                ReplyType.ENHANCE_BREAK,
        ):
            counts[w.id][rtype] += len(events.get(rtype, []))

    probs = {}
    for wid, c in counts.items():
        total = sum(c.values())
        if total == 0:
            continue

        probs[wid] = {
            rtype: c[rtype] / total
            for rtype in c
        }

    return probs


def gold_bin(gold: int, bin_size: int = 1_000_000) -> int:
    return gold // bin_size * bin_size


def compute_probs_by_gold(
        enhance_events: Dict[WeaponInfo, Dict[ReplyType, list]],
        *,
        bin_size: int = 1_000_000,
) -> Dict[int, Dict[ReplyType, float]]:
    """
    반환:
      {
        gold_bin: {
            ReplyType.ENHANCE_SUCCESS: p_s,
            ReplyType.ENHANCE_KEEP: p_k,
            ReplyType.ENHANCE_BREAK: p_b,
        }
      }
    """
    counts = defaultdict(lambda: defaultdict(int))

    for events in enhance_events.values():
        for rtype in (
                ReplyType.ENHANCE_SUCCESS,
                ReplyType.ENHANCE_KEEP,
                ReplyType.ENHANCE_BREAK,
        ):
            for gold, _ts in events.get(rtype, []):
                gb = gold_bin(gold, bin_size)
                counts[gb][rtype] += 1

    probs = {}
    for gb, c in counts.items():
        total = sum(c.values())
        if total == 0:
            continue

        probs[gb] = {
            rtype: c[rtype] / total
            for rtype in c
        }

    return probs


def compute_level_group_stats(
        enhance_events: Dict[WeaponInfo, Dict[ReplyType, list]],
        *,
        special_ids: Set[int],
) -> Dict[int, Dict[str, dict]]:
    """
    반환 구조:
      stats[level][group] = {
          "n": int,
          ReplyType.ENHANCE_SUCCESS: {"k": int, "p": float, "ci": (low, high)},
          ReplyType.ENHANCE_KEEP   : ...
          ReplyType.ENHANCE_BREAK  : ...
      }
    group in {"special", "normal"}
    """
    outcomes = (
        ReplyType.ENHANCE_SUCCESS,
        ReplyType.ENHANCE_KEEP,
        ReplyType.ENHANCE_BREAK,
    )

    # counts[level][group][rtype] = k
    counts = defaultdict(lambda: {
        "special": defaultdict(int),
        "normal": defaultdict(int),
    })

    for w, events in enhance_events.items():
        if w.id is None:
            continue  # 분류 불가
        lvl = w.level
        group = "special" if w.id in special_ids else "normal"
        for rtype in outcomes:
            counts[lvl][group][rtype] += len(events.get(rtype, []))

    stats: Dict[int, Dict[str, dict]] = {}
    for lvl, by_group in counts.items():
        stats[lvl] = {}
        for group, c in by_group.items():
            n = sum(c.get(rt, 0) for rt in outcomes)
            if n == 0:
                continue

            row = {"n": n}
            for rt in outcomes:
                k = int(c.get(rt, 0))
                p = k / n
                low, high = wilson_ci(k, n, z=1.96)
                row[rt] = {"k": k, "p": p, "ci": (low, high)}
            stats[lvl][group] = row

    return stats


def plot_weapon_id_pca(prob_by_id: dict):
    """
    prob_by_id:
      { id: {ReplyType.SUCCESS: p_s, KEEP: p_k, BREAK: p_b} }
    """
    ids = []
    X = []

    for wid, p in prob_by_id.items():
        if ReplyType.ENHANCE_BREAK not in p:
            continue
        ids.append(wid)
        X.append([
            p.get(ReplyType.ENHANCE_SUCCESS, 0.0),
            p.get(ReplyType.ENHANCE_KEEP, 0.0),
            p.get(ReplyType.ENHANCE_BREAK, 0.0),
        ])

    X = np.array(X)

    Z = PCA(n_components=2).fit_transform(X)

    plt.figure(figsize=(7, 6))
    sc = plt.scatter(Z[:, 0], Z[:, 1], c=X[:, 2], cmap="Reds", s=40)
    plt.colorbar(sc, label="P(BREAK)")
    plt.xlabel("PC1")
    plt.ylabel("PC2")
    plt.title("Weapon ID enhancement behavior (PCA)")
    plt.show()


def plot_weapon_prob_heatmap(prob_by_id: dict, top_n=None):
    rows = []
    for wid, p in prob_by_id.items():
        rows.append({
            "id": wid,
            "SUCCESS": p.get(ReplyType.ENHANCE_SUCCESS, 0.0),
            "KEEP": p.get(ReplyType.ENHANCE_KEEP, 0.0),
            "BREAK": p.get(ReplyType.ENHANCE_BREAK, 0.0),
        })

    df = pd.DataFrame(rows).set_index("id")
    df = df.sort_values("BREAK", ascending=False)

    if top_n:
        df = df.head(top_n)

    plt.figure(figsize=(6, max(6, 0.25 * len(df))))
    plt.imshow(df.values, aspect="auto", cmap="viridis")
    plt.colorbar(label="Probability")
    plt.yticks(range(len(df)), df.index)
    plt.xticks(range(3), df.columns)
    plt.title("Enhancement probabilities by weapon id")
    plt.show()


def summarize_weapon_risk(prob_by_id, top_k=10):
    scores = []
    for wid, p in prob_by_id.items():
        score = p.get(ReplyType.ENHANCE_BREAK, 0) - p.get(ReplyType.ENHANCE_SUCCESS, 0)
        scores.append((wid, score))

    scores.sort(key=lambda x: x[1], reverse=True)

    print("Most risky weapon ids:")
    for wid, s in scores[:top_k]:
        print(f"  id={wid:4d}  risk={s:.3f}")

    print("\nMost stable weapon ids:")
    for wid, s in scores[-top_k:]:
        print(f"  id={wid:4d}  risk={s:.3f}")


def print_gold_table(prob_by_gold: Dict[int, Dict[ReplyType, float]], *, top_n: int = 30) -> None:
    """
    Print a compact table of gold bins sorted by bin (ascending).
    """
    rows = []
    for gb, p in prob_by_gold.items():
        rows.append({
            "gold_bin": gb,
            "P_SUCCESS": p.get(ReplyType.ENHANCE_SUCCESS, 0.0),
            "P_KEEP": p.get(ReplyType.ENHANCE_KEEP, 0.0),
            "P_BREAK": p.get(ReplyType.ENHANCE_BREAK, 0.0),
        })

    if not rows:
        print("[Gold] No data to print.")
        return

    df = pd.DataFrame(rows).sort_values("gold_bin").head(int(top_n))
    print("\nGold-bin probabilities (first rows):")
    print(df.to_string(index=False))


def print_level_group_stats_side_by_side(
        stats: Dict[int, Dict[str, dict]]
) -> None:
    """
    level별로 special / normal을 한 줄에 나란히 출력
    """
    print("\n===== Level-wise probabilities (SPECIAL vs NORMAL, side-by-side) =====")
    print(
        "level |  n(sp)  SUCCESS        KEEP           BREAK     ||"
        "  n(nm)  SUCCESS        KEEP           BREAK"
    )
    print(
        "-------------------------------------------------------------------------------"
        "--------------------------------------------"
    )

    def fmt(row: dict, rt: ReplyType) -> str:
        p = row[rt]["p"]
        low, high = row[rt]["ci"]
        half = (high - low) / 2.0
        return f"{p:6.3f}±{half:6.3f}"

    for lvl in sorted(stats):
        sp = stats[lvl].get("special")
        nm = stats[lvl].get("normal")

        # special 쪽
        if sp is not None:
            n_sp = sp["n"]
            sp_s = fmt(sp, ReplyType.ENHANCE_SUCCESS)
            sp_k = fmt(sp, ReplyType.ENHANCE_KEEP)
            sp_b = fmt(sp, ReplyType.ENHANCE_BREAK)
        else:
            n_sp, sp_s, sp_k, sp_b = "-", "   -   ", "   -   ", "   -   "

        # normal 쪽
        if nm is not None:
            n_nm = nm["n"]
            nm_s = fmt(nm, ReplyType.ENHANCE_SUCCESS)
            nm_k = fmt(nm, ReplyType.ENHANCE_KEEP)
            nm_b = fmt(nm, ReplyType.ENHANCE_BREAK)
        else:
            n_nm, nm_s, nm_k, nm_b = "-", "   -   ", "   -   ", "   -   "

        print(
            f"{lvl:5d} |"
            f" {str(n_sp):>6s}  {sp_s:>12s}  {sp_k:>12s}  {sp_b:>12s} ||"
            f" {str(n_nm):>6s}  {nm_s:>12s}  {nm_k:>12s}  {nm_b:>12s}"
        )

    print(
        "============================================================================="
        "============================================\n"
    )


def compute_sell_stats_by_level_and_special(
        sell_events: Dict[WeaponInfo, List[Tuple[int, object]]],  # object = TimestampT
        *,
        special_ids: Set[int],
) -> Dict[int, Dict[str, dict]]:
    """
    SELL 수익(=gold)만을 대상으로 level별 special/normal을 나눠 평균과 표준편차를 계산.

    반환:
      stats[level][group] = {
          "n": int,
          "mean": float,
          "std": float,   # sample std (ddof=1), n<2이면 0.0
      }
    """
    values = defaultdict(lambda: {"special": [], "normal": []})

    for w, xs in sell_events.items():
        if w.id is None:
            continue  # 분류 불가
        lvl = w.level
        group = "special" if w.id in special_ids else "normal"

        for gold, _ts in xs:
            values[lvl][group].append(float(gold))

    stats: Dict[int, Dict[str, dict]] = {}
    for lvl, by_group in values.items():
        stats[lvl] = {}
        for group, arr in by_group.items():
            n = len(arr)
            if n == 0:
                continue
            mean = sum(arr) / n
            if n >= 2:
                var = sum((x - mean) ** 2 for x in arr) / (n - 1)
                std = math.sqrt(var)
            else:
                std = 0.0
            stats[lvl][group] = {"n": n, "mean": mean, "std": std}

    return stats


def print_sell_stats_side_by_side(stats: Dict[int, Dict[str, dict]]) -> None:
    print("\n===== SELL revenue stats by level (SPECIAL vs NORMAL) =====")
    print("level |  n(sp)   mean(sp)    std(sp)   ||  n(nm)   mean(nm)    std(nm)")
    print("-----------------------------------------------------------------------")

    for lvl in sorted(stats):
        sp = stats[lvl].get("special")
        nm = stats[lvl].get("normal")

        if sp:
            n_sp, m_sp, s_sp = sp["n"], sp["mean"], sp["std"]
            sp_str = f"{n_sp:6d}  {m_sp:10.1f}  {s_sp:8.1f}"
        else:
            sp_str = f"{'-':>6s}  {'-':>10s}  {'-':>8s}"

        if nm:
            n_nm, m_nm, s_nm = nm["n"], nm["mean"], nm["std"]
            nm_str = f"{n_nm:6d}  {m_nm:10.1f}  {s_nm:8.1f}"
        else:
            nm_str = f"{'-':>6s}  {'-':>10s}  {'-':>8s}"

        print(f"{lvl:5d} | {sp_str} || {nm_str}")

    print("=======================================================================\n")
