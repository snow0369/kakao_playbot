# playbot_log_analyze.py
# 사용법:
#   1) INPUT_PATH를 본인 파일 경로로 바꾸고 실행
#   2) 결과 엑셀: playbot_analysis_normalized.xlsx 생성

import re
import pandas as pd
import datetime as dt

# =========================
# 입력 / 출력 경로
# =========================
INPUT_PATH = "/mnt/data/Talk_2026.1.9 11_51-1.txt"
OUTPUT_XLSX = "/mnt/data/playbot_analysis_normalized.xlsx"

# =========================
# 메시지 헤더 파싱
# (카카오톡 내보내기 포맷 가정)
#   2026. 1. 8. 오후 5:42, 플레이봇 : 본문...
# =========================
MSG_HEADER_RE = re.compile(
    r"^(\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.)\s*(오전|오후)\s*([0-9]{1,2}:[0-9]{2}),\s*([^:]+)\s*:\s*(.*)$",
    re.M
)

def parse_datetime(date_str: str, ampm: str, time_str: str) -> dt.datetime:
    # date_str: '2026. 1. 8.' 형태
    parts = [p.strip() for p in date_str.replace(".", " ").split() if p.strip()]
    y, m, d = map(int, parts[:3])
    hh, mm = map(int, time_str.split(":"))
    if ampm == "오후" and hh != 12:
        hh += 12
    if ampm == "오전" and hh == 12:
        hh = 0
    return dt.datetime(y, m, d, hh, mm)

def parse_int_korean_num(s: str) -> int:
    return int(s.replace(",", "").strip())

# =========================
# 이벤트 파싱 정규식
# =========================
COST_RE = re.compile(r"사용 골드\s*:\s*-\s*([\d,]+)G")
GOLD_AFTER_RE = re.compile(r"남은 골드\s*:\s*([\d,]+)G")

# 강화 성공: +a → +b, 획득 검: [+b] NAME
SUCC_HEADER_RE = re.compile(r"강화 성공.*?\+(\d+)\s*→\s*\+(\d+)")
SUCC_GAIN_RE = re.compile(r"획득\s*검\s*:\s*\[\+(\d+)\]\s*([^\n\r]+)")

# 강화 유지: 『[+L] NAME』 ... 레벨이 유지되었습니다.
KEEP_RE = re.compile(r"강화 유지")
KEEP_LEVELNAME_RE = re.compile(r"『\s*\[\+(\d+)\]\s*([^\]』]+?)\s*』.*?레벨이 유지", re.S)

# 강화 파괴: 종종 "산산조각 ... '[+0] 낡은 검' 지급" 공지가 다음 메시지에 옴
BREAK_RE = re.compile(r"강화 파괴")
BREAK_NOTICE_RE = re.compile(
    r"『\s*\[\+(\d+)\]\s*([^\]』]+?)\s*』.*?산산조각.*?『\s*\[\+0\]\s*([^\]』]+?)\s*』\s*지급",
    re.S
)

# 판매
SELL_RE = re.compile(r"검 판매")
SELL_REWARD_RE = re.compile(r"획득 골드\s*:\s*\+([\d,]+)G")
SELL_GOLDAFTER_RE = re.compile(r"현재 보유 골드\s*:\s*([\d,]+)G")
# 판매된 무기: 대화문에 '[+10] 무기'가 따옴표로 들어가는 케이스가 많음
SELL_SOLD_RE = re.compile(r"'\s*\[\+(\d+)\]\s*([^']+?)\s*'")
SELL_NEW_RE = re.compile(r"새로운\s*검\s*획득\s*:\s*\[\+(\d+)\]\s*([^\n\r]+)")

# 상태 라인(보조): "[+L] NAME" 한 줄로 오는 케이스
STATE_LINE_RE = re.compile(r"^\[\+(\d+)\]\s*(.+)$", re.M)

# =========================
# 1) 텍스트 로드 -> 메시지 단위로 분해
# =========================
text = open(INPUT_PATH, "r", encoding="utf-8").read().replace("\r\n", "\n")

matches = list(MSG_HEADER_RE.finditer(text))

messages = []
for i, m in enumerate(matches):
    start = m.start()
    end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

    date_str, ampm, tstr = m.group(1), m.group(2), m.group(3)
    sender = m.group(4).strip()
    first_line = m.group(5)

    body = text[m.end():end].strip("\n")
    content = (first_line + ("\n" + body if body else "")).strip()

    messages.append({
        "dt": parse_datetime(date_str, ampm, tstr),
        "sender": sender,
        "content": content,
    })

dfm = pd.DataFrame(messages).sort_values("dt").reset_index(drop=True)

