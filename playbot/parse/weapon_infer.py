from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Literal, Union, Set, Dict, Tuple, Callable, Optional, List

from playbot.types import ReplyType, WeaponInfo, ReplyInfo
from playbot.weaponbook import crawl_all_hierarchies_by_clicking, WeaponBook


# =========================
# Policy
# =========================

@dataclass(frozen=True)
class WeaponIdPolicy:
    """
    mode:
      - online: 리로드 최소화 + 휴리스틱 계승
      - batch: weapon_index가 최신이라는 가정 하에 최대한 교집합으로 정확히

    online에서는 "SUCCESS & 레벨 +1"이면 id를 계승(=후보 집합 유지)하는 최적화를 기본 제공.
    """
    mode: Literal["online", "batch"] = "online"

    # ---- online 휴리스틱/검증 ----
    online_inherit_on_success_level_up: bool = True
    online_validate_with_index_on_normal_steps: bool = False
    # (False면 평상시엔 weapon_index 교집합 검증을 생략하고,
    #  mismatch/종료 후 재시작/초기화 등 "필요할 때만" index를 사용)

    # ---- reload 정책 ----
    enable_reload: bool = True
    reload_on_missing_key: bool = False
    reload_on_termination_then_missing: bool = True  # SELL/BREAK 이후 새 트랙 시작에서만 missing이면 reload
    keep_candidates_when_after_unindexed: bool = True
    reload_cooldown_sec: float = 30.0
    max_reload_calls: int = 2  # 한 번의 assign 수행 중 최대 호출 횟수 제한


# =========================
# Helpers
# =========================

IdLike = Union[int, Set[int], None]
WeaponIndex = Dict[Tuple[str, int], Set[int]]
SpecialId = List[int]
ReloadFn = Callable[[], Tuple[SpecialId, WeaponIndex]]


def _to_set(x: IdLike) -> Optional[Set[int]]:
    if x is None:
        return None
    if isinstance(x, set):
        return set(x)
    return {int(x)}


def _safe_timestamp_seconds(ts: object) -> Optional[float]:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, datetime):
        return ts.timestamp()
    for attr in ("timestamp", "to_pydatetime"):
        if hasattr(ts, attr):
            try:
                v = getattr(ts, attr)()
                if isinstance(v, datetime):
                    return v.timestamp()
                if isinstance(v, (int, float)):
                    return float(v)
            except Exception:
                pass
    return None


def _expected_level_relation(reply_type: ReplyType) -> Optional[int]:
    if reply_type == ReplyType.ENHANCE_SUCCESS:
        return +1
    if reply_type == ReplyType.ENHANCE_KEEP:
        return 0
    return None


def _resolve_key(w: Optional[WeaponInfo]) -> Optional[Tuple[str, int]]:
    if w is None:
        return None
    return (w.name, w.level)


def _set_weapon_id(w: Optional[WeaponInfo], resolved_id: Optional[int]) -> Optional[WeaponInfo]:
    if w is None:
        return None
    return replace(w, id=resolved_id)


def _resolved_id_from_candidates(cands: Optional[Set[int]]) -> Optional[int]:
    if cands is None:
        return None
    if len(cands) == 1:
        return next(iter(cands))
    return None


# =========================
# Reload function
# =========================
def make_reload_cb(
        *,
        bot_user_key: str,
        bot_group_key: str,
        tree_out_dir: str,
        cache: WeaponBook,
) -> Callable[[], None]:
    """
    반환: () -> None
    리로드하면 cache.weapon_index, cache.special_ids 둘 다 갱신
    """
    from selenium import webdriver

    def _reload() -> None:
        driver = webdriver.Chrome()
        try:
            hierarchies, special_ids, weapon_index = crawl_all_hierarchies_by_clicking(
                driver=driver,
                bot_user_key=bot_user_key,
                bot_group_key=bot_group_key,
                out_dir=tree_out_dir,
                sort="enhancement",
                max_tiles=None,
            )
        finally:
            driver.quit()

        cache.update(hierarchies=hierarchies, weapon_index=weapon_index, special_ids=special_ids)

    return _reload


# =========================
# Core assignment
# =========================


