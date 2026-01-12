import time
from typing import Optional, Tuple

from pynput import keyboard

from config import load_config
from interact import StopFlag, start_emergency_listener, calibrate_click, select_all_copy_verified, \
    send_command, wait_for_bot_turn, get_last_sender, refresh_chat_window_safe
from parse import extract_last_result_block, parse_result_block


# =========================
# Settings
# =========================
config = load_config()
USER_NAME = config["USER_NAME"]
BOT_SENDER_NAME = "플레이봇"  # 복사 텍스트에서 [플레이봇] 형태로 나타나는 발화자
BOT_MENTION_NAME = "플레이봇"  # 멘션 자동완성에서 클릭할 이름(동일하면 그대로)

COMMAND_ENHANCE = "강화"
COMMAND_SELL = "판매"

# 비상탈출 키
EXIT_KEY = keyboard.Key.f12
STOP = StopFlag(EXIT_KEY)

# 채팅방 재오픈
REFRESH_EVERY = 1000


# =========================
# 의사결정 로직
# =========================
def decide_next_command(level: int, gold: int) -> Tuple[Optional[str], str]:
    # if level >= 20:
    #     return None, f"종료: 레벨 {level} >= 20"
    if level >= 18:
        return COMMAND_SELL, f"레벨 {level} >= 18 → 판매"

    if level <= 8:
        return COMMAND_ENHANCE, f"레벨 {level} ≤ 8 → 강화"

    threshold = 100_000 + (level - 9) * 150_000
    if gold < threshold:
        return COMMAND_SELL, f"레벨 {level}, 골드 {gold:,} < 판매 기준 {threshold:,} → 판매"
    return COMMAND_ENHANCE, f"레벨 {level}, 골드 {gold:,} ≥ 판매 기준 {threshold:,} → 강화"


# =========================
# 메인
# =========================
def main():
    print("카카오톡 PC 창을 최대화하고 자동화할 대화방을 띄우세요.")
    print(f"비상 종료: {str(EXIT_KEY)} (전역), 또는 마우스를 좌상단으로 이동(pyautogui failsafe)\n")

    start_emergency_listener(STOP)

    # 캘리브레이션:
    chat_text_xy = calibrate_click("채팅 로그 위' 클릭 지점 (Ctrl+A/C가 되게)", STOP)
    input_xy = calibrate_click("메시지 입력창 클릭 지점", STOP)
    mention_xy = calibrate_click(f"멘션 목록에서 '{BOT_MENTION_NAME}' 항목 클릭 지점(더블클릭될 곳)", STOP)
    room_xy = calibrate_click("채팅 목록에서 대상 대화방(플레이봇 방) 항목 좌표(더블클릭될 곳)", STOP)

    # 초기 상태
    full0 = select_all_copy_verified(chat_text_xy, STOP, retries=3)
    block0 = extract_last_result_block(full0)
    info0 = parse_result_block(block0)

    current_level = info0.level if info0.level is not None else 0
    current_gold = info0.gold if info0.gold is not None else 0

    print(f"\n[초기 상태] 레벨={current_level}, 골드={current_gold:,}")

    loop_count = 0
    command = COMMAND_ENHANCE

    while True:
        if STOP.is_set():
            break

        loop_count += 1

        if loop_count % REFRESH_EVERY == 0:
            print(f"[리프레시] loop={loop_count}, 대화창 재오픈 수행")
            refresh_chat_window_safe(chat_text_xy, room_xy, input_xy, BOT_SENDER_NAME, STOP)

            # 리프레시 직후엔 포커스/복사 안정화를 위해 한 번 더 대기 또는 더미 복사 권장
            time.sleep(0.3)

        # 1) 명령 전송
        send_command(input_xy, mention_xy, command, BOT_MENTION_NAME, STOP)

        # 2) 봇 턴이 올 때까지 대기
        full = wait_for_bot_turn(chat_text_xy, USER_NAME, BOT_SENDER_NAME, STOP,
                                 timeout_sec=10.0, poll_interval=0.35)

        # 3) 결과 블록 파싱
        block = extract_last_result_block(full)
        info = parse_result_block(block)

        # 4) busy면 결과가 올 때까지 한 번 더
        if info.rtype == "busy":
            full = wait_for_bot_turn(chat_text_xy, USER_NAME, BOT_SENDER_NAME, STOP,
                                     timeout_sec=10.0, poll_interval=0.35)
            block = extract_last_result_block(full)
            info = parse_result_block(block)

        # 5) 상태 업데이트 (파싱 실패 시 이전 값 유지)
        if info.level is not None:
            current_level = info.level
        if info.gold is not None:
            current_gold = info.gold

        sender = get_last_sender(full)
        print(f"\n[수신] last_sender={sender}, type={info.rtype}")
        print(f"[상태] 레벨={current_level}, 골드={current_gold:,}")

        # 6) 다음 커맨드 결정
        next_cmd, reason = decide_next_command(current_level, current_gold)
        print(f"[결정] {reason}")

        if next_cmd is None:
            print("루프 종료(목표 레벨 도달)")
            break

        command = next_cmd
        time.sleep(0.2)

    print("\n프로그램 종료")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        print(f"\n프로그램 종료: {e}")
    except Exception as e:
        print(f"\n오류로 종료: {e}")