# =========================
# 2) 이벤트 추출 (상태 머신)
#   - 레벨 0은 분기 가능
#   - 레벨>=1은 레벨에 따른 이름이 사실상 고정이므로 이후 canonical map으로 보정
# =========================
events = []
cur_level: int | None = None
cur_name: str | None = None

for i, row in dfm.iterrows():
    if row["sender"] != "플레이봇":
        continue

    c = row["content"]

    # 강화 성공
    mh = SUCC_HEADER_RE.search(c)
    if mh:
        from_lv = int(mh.group(1))
        to_lv = int(mh.group(2))

        mg = SUCC_GAIN_RE.search(c)
        gain_name = mg.group(2).strip() if mg else None

        cost_m = COST_RE.search(c)
        gold_m = GOLD_AFTER_RE.search(c)
        cost = parse_int_korean_num(cost_m.group(1)) if cost_m else None
        gold_after = parse_int_korean_num(gold_m.group(1)) if gold_m else None

        before_name = cur_name if (cur_level == from_lv) else None

        events.append({
            "dt": row["dt"],
            "event": "enhance_success",
            "before_level": from_lv,
            "before_name": before_name,
            "after_level": to_lv,
            "after_name": gain_name,
            "cost": cost,
            "reward": None,
            "gold_after": gold_after,
        })

        # 상태 업데이트
        if gain_name is not None:
            cur_level = to_lv
            cur_name = gain_name
        else:
            cur_level = to_lv
        continue

    # 강화 유지
    if KEEP_RE.search(c) and "〖" in c:
        km = KEEP_LEVELNAME_RE.search(c)
        if km:
            lv = int(km.group(1))
            nm = km.group(2).strip()
        else:
            # 포맷이 깨진 경우: 현재 상태 fallback
            lv = cur_level
            nm = cur_name

        cost_m = COST_RE.search(c)
        gold_m = GOLD_AFTER_RE.search(c)
        cost = parse_int_korean_num(cost_m.group(1)) if cost_m else None
        gold_after = parse_int_korean_num(gold_m.group(1)) if gold_m else None

        events.append({
            "dt": row["dt"],
            "event": "enhance_keep",
            "before_level": lv,
            "before_name": nm,
            "after_level": lv,
            "after_name": nm,
            "cost": cost,
            "reward": None,
            "gold_after": gold_after,
        })

        cur_level = lv
        cur_name = nm
        continue

    # 강화 파괴
    if BREAK_RE.search(c) and "〖" in c:
        after_name = "낡은 검"
        broken_lv = cur_level
        broken_nm = cur_name

        # 파괴 공지는 다음 메시지(보통 1~2개 뒤)에서 뜨는 케이스가 있어 lookahead
        for j in range(i, min(i + 6, len(dfm))):
            if dfm.loc[j, "sender"] == "플레이봇":
                bn = BREAK_NOTICE_RE.search(dfm.loc[j, "content"])
                if bn:
                    broken_lv = int(bn.group(1))
                    broken_nm = bn.group(2).strip()
                    after_name = bn.group(3).strip()
                    break

        cost_m = COST_RE.search(c)
        gold_m = GOLD_AFTER_RE.search(c)
        cost = parse_int_korean_num(cost_m.group(1)) if cost_m else None
        gold_after = parse_int_korean_num(gold_m.group(1)) if gold_m else None

        events.append({
            "dt": row["dt"],
            "event": "enhance_break",
            "before_level": broken_lv,
            "before_name": broken_nm,
            "after_level": 0,
            "after_name": after_name,
            "cost": cost,
            "reward": None,
            "gold_after": gold_after,
        })

        cur_level = 0
        cur_name = after_name
        continue

    # 판매
    if SELL_RE.search(c):
        rew_m = SELL_REWARD_RE.search(c)
        goldm = SELL_GOLDAFTER_RE.search(c)
        reward = parse_int_korean_num(rew_m.group(1)) if rew_m else None
        gold_after = parse_int_korean_num(goldm.group(1)) if goldm else None

        sold = SELL_SOLD_RE.search(c)
        before_level = int(sold.group(1)) if sold else cur_level
        before_name = sold.group(2).strip() if sold else cur_name

        newm = SELL_NEW_RE.search(c)
        after_level = int(newm.group(1)) if newm else 0
        after_name = newm.group(2).strip() if newm else "낡은 검"

        events.append({
            "dt": row["dt"],
            "event": "sell",
            "before_level": before_level,
            "before_name": before_name,
            "after_level": after_level,
            "after_name": after_name,
            "cost": None,
            "reward": reward,
            "gold_after": gold_after,
        })

        cur_level = after_level
        cur_name = after_name
        continue

    # 보조: 상태 라인 업데이트
    sm = STATE_LINE_RE.match(c.strip())
    if sm:
        cur_level = int(sm.group(1))
        cur_name = sm.group(2).strip()