def assign_weapon_ids(
        replies: List[ReplyInfo],
        book: WeaponBook,
        previous_weapon_id: IdLike = None,
        *,
        reload_weapon_book: Optional[Callable[[], None]] = None,
        policy: WeaponIdPolicy = WeaponIdPolicy(),
) -> List[ReplyInfo]:
    """
    - ENHANCE*, SELL만 무기 상태를 가지며 id를 주입한다.
    - 기타 타입(BUSY, INSUFFICIENT_GOLD 등)은 weapon_before/after가 항상 None이므로,
      ReplyInfo를 수정하지 않고 그대로 통과한다.
    - 트랙 내에서 어떤 시점에 id가 resolve(단일 후보)되면, 그 이전에 같은 트랙으로 이어졌던
      미확정 reply들에도 소급(backfill)하여 id를 채운다.
    """

    # ---- state ----
    cands: Optional[Set[int]] = _to_set(previous_weapon_id)  # 현재 트랙 후보
    last_after: Optional[WeaponInfo] = None  # 연결용 직전 after
    terminated_prev: bool = False  # 직전이 SELL/BREAK였는지

    # backfill: 현 트랙에서 아직 id 미확정인 out 인덱스들
    pending_idxs: List[int] = []

    # reload throttle
    reload_calls = 0
    last_reload_sec: Optional[float] = None

    def can_reload(now_sec: Optional[float]) -> bool:
        nonlocal reload_calls, last_reload_sec
        if not policy.enable_reload:
            return False
        if reload_calls >= policy.max_reload_calls:
            return False
        if now_sec is None or last_reload_sec is None:
            return True
        return (now_sec - last_reload_sec) >= policy.reload_cooldown_sec

    def maybe_reload(now_sec: Optional[float]) -> None:
        nonlocal reload_calls, last_reload_sec
        if can_reload(now_sec):
            reload_weapon_book()
            reload_calls += 1
            last_reload_sec = now_sec

    def lookup_candidates(
            key: Optional[Tuple[str, int]],
            now_sec: Optional[float],
            *,
            allow_reload: bool,
    ) -> Optional[Set[int]]:
        if key is None:
            return None
        s = book.weapon_index.get(key)
        if s is not None:
            return set(s)
        if allow_reload and reload_weapon_book is not None:
            maybe_reload(now_sec)  # 내부 throttling 유지
            reload_weapon_book()  # cache 갱신 (weapon_index + special_ids)
            s2 = book.weapon_index.get(key)
            return set(s2) if s2 is not None else None
        return None

    out: List[ReplyInfo] = []

    def apply_backfill(resolved_id: int) -> None:
        """현재 트랙에서 id가 비어있던 reply들을 소급해서 채움."""
        nonlocal pending_idxs, out
        if not pending_idxs:
            return
        for j in pending_idxs:
            rr = out[j]
            nb = _set_weapon_id(rr.weapon_before, resolved_id)
            na = _set_weapon_id(rr.weapon_after, resolved_id)
            out[j] = replace(rr, weapon_before=nb, weapon_after=na)
        pending_idxs.clear()

    for idx_r, r in enumerate(replies):
        now_sec = _safe_timestamp_seconds(r.timestamp)

        is_enhance = r.type in (ReplyType.ENHANCE_SUCCESS, ReplyType.ENHANCE_KEEP, ReplyType.ENHANCE_BREAK)
        is_sell = r.type == ReplyType.SELL
        is_terminate = (r.type == ReplyType.ENHANCE_BREAK) or is_sell

        # ------------------------------------------------------------
        # 기타 타입: 무기 정보가 없으므로 그대로 통과 (상태도 유지)
        # ------------------------------------------------------------
        if (not is_enhance) and (not is_sell):
            out.append(r)
            continue

        # 여기부터는 ENHANCE* 또는 SELL만 다룸
        before = r.weapon_before
        after = r.weapon_after

        before_key = _resolve_key(before)
        after_key = _resolve_key(after)

        # ------------------------------------------------------------
        # termination (BREAK/SELL): 트랙 종료
        # ------------------------------------------------------------
        if is_terminate:
            resolved = _resolved_id_from_candidates(cands)
            new_before = _set_weapon_id(r.weapon_before, resolved)
            new_after = _set_weapon_id(r.weapon_after, None)
            out.append(replace(r, weapon_before=new_before, weapon_after=new_after))

            if resolved is not None:
                apply_backfill(resolved)
            else:
                pending_idxs.clear()

            # 상태 리셋
            cands = None
            last_after = r.weapon_after if r.weapon_after is not None else last_after
            terminated_prev = True
            continue

        # ------------------------------------------------------------
        # SUCCESS/KEEP 처리
        # ------------------------------------------------------------
        expected_delta = _expected_level_relation(r.type)

        # 관측 기반 mismatch 탐지(보조 신호)
        mismatch = False
        if expected_delta is not None and before is not None and after is not None:
            if (after.level - before.level) != expected_delta:
                mismatch = True

        # online 최적화: SUCCESS + level-up이면 후보 유지(계승)
        allow_fast_inherit = (
                policy.mode == "online"
                and policy.online_inherit_on_success_level_up
                and r.type == ReplyType.ENHANCE_SUCCESS
                and not terminated_prev
                and not mismatch
        )

        # after로부터 후보를 얻을지 결정
        need_index_validation = (
                policy.mode == "batch"
                or policy.online_validate_with_index_on_normal_steps
                or cands is None
                or mismatch
                or terminated_prev
        )

        # reload 허용 조건
        if policy.mode == "batch":
            allow_reload = False
        else:
            allow_reload = policy.reload_on_missing_key or (
                    terminated_prev and policy.reload_on_termination_then_missing)

        after_cands: Optional[Set[int]] = None
        if after_key is not None and need_index_validation:
            after_cands = lookup_candidates(after_key, now_sec, allow_reload=allow_reload)
        elif after_key is not None and cands is None:
            # 트랙 시작인데 validation을 꺼놨더라도 초기 후보는 잡는다(리로드 없이)
            after_cands = lookup_candidates(after_key, now_sec, allow_reload=False)

        # 갱신/끊김 판정
        reset_track = False

        # after가 book에서 끝내 안 잡히는 경우:
        # - SUCCESS/KEEP이며 mismatch가 아니면, book 미지원으로 보고 cands를 유지(계승)한다.
        # - 단, termination 직후는 새 트랙일 수 있으므로 기존 로직을 우선한다.
        if (
                policy.keep_candidates_when_after_unindexed
                and after_key is not None
                and after_cands is None
                and not mismatch
                and not terminated_prev
        ):
            # cands 유지(아무것도 하지 않음)
            pass
        else:
            if terminated_prev:
                # SELL/BREAK 직후는 새 트랙 시작 취급
                cands = after_cands if after_cands is not None else None
                reset_track = True

            else:
                if cands is None:
                    cands = after_cands if after_cands is not None else None
                    reset_track = True

                else:
                    if allow_fast_inherit:
                        if after_cands is not None:
                            inter = cands & after_cands
                            if len(inter) == 0:
                                cands = after_cands
                                reset_track = True
                            else:
                                cands = inter
                        # after_cands None이면: 유지 (위 if에서 이미 pass 처리될 수도 있고, 아니면 여기서도 유지)
                    else:
                        if after_cands is not None:
                            inter = cands & after_cands
                            if len(inter) == 0:
                                cands = after_cands
                                reset_track = True
                            else:
                                cands = inter
                        # after_cands None이면: 유지(online), batch도 일단 유지 (원하면 batch에서는 degrade 가능)

        if reset_track:
            pending_idxs.clear()

        resolved = _resolved_id_from_candidates(cands)

        new_before = _set_weapon_id(r.weapon_before, resolved)
        new_after = _set_weapon_id(r.weapon_after, resolved)
        out.append(replace(r, weapon_before=new_before, weapon_after=new_after))

        if resolved is None:
            pending_idxs.append(len(out) - 1)
        else:
            apply_backfill(resolved)

        # 상태 업데이트
        last_after = new_after if new_after is not None else r.weapon_after
        terminated_prev = False

    ###### Summary #######
    total = len(out)

    type_counter = Counter(r.type for r in out)

    success_cnt = type_counter.get(ReplyType.ENHANCE_SUCCESS, 0)
    keep_cnt    = type_counter.get(ReplyType.ENHANCE_KEEP, 0)
    break_cnt   = type_counter.get(ReplyType.ENHANCE_BREAK, 0)
    sell_cnt    = type_counter.get(ReplyType.SELL, 0)

    considered_types = {
        ReplyType.ENHANCE_SUCCESS,
        ReplyType.ENHANCE_KEEP,
        ReplyType.ENHANCE_BREAK,
        ReplyType.SELL,
    }

    considered_cnt = 0
    resolved_cnt = 0
    unresolved_cnt = 0

    for r in out:
        if r.type not in considered_types:
            continue

        considered_cnt += 1

        wb = r.weapon_before
        wa = r.weapon_after

        has_any_id = (
            (wb is not None and wb.id is not None)
            or (wa is not None and wa.id is not None)
        )

        if has_any_id:
            resolved_cnt += 1
        else:
            unresolved_cnt += 1

    print("===== assign_weapon_ids summary =====")
    print(f"total replies            : {total}")
    print(f"  enhance_success        : {success_cnt}")
    print(f"  enhance_keep           : {keep_cnt}")
    print(f"  enhance_break          : {break_cnt}")
    print(f"  sell                   : {sell_cnt}")
    print("-------------------------------------")
    print(f"considered (ENHANCE/SELL): {considered_cnt}")
    print(f"resolved replies         : {resolved_cnt}")
    print(f"unresolved replies       : {unresolved_cnt}")
    print("=====================================")

    return out


