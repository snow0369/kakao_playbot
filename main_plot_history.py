from config import load_username
from playbot.analysis import plot_gold_and_level_by_reply_index
from playbot.parse import load_chat_log, extract_triplets

USER_NAME = load_username()
BOT_SENDER_NAME = "플레이봇"  # 복사 텍스트에서 [플레이봇] 형태로 나타나는 발화자

PATH_EXPORTED_CHAT = "chat_log/"
TIME_START = None
TIME_END = None

PLOT_PATH = "plots/"

if __name__ == "__main__":
    all_chat = load_chat_log(PATH_EXPORTED_CHAT, TIME_START, TIME_END, prev_seq=0)
    reply_list, _, _ = extract_triplets(all_chat, USER_NAME, BOT_SENDER_NAME)
    plot_gold_and_level_by_reply_index(reply_list, PLOT_PATH,
                                       start=TIME_START, end=TIME_END,)