edf = pd.DataFrame(events).sort_values("dt").reset_index(drop=True)

# =========================
# 3) 레벨>=1 이름이 "결정적"이라는 가정 반영:
#    (level -> canonical_name) 를 로그에서 학습(mode)하고 보정
# =========================
name_obs = pd.concat([
    edf.loc[edf["event"] == "enhance_success", ["after_level", "after_name"]],
    edf.loc[edf["event"] == "enhance_keep", ["after_level", "after_name"]],
]).dropna()

name_map = {}
consistency_rows = []

for lvl, grp in name_obs.groupby("after_level"):
    if pd.isna(lvl):
        continue
    lvl = int(lvl)
    if lvl >= 1:
        mode_name = grp["after_name"].mode().iloc[0]
        name_map[lvl] = mode_name
        consistency_rows.append({
            "level": lvl,
            "canonical_name": mode_name,
            "observations": len(grp),
            "unique_names": grp["after_name"].nunique(),
            "match_rate": float((grp["after_name"] == mode_name).mean()),
        })

name_map_df = pd.DataFrame(consistency_rows).sort_values("level").reset_index(drop=True)

# before_name / after_name 결측 또는 흔들림 보정
edf["before_name_filled"] = edf["before_name"]
mask = edf["before_name_filled"].isna() & edf["before_level"].notna()
edf.loc[mask, "before_name_filled"] = edf.loc[mask, "before_level"].astype(int).map(name_map)

edf["after_name_filled"] = edf["after_name"]
mask2 = edf["after_name_filled"].isna() & edf["after_level"].notna()
edf.loc[mask2, "after_name_filled"] = edf.loc[mask2, "after_level"].astype(int).map(name_map)

# =========================
# 4) 요구 통계 산출
# =========================

# (A) 레벨별 강화 비용/확률 (시도 레벨 = before_level 기준)
enh_df = edf[edf["event"].isin(["enhance_success", "enhance_keep", "enhance_break"])].copy()

enh_stats = (
    enh_df.groupby("before_level")
    .agg(
        trials=("event", "count"),
        success=("event", lambda x: (x == "enhance_success").sum()),
        keep=("event", lambda x: (x == "enhance_keep").sum()),
        break_=("event", lambda x: (x == "enhance_break").sum()),
        avg_cost=("cost", "mean"),
        median_cost=("cost", "median"),
    )
    .reset_index()
)
enh_stats["p_success"] = enh_stats["success"] / enh_stats["trials"]
enh_stats["p_keep"] = enh_stats["keep"] / enh_stats["trials"]
enh_stats["p_break"] = enh_stats["break_"] / enh_stats["trials"]
enh_stats["weapon_name(canonical>=1)"] = enh_stats["before_level"].map(name_map)

# (B) 레벨0에서 1로 갈 때 분기(무기 이름 분포)
lvl0_to1 = edf[(edf["event"] == "enhance_success") & (edf["before_level"] == 0)].copy()
lvl0_dist = (
    lvl0_to1.groupby("after_name_filled")
    .size()
    .reset_index(name="count")
    .sort_values("count", ascending=False)
)

# (C) 판매 보상 앙상블: sold level 기준
sell_df = edf[edf["event"] == "sell"].copy()
sell_df["sold_level"] = sell_df["before_level"]
sell_rewards = (
    sell_df.groupby("sold_level")
    .agg(
        count=("reward", "count"),
        mean_reward=("reward", "mean"),
        std_reward=("reward", "std"),
        min_reward=("reward", "min"),
        max_reward=("reward", "max"),
    )
    .reset_index()
)
sell_rewards["weapon_name(canonical>=1)"] = sell_rewards["sold_level"].map(name_map)

# =========================
# 5) 엑셀 출력
# =========================
with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as writer:
    edf.to_excel(writer, index=False, sheet_name="raw_events")
    name_map_df.to_excel(writer, index=False, sheet_name="level_name_map")
    enh_stats.sort_values("before_level").to_excel(writer, index=False, sheet_name="enhance_stats_by_level")
    sell_rewards.sort_values("sold_level").to_excel(writer, index=False, sheet_name="sell_rewards_by_level")
    lvl0_dist.to_excel(writer, index=False, sheet_name="level0_to1_distribution")

print(f"Done: {OUTPUT_XLSX}")
