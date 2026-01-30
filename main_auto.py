import time
from typing import Optional, Tuple

from pynput import keyboard

from config import load_username, load_botgroupkey, load_botuserkey
from playbot.interact import StopFlag, start_emergency_listener, calibrate_click, select_all_copy_verified, \
    send_command, wait_for_bot_turn, get_last_sender, refresh_chat_window_safe
from playbot.parse import parse_kakao, extract_triplets, extract_triplets_last, extract_current_weapon, \
    extract_current_gold, make_reload_cb, WeaponIdPolicy, assign_weapon_ids

# =========================
# Settings
# =========================
from playbot.analysis import load_dictionary, build_count_tables
from playbot.strategy.strategy import build_sell_tables, optimal_strategy_for_weapon
from playbot.types import WeaponInfo, MacroAction, RawData
from playbot.weaponbook import load_weapon_book

USER_NAME = load_username()
BOT_SENDER_NAME = "플레이봇"  # 복사 텍스트에서 [플레이봇] 형태로 나타나는 발화자
BOT_MENTION_NAME = "플레이봇"  # 멘션 자동완성에서 클릭할 이름(동일하면 그대로)

COMMAND_ENHANCE = "강화"
COMMAND_SELL = "판매"

BOT_USER_KEY = load_botuserkey()
BOT_GROUP_KEY = load_botgroupkey()

# 비상탈출 키
EXIT_KEY = keyboard.Key.f12
PAUSE_KEY = keyboard.Key.f11
STOP = StopFlag(EXIT_KEY, PAUSE_KEY)

# 채팅방 재오픈
REFRESH_EVERY = 1000

# 백업 클릭 위치 (모니터 해상도가 작을 때 추천)
USE_BACKUP_CHAT_CLICK = True

# Decision by analysis
USE_STATISTICS = True
WEAPON_TREE_DIR = "data/weapon_trees"


# =========================
# 의사결정 로직
# =========================
def decide_next_command(weapon: WeaponInfo, gold: int, **kwargs) -> Tuple[Optional[str], str]:
    level = weapon.level
    # if level >= 20:
    #     return None, f"종료: 레벨 {level} >= 20"
    threshold_table = {
        9: 500_000,
        10: 1_000_000,
        11: 2_000_000,
        12: 3_000_000,
        13: 5_000_000,
        14: 7_000_000,
        15: 10_000_000,
        16: 12_000_000,
        17: 20_000_000,
    }
    if level <= 8:
        return COMMAND_ENHANCE, f"레벨 {level} ≤ 8 → 강화"

    if level >= 18:
        return COMMAND_SELL, f"레벨 {level} >= 18 → 판매"
    if USE_STATISTICS:
        # Confidence thresholds (tune as needed)
        MIN_N = 20
        MAX_BREAK_ERR = 0.1  # Wilson 95% CI half-width for BREAK

        decisions = optimal_strategy_for_weapon(
            start_level=level,
            weapon_id=weapon.id,
            special_ids=kwargs["special_set"],

            # NEW: counts for hierarchical backoff
            idlvl_cnt=kwargs["idlvl_cnt"],
            grplvl_cnt=kwargs["grplvl_cnt"],
            lvl_cnt=kwargs["lvl_cnt"],

            # SELL stats
            sell_idlvl=kwargs["sell_idlvl"],
            sell_grplvl=kwargs["sell_grplvl"],
            sell_lvl=kwargs["sell_lvl"],

            min_n=MIN_N,
            max_break_err=MAX_BREAK_ERR,

            max_level=16,
        )

        d = decisions.get(level)
        if d is None:
            # 통계 계산 실패 시 안전한 fallback
            return COMMAND_SELL, f"레벨 {level}: 통계 부족 → 안전 판매"

        if d.action == "ENHANCE":
            return (
                COMMAND_ENHANCE,
                (
                    f"[통계] 레벨 {level} → 강화 "
                    f"(E[강화]={d.V_enh:,.0f}, E[판매]={d.S:,.0f}, "
                    f"p_b={d.pb:.3f}, n={d.n_prob})"
                ),
            )
        else:
            return (
                COMMAND_SELL,
                (
                    f"[통계] 레벨 {level} → 판매 "
                    f"(E[판매]={d.S:,.0f} ≥ E[강화]={d.V_enh:,.0f}, "
                    f"p_b={d.pb:.3f}, n={d.n_prob})"
                ),
            )
    else:
        threshold = threshold_table[level]
        if gold < threshold:
            return COMMAND_SELL, f"레벨 {level}, 골드 {gold:,} < 판매 기준 {threshold:,} → 판매"
        return COMMAND_ENHANCE, f"레벨 {level}, 골드 {gold:,} ≥ 판매 기준 {threshold:,} → 강화"