def save_unresolved_replies_log(
    out: List[ReplyInfo],
    log_path: str,
    *,
    include_header: bool = True,
) -> int:
    """
    unresolved replies를 로그 파일로 저장한다.

    unresolved 정의(수정):
      - type이 ENHANCE_* 또는 SELL 인 reply만 고려
      - 그 중 weapon_before/after 둘 다 없거나, 둘 다 id가 None이면 unresolved
    """
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    enhance_sell_types = {
        ReplyType.ENHANCE_SUCCESS,
        ReplyType.ENHANCE_KEEP,
        ReplyType.ENHANCE_BREAK,
        ReplyType.SELL,
    }

    def _fmt_ts(ts: Optional[object]) -> str:
        if ts is None:
            return "-"
        if isinstance(ts, datetime):
            return ts.isoformat(sep=" ", timespec="seconds")
        return str(ts)

    def _fmt_weapon(w: Optional[WeaponInfo]) -> str:
        if w is None:
            return "-"
        return f"[+{w.level}] {w.name} (id={w.id})"

    unresolved_idx = []
    for i, r in enumerate(out):
        if r.type not in enhance_sell_types:
            continue  # BUSY/INSUFFICIENT_GOLD 등은 고려하지 않음

        wb = r.weapon_before
        wa = r.weapon_after

        has_any_weapon = (wb is not None) or (wa is not None)
        has_any_id = ((wb is not None and wb.id is not None) or (wa is not None and wa.id is not None))

        if (not has_any_weapon) or (not has_any_id):
            unresolved_idx.append(i)

    with p.open("w", encoding="utf-8") as f:
        if include_header:
            f.write("===== unresolved replies log =====\n")
            f.write(f"generated_at: {datetime.now().isoformat(sep=' ', timespec='seconds')}\n")
            f.write(f"total_out: {len(out)}\n")
            f.write(f"considered_types: {sorted(t.value for t in enhance_sell_types)}\n")
            f.write(f"unresolved_count: {len(unresolved_idx)}\n")
            f.write("==================================\n\n")

        for i in unresolved_idx:
            r = out[i]
            f.write(f"#{i}\n")
            f.write(f"  type: {r.type}\n")
            f.write(f"  timestamp: {_fmt_ts(r.timestamp)}\n")
            f.write(f"  weapon_before: {_fmt_weapon(r.weapon_before)}\n")
            f.write(f"  weapon_after : {_fmt_weapon(r.weapon_after)}\n")
            if r.gold_after is not None:
                f.write(f"  gold_after: {r.gold_after}\n")
            if r.cost is not None:
                f.write(f"  cost: {r.cost}\n")
            if r.reward is not None:
                f.write(f"  reward: {r.reward}\n")
            if r.raw_main:
                f.write(f"  raw_main: {r.raw_main}\n")
            if r.raw_aux:
                f.write(f"  raw_aux : {r.raw_aux}\n")
            f.write("\n")

    return len(unresolved_idx)

