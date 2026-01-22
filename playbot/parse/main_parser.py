import re
from dataclasses import dataclass
from typing import Tuple, Optional, List, Iterable

import pandas as pd

from playbot.utils import _to_int
from .known_errors import KNOWN_WEAPON_MISMATCH
from playbot.types import ReplyInfo, ReplyType, WeaponInfo, UserCommand, UserCommandTarget, MacroAction, TimestampT

# TODO: add run out of money

# =========================
# Regex / parsing helpers
# =========================

# gold/cost/reward
RE_COST = re.compile(r"사용 골드\s*:\s*-\s*([\d,]+)G")
RE_GOLD_AFTER_1 = re.compile(r"남은 골드\s*:\s*([\d,]+)G")
RE_GOLD_AFTER_2 = re.compile(r"현재 보유 골드\s*:\s*([\d,]+)G")
RE_REWARD = re.compile(r"획득 골드\s*:\s*\+\s*([\d,]+)G")

# enhance success
RE_SUCC_HDR = re.compile(r"강화 성공.*?\+(\d+)\s*→\s*\+(\d+)")
RE_SUCC_GAIN = re.compile(r"획득\s*검\s*:\s*\[\+(\d+)\]\s*([^\n\r]+)")

# enhance keep
RE_KEEP = re.compile(r"강화 유지")
RE_KEEP_LINE = re.compile(r"『\s*\[\+(\d+)\]\s*([^\]』]+?)\s*』.*?레벨이 유지", re.S)

# enhance break (main)
RE_BREAK = re.compile(r"강화 파괴")

# break notice (aux)
RE_BREAK_NOTICE = re.compile(
    r"『\s*\[\+(\d+)\]\s*([^\]』]+?)\s*』\s*산산조각.*?『\s*\[\+(\d+)\]\s*([^\]』]+?)\s*』\s*지급",
    re.S
)

# sell
RE_SELL = re.compile(r"검 판매")
RE_SELL_SOLD = re.compile(r"'\s*\[\+(\d+)\]\s*([^']+?)\s*'")  # 판매된 무기: '[+10] ...'
RE_SELL_NEW = re.compile(r"새로운\s*검\s*획득\s*:\s*\[\+(\d+)\]\s*([^\n\r]+)")

# busy
RE_BUSY = re.compile(r"강화 중이니\s*잠깐\s*기다리도록")

# insufficient gold (첫 메시지)
RE_NO_GOLD = re.compile(r"골드가\s*부족해")
RE_NEED_GOLD = re.compile(r"필요\s*골드\s*:\s*([\d,]+)G")
RE_LEFT_GOLD = re.compile(r"남은\s*골드\s*:\s*([\d,]+)G")

# insufficient gold (둘째 메시지: 안내/버튼류)
RE_GO_EARN_GOLD = re.compile(r"골드\s*모으러가기|출석체크|검\s*'판매'")

# user command
RE_MENTION = re.compile(r"^\s*@(\S+)\s*(.*)\s*$")  # "@대상 나머지"