# =========================
# Main
# =========================
def main():
    if USE_STATISTICS:
        # Load weapon book
        weapon_book = load_weapon_book(WEAPON_TREE_DIR)
        special_set = set(weapon_book.special_ids)
        reload_fn = make_reload_cb(
            bot_user_key=BOT_USER_KEY,
            bot_group_key=BOT_GROUP_KEY,
            tree_out_dir=WEAPON_TREE_DIR,
            cache=weapon_book
        )
        infer_policy = WeaponIdPolicy(
            mode="online",
            enable_reload=True,
            reload_on_missing_key=True,
            reload_on_termination_then_missing=False,
        )

        # Load analysis
        enhance_events, start_ts_en, end_ts_en = load_dictionary(RawData.ENHANCE_EVENTS)
        sell_events, start_ts_se, end_ts_se = load_dictionary(RawData.SELL_EVENTS)
        idlvl_cnt, grplvl_cnt, lvl_cnt = build_count_tables(enhance_events, special_ids=special_set)
        sell_idlvl, sell_grplvl, sell_lvl = build_sell_tables(sell_events, special_ids=special_set)

    else:
        weapon_book, special_set = None, None
        enhance_events, sell_events = None, None
        idlvl_cnt, grplvl_cnt, lvl_cnt = None, None, None
        sell_idlvl, sell_grplvl, sell_lvl = None, None, None
        reload_fn, infer_policy = None, None

    print("카카오톡 PC 창을 최대화하고 자동화할 대화방을 띄우세요.")
    print(f"비상 종료: {str(EXIT_KEY)} (전역), 또는 마우스를 좌상단으로 이동(pyautogui failsafe)\n")

    start_emergency_listener(STOP)

    # 캘리브레이션:
    chat_text_xy = calibrate_click("채팅 로그 위' 클릭 지점 (Ctrl+A/C가 되게)", STOP)
    if USE_BACKUP_CHAT_CLICK:
        chat_text_xy_backup = calibrate_click("백업 위치: 채팅 로그 위' 클릭 지점 (Ctrl+A/C가 되게)", STOP)
        chat_text_xy_list = [chat_text_xy, chat_text_xy_backup]
    else:
        chat_text_xy_list = [chat_text_xy]
    input_xy = calibrate_click("메시지 입력창 클릭 지점", STOP)
    mention_xy = calibrate_click(f"멘션 목록에서 '{BOT_MENTION_NAME}' 항목 클릭 지점(더블클릭될 곳)", STOP)
    room_xy = calibrate_click("채팅 목록에서 대상 대화방(플레이봇 방) 항목 좌표(더블클릭될 곳)", STOP)

    # 초기 상태
    full0 = select_all_copy_verified(chat_text_xy_list, STOP, retries=3)
    block0 = parse_kakao(full0)
    reply0, _, _ = extract_triplets(block0, USER_NAME, BOT_SENDER_NAME)

    current_weapon = extract_current_weapon(reply0)
    current_gold = extract_current_gold(reply0)

    print(f"\n[초기 상태] 무기=[{current_weapon.level}] {current_weapon.name}, 골드={current_gold:,}")

    loop_count = 0
    command = COMMAND_ENHANCE

    while True:
        if STOP.is_stop_set():
            break

        if loop_count % REFRESH_EVERY == 0 and loop_count > 0 and not STOP.is_pause_set():
            print(f"[리프레시] loop={loop_count}, 대화창 재오픈 수행")
            refresh_chat_window_safe(chat_text_xy_list, room_xy, input_xy, BOT_SENDER_NAME, STOP)

            # 리프레시 직후엔 포커스/복사 안정화를 위해 한 번 더 대기 또는 더미 복사 권장
            time.sleep(0.3)

        # 1) 명령 전송
        send_command(input_xy, mention_xy, command, BOT_MENTION_NAME, STOP)

        # 2) 봇 턴이 올 때까지 대기
        full = wait_for_bot_turn(chat_text_xy_list, USER_NAME, BOT_SENDER_NAME, STOP,
                                 timeout_sec=60.0, poll_interval=0.35)

        # 3) 결과 블록 파싱
        block = parse_kakao(full)
        reply_list, _, usercomm_list = extract_triplets(block, USER_NAME, BOT_SENDER_NAME)

        # 4) Macro command 처리
        usercomm = usercomm_list[-1] if len(usercomm_list) > 0 else None
        if usercomm and usercomm.macro_action == MacroAction.PAUSE:
            STOP.set_pause()
        elif usercomm and usercomm.macro_action == MacroAction.RESUME:
            STOP.unset_pause()
        elif usercomm and usercomm.macro_action == MacroAction.EXIT:
            STOP.set_stop()

        if STOP.is_pause_set():
            time.sleep(1.0)
            continue

        if USE_STATISTICS:
            reply_list = assign_weapon_ids(
                replies=reply_list,
                book=weapon_book,
                previous_weapon_id=current_weapon.id,
                reload_weapon_book=reload_fn,
                policy=infer_policy
            )

        reply = reply_list[-1]

        # 4) busy면 패스
        if reply.type == "busy":
            time.sleep(0.5)
            loop_count += 1
            continue

        # 5) 상태 업데이트 (파싱 실패 시 이전 값 유지)
        _current_weapon = extract_current_weapon([reply])
        _current_gold = extract_current_gold([reply])
        if _current_weapon is not None:
            current_weapon = _current_weapon
        if _current_gold is not None:
            current_gold = _current_gold

        sender = get_last_sender(full)
        print(f"\n[수신] last_sender={sender}, type={reply.type}")
        print(f"[상태] 무기=[{current_weapon.level}] {current_weapon.name}, 골드={current_gold:,}")

        # 6) 다음 커맨드 결정
        if reply.type == "insufficient_gold":
            next_cmd, reason = COMMAND_SELL, "골드 부족 → 판매"
        else:
            next_cmd, reason = decide_next_command(current_weapon, current_gold,
                                                   special_set=special_set, idlvl_cnt=idlvl_cnt,
                                                   grplvl_cnt=grplvl_cnt, lvl_cnt=lvl_cnt,
                                                   sell_idlvl=sell_idlvl, sell_grplvl= sell_grplvl,
                                                   sell_lvl=sell_lvl)
        print(f"[결정] {reason}")

        if next_cmd is None:
            print("루프 종료(목표 레벨 도달)")
            break

        command = next_cmd
        time.sleep(0.2)

        loop_count += 1

    print("\n프로그램 종료")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        print(f"\n프로그램 종료: {e}")
    except Exception as e:
        print(f"\n오류로 종료: {e}")
        raise e
