import pandas as pd

from playbot.parse.kakao_mobile_imported import MOBILE_EXPORT_MSG_RE, parse_mobile_export_format
from playbot.parse.kakao_pc_imported import PC_EXPORT_MSG_RE, PC_EXPORT_DAY_RE, PC_EXPORT_SAVED_AT_RE, \
    parse_pc_export_format
from playbot.parse.kakao_realtime import COPY_MSG_RE, COPY_DATE_RE, parse_copy_format


def parse_kakao(text: str, prev_seq: int = 0) -> pd.DataFrame:
    """
    입력 텍스트가 export인지 copy인지 자동 판별하여,
    동일한 (dt, sender, content) 형태로 반환.
    """
    t = text.replace("\r\n", "\n")

    # 강한 특징으로 판별: export는 "YYYY. M. D. 오전/오후 HH:MM, sender :" 패턴이 있음
    if MOBILE_EXPORT_MSG_RE.search(t):
        return parse_mobile_export_format(t, prev_seq)
    if PC_EXPORT_MSG_RE.search(t) or PC_EXPORT_DAY_RE.search(t) or PC_EXPORT_SAVED_AT_RE.search(t):
        return parse_pc_export_format(t, prev_seq)
    # copy는 "[sender] [오전/오후 HH:MM]" 패턴 + "YYYY년 M월 D일 요일"이 흔함
    if COPY_MSG_RE.search(t) and COPY_DATE_RE.search(t):
        return parse_copy_format(t, prev_seq)

    raise ValueError("알 수 없는 카카오톡 텍스트 포맷입니다. export/copy 패턴 모두 매칭되지 않습니다.")