def _extract_cost_gold_reward(content: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    cost = None
    m = RE_COST.search(content)
    if m:
        cost = _to_int(m.group(1))

    gold_after = None
    m = RE_GOLD_AFTER_1.search(content) or RE_GOLD_AFTER_2.search(content)
    if m:
        gold_after = _to_int(m.group(1))

    reward = None
    m = RE_REWARD.search(content)
    if m:
        reward = _to_int(m.group(1))

    return cost, gold_after, reward


def _parse_weapon_from_gain_line(content: str) -> Optional[WeaponInfo]:
    m = RE_SUCC_GAIN.search(content)
    if not m:
        return None
    lv = int(m.group(1))
    name = m.group(2).strip()
    return WeaponInfo(level=lv, name=name)


def _parse_weapon_from_keep_line(content: str) -> Optional[WeaponInfo]:
    m = RE_KEEP_LINE.search(content)
    if not m:
        return None
    lv = int(m.group(1))
    name = m.group(2).strip()
    return WeaponInfo(level=lv, name=name)


def _parse_break_notice(content: str) -> Optional[Tuple[WeaponInfo, WeaponInfo]]:
    m = RE_BREAK_NOTICE.search(content)
    if not m:
        return None
    broken = WeaponInfo(level=int(m.group(1)), name=m.group(2).strip())
    granted = WeaponInfo(level=int(m.group(3)), name=m.group(4).strip())
    return broken, granted


def _parse_sell_weapons(content: str) -> Tuple[Optional[WeaponInfo], Optional[WeaponInfo]]:
    sold = None
    m = RE_SELL_SOLD.search(content)
    if m:
        sold = WeaponInfo(level=int(m.group(1)), name=m.group(2).strip())

    new = None
    m = RE_SELL_NEW.search(content)
    if m:
        new = WeaponInfo(level=int(m.group(1)), name=m.group(2).strip())

    return sold, new


def parse_user_command(content: str, timestamp: TimestampT,
                       bot_name: str, macro_name: str = "매크로") -> Optional[UserCommand]:
    raw = content.strip()
    m = RE_MENTION.match(raw)
    if not m:
        return None

    target = m.group(1).strip()
    rest = (m.group(2) or "").strip()

    if target == macro_name:
        if rest == "중지":
            return UserCommand(target=UserCommandTarget.MACRO, raw=raw, macro_action=MacroAction.PAUSE,
                               timestamp=timestamp)
        if rest == "재개":
            return UserCommand(target=UserCommandTarget.MACRO, raw=raw, macro_action=MacroAction.RESUME,
                               timestamp=timestamp)
        return UserCommand(target=UserCommandTarget.MACRO, raw=raw, macro_action=None,
                           timestamp=timestamp)

    if target == bot_name:
        # bot_command는 그대로 저장 (예: "강화", "판매", 혹은 확장 명령)
        return UserCommand(target=UserCommandTarget.BOT, raw=raw, bot_command=rest or None,
                           timestamp=timestamp)

    return None


# =========================
# Main extraction logic
# =========================

@dataclass
class _State:
    current_weapon: Optional[WeaponInfo] = None


def extract_triplets_last(
        df: pd.DataFrame,
        user_name: str,
        bot_name: str,
        macro_name: str = "매크로",
        lookahead_max: int = 3,
        prev_weapon_id: Optional[int] = None,
) -> Tuple[ReplyInfo, UserCommand, UserCommand]:
    r, cb, cm = extract_triplets(df, user_name, bot_name, macro_name, lookahead_max)
    last_r = r[-1] if r else None
    last_cb = cb[-1] if cb else None
    last_cm = cm[-1] if cm else None
    return last_r, last_cb, last_cm


def extract_triplets(
        df: pd.DataFrame,
        user_name: str,
        bot_name: str,
        macro_name: str = "매크로",
        lookahead_max: int = 3,
) -> Tuple[List[ReplyInfo], List[UserCommand], List[UserCommand]]:
    """
    Input: DataFrame with columns: dt, seq, sender, content
    Output:
      - replies: List[ReplyInfo] (NO UNKNOWN; break merged with notice; others ignored)
      - user_bot_cmds: List[UserCommand] (target=BOT)
      - user_macro_cmds: List[UserCommand] (target=MACRO)
    """

    required_cols = {"dt", "seq", "sender", "content"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing columns: {sorted(missing)}")

    df2 = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df2["dt"]):
        df2["dt"] = pd.to_datetime(df2["dt"], errors="coerce")

    df2 = df.sort_values(["dt", "seq"]).reset_index(drop=True)

    replies: List[ReplyInfo] = []
    user_bot_cmds: List[UserCommand] = []
    user_macro_cmds: List[UserCommand] = []

    st = _State()

    i = 0
    n = len(df2)

    while i < n:
        ts = df2.at[i, "dt"]
        if pd.isna(ts):
            ts = None

        sender = str(df2.at[i, "sender"])
        content = str(df2.at[i, "content"] or "")

        # ----- User side: commands -----
        if sender == user_name:
            cmd = parse_user_command(content, timestamp=ts, bot_name=bot_name, macro_name=macro_name)
            if cmd:
                if cmd.target == UserCommandTarget.BOT:
                    user_bot_cmds.append(cmd)
                elif cmd.target == UserCommandTarget.MACRO:
                    user_macro_cmds.append(cmd)
            i += 1
            continue

        # ----- Bot side: events only (ignore non-event chatter) -----
        if sender != bot_name:
            i += 1
            continue

        cost, gold_after, reward = _extract_cost_gold_reward(content)

        # 0) BUSY (no state change)
        if RE_BUSY.search(content):
            replies.append(
                ReplyInfo(
                    type=ReplyType.BUSY,
                    raw_main=content,
                    timestamp=ts,
                )
            )
            i += 1
            continue

        # 0) INSUFFICIENT_GOLD (often followed by 1 auxiliary guidance message)
        if RE_NO_GOLD.search(content):
            need = None
            m = RE_NEED_GOLD.search(content)
            if m:
                need = _to_int(m.group(1))

            left = None
            m = RE_LEFT_GOLD.search(content)
            if m:
                left = _to_int(m.group(1))

            aux = None
            # lookahead 1~2: 보통 바로 다음 봇 메시지가 "골드 모으러가기" 안내
            for j in range(i + 1, min(i + 3, n)):
                if str(df2.at[j, "sender"]) != bot_name:
                    break
                cand = str(df2.at[j, "content"] or "")
                if RE_GO_EARN_GOLD.search(cand):
                    aux = cand
                    break

            replies.append(
                ReplyInfo(
                    type=ReplyType.INSUFFICIENT_GOLD,
                    gold_after=left,
                    raw_main=content,
                    raw_aux=aux,
                    timestamp=ts,
                )
            )
            # aux를 소비하지는 않음(원본 메시지 보존); 다만 이벤트는 1개만 생성
            i += 1
            continue

        # 1) SELL (single-message event; optional extra bot messages ignored)
        if RE_SELL.search(content):
            sold_weapon, new_weapon = _parse_sell_weapons(content)

            # weapon_before: prefer sold_weapon; else fall back to state
            weapon_before = sold_weapon or st.current_weapon
            weapon_after = new_weapon  # often [+0] 낡은 검

            if weapon_before in KNOWN_WEAPON_MISMATCH:
                weapon_before = KNOWN_WEAPON_MISMATCH[weapon_before]
            if weapon_after in KNOWN_WEAPON_MISMATCH:
                weapon_after = KNOWN_WEAPON_MISMATCH[weapon_after]

            # update state if new weapon known
            if weapon_after:
                st.current_weapon = weapon_after

            replies.append(
                ReplyInfo(
                    type=ReplyType.SELL,
                    gold_after=gold_after,
                    reward=reward,
                    weapon_before=weapon_before,
                    weapon_after=weapon_after,
                    raw_main=content,
                    timestamp=ts,
                )
            )
            i += 1
            continue

        # 2) ENHANCE SUCCESS
        mh = RE_SUCC_HDR.search(content)
        if mh:
            before_lv = int(mh.group(1))
            after_lv = int(mh.group(2))

            after_weapon = _parse_weapon_from_gain_line(content)
            if not after_weapon:
                i += 1
                continue

            # weapon_before는 level이 맞을 때만 state에서 가져옴
            weapon_before = None
            if st.current_weapon and st.current_weapon.level == before_lv:
                weapon_before = st.current_weapon

            weapon_after = after_weapon
            if weapon_after in KNOWN_WEAPON_MISMATCH:
                weapon_after = KNOWN_WEAPON_MISMATCH[weapon_after]

            # state update는 after_weapon으로만 수행
            st.current_weapon = weapon_after

            replies.append(
                ReplyInfo(
                    type=ReplyType.ENHANCE_SUCCESS,
                    gold_after=gold_after,
                    cost=cost,
                    weapon_before=weapon_before,
                    weapon_after=weapon_after,
                    raw_main=content,
                    timestamp=ts,
                )
            )
            i += 1
            continue

        # 3) ENHANCE KEEP
        if RE_KEEP.search(content):
            keep_weapon = _parse_weapon_from_keep_line(content)

            if keep_weapon in KNOWN_WEAPON_MISMATCH:
                keep_weapon = KNOWN_WEAPON_MISMATCH[keep_weapon]

            # 유지 이벤트는 현재 무기가 그대로. state를 keep_weapon로 동기화(있으면).
            if keep_weapon:
                st.current_weapon = keep_weapon

            replies.append(
                ReplyInfo(
                    type=ReplyType.ENHANCE_KEEP,
                    gold_after=gold_after,
                    cost=cost,
                    weapon_before=keep_weapon,  # 동기화 이후라 before/after 같음
                    weapon_after=keep_weapon,
                    raw_main=content,
                    timestamp=ts,
                )
            )
            i += 1
            continue

        # 4) ENHANCE BREAK (merge with notice ONLY; otherwise ignore)
        if RE_BREAK.search(content):
            # lookahead: next bot messages for break notice
            aux = None
            broken_granted = None

            for j in range(i + 1, min(i + 1 + lookahead_max, n)):
                if str(df2.at[j, "sender"]) != bot_name:
                    break
                cand = str(df2.at[j, "content"] or "")
                bg = _parse_break_notice(cand)
                if bg:
                    aux = cand
                    broken_granted = bg
                    break

            # 정책: 파괴 이벤트는 "공지 메시지"가 있어야만 ReplyInfo 생성 (UNKNOWN 제거 조건)
            if not broken_granted:
                i += 1
                continue

            broken_weapon, granted_weapon = broken_granted
            if broken_weapon in KNOWN_WEAPON_MISMATCH:
                broken_weapon = KNOWN_WEAPON_MISMATCH[broken_weapon]
            if granted_weapon in KNOWN_WEAPON_MISMATCH:
                granted_weapon = KNOWN_WEAPON_MISMATCH[granted_weapon]

            # weapon_before/after: state 기반 + notice 기반을 조합
            # notice가 가장 신뢰할 수 있으므로 broken/granted를 그대로 사용
            weapon_before = broken_weapon
            weapon_after = granted_weapon

            # state update to granted weapon
            st.current_weapon = granted_weapon

            replies.append(
                ReplyInfo(
                    type=ReplyType.ENHANCE_BREAK,
                    gold_after=gold_after,
                    cost=cost,
                    weapon_before=weapon_before,
                    weapon_after=weapon_after,
                    raw_main=content,
                    raw_aux=aux,
                    timestamp=ts,
                )
            )
            i += 1
            continue

        # 5) Everything else from bot is ignored (no UNKNOWN output)
        i += 1

    return replies, user_bot_cmds, user_macro_cmds


@dataclass
class CurrentState:
    gold: Optional[int] = None
    weapon: Optional[WeaponInfo] = None


def extract_current_gold_and_weapon(
    replies: Iterable[ReplyInfo],
) -> CurrentState:
    """
    ReplyInfo 스트림에서 '현재 골드'와 '현재 무기'를 추출한다.

    규칙:
    - gold: ReplyInfo.gold_after가 None이 아니면 그 값을 현재 골드로 갱신
      (INSUFFICIENT_GOLD는 gold_after에 남은 골드가 들어오도록 해둔 설계를 가정)
    - weapon: ReplyInfo.weapon_after(또는 granted_weapon)가 있으면 그 값을 현재 무기로 갱신
      - 성공/유지/판매/파괴 모두 weapon_after가 세팅되도록 해두면 일관적
    """
    st = CurrentState()

    for r in replies:
        # gold update
        if r.gold_after is not None:
            st.gold = r.gold_after

        # weapon update (prefer explicit granted_weapon for break, but weapon_after should already be same)
        if r.weapon_after is not None:
            st.weapon = r.weapon_after

    return st


def extract_current_gold(replies: Iterable[ReplyInfo]) -> Optional[int]:
    return extract_current_gold_and_weapon(replies).gold


def extract_current_weapon(replies: Iterable[ReplyInfo]) -> Optional[WeaponInfo]:
    return extract_current_gold_and_weapon(replies).weapon