# =========================
# Usage examples
# =========================
#
# 1) Online (실시간): reload 최소화, SUCCESS(+1)이면 기본 계승
#
# policy = WeaponIdPolicy(
#     mode="online",
#     reload_on_missing_key=False,
#     reload_on_termination_then_missing=True,
#     online_validate_with_index_on_normal_steps=False,
# )
# replies2 = assign_weapon_ids(
#     replies,
#     weapon_index,
#     previous_weapon_id=prev_id_or_candidates,
#     reload_weapon_index=reload_cb,   # Optional
#     policy=policy,
# )
#
# 2) Batch (사후 분석): 최신 weapon_index 가정 + 최대 정확도(필요 시 reload도 허용)
#
# policy = WeaponIdPolicy(mode="batch", enable_reload=True)
# replies2 = assign_weapon_ids(replies, weapon_index, policy=policy, reload_weapon_index=reload_cb)
"""
# 초기 book 로딩 결과가 있다고 가정
book = WeaponBookCache(weapon_index=weapon_index, special_ids=list(special_ids))

reload_cb = make_reload_cb(
    bot_user_key=BOT_USER_KEY,
    bot_group_key=BOT_GROUP_KEY,
    tree_out_dir=TREE_OUT_DIR,
    cache=book,
    crawl_fn=crawl_all_hierarchies_by_clicking,
)

replies2 = assign_weapon_ids(
    replies=replies,
    book=book,
    previous_weapon_id=prev_id,
    reload_weapon_book=reload_cb,
    policy=WeaponIdPolicy(mode="online", reload_on_termination_then_missing=True),
)

# 항상 최신 special_ids
latest_special_ids = book.special_ids
"""
