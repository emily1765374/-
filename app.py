import json
import os
import shutil
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

BASE = Path(__file__).parent
DATA_FILE = BASE / "expenses.csv"
POINT_FILE = BASE / "points.csv"
COLUMNS = ["id", "date", "category", "place", "item", "amount", "memo", "created_at"]
POINT_COLUMNS = ["id", "date", "type", "points", "memo", "created_at"]
CATEGORIES = ["평일식재료", "안식일식재료", "주방소모품", "기타"]
POINT_TYPES = ["적립", "사용"]
LABELS = {"date": "날짜", "category": "카테고리", "place": "사용처", "item": "품목", "amount": "금액",
          "type": "구분", "points": "포인트", "memo": "메모"}
ORDINALS = ["첫째", "둘째", "셋째", "넷째", "다섯째", "여섯째"]
WEEKDAYS = "월화수목금토일"
ENCODING = "utf-8-sig"  # 엑셀에서 한글 깨짐 방지


# ---------- 저장소 ----------

def new_id():
    return uuid.uuid4().hex[:8]


def load_data(path=DATA_FILE, columns=COLUMNS, num_col="amount"):
    """CSV를 읽어 DataFrame 반환. 파일이 없으면 빈 표. 손상 시 예외를 그대로 올린다(덮어쓰기 방지)."""
    if not path.exists():
        return pd.DataFrame(columns=columns).astype({num_col: "Int64"})
    df = pd.read_csv(path, encoding=ENCODING, dtype=str, keep_default_na=False)
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    df = df[columns].copy()
    # 숫자가 아닌 값은 행을 지우지 않고 NA로 둔다 (합계에서만 제외)
    df[num_col] = pd.to_numeric(df[num_col].str.replace(",", ""), errors="coerce").astype("Int64")
    no_id = df["id"] == ""
    df.loc[no_id, "id"] = [new_id() for _ in range(no_id.sum())]
    return df


def save_data(df, path=DATA_FILE, columns=COLUMNS):
    """임시 파일에 쓴 뒤 원자적으로 교체. 직전 원본은 .bak 으로 1개 보관."""
    tmp = path.with_suffix(".csv.tmp")
    df[columns].to_csv(tmp, index=False, encoding=ENCODING)
    if path.exists():
        shutil.copy2(path, path.with_suffix(".csv.bak"))
    os.replace(tmp, path)


def load_points():
    return load_data(POINT_FILE, POINT_COLUMNS, "points")


def save_points(df):
    save_data(df, POINT_FILE, POINT_COLUMNS)


# ---------- 계산 ----------

def won(n):
    return "금액 오류" if pd.isna(n) else f"{int(n):,}원"


def month_end(d):
    return (d.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def week_start(d):
    """d가 속한 주의 일요일"""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def week_of(d):
    """일~토 달력 주차. 1일~첫 토요일이 1주차, 마지막 일요일~말일이 마지막 주차."""
    offset = (d.replace(day=1).weekday() + 1) % 7  # 1일의 요일 (일=0 ... 토=6)
    return (d.day - 1 + offset) // 7 + 1


def month_weeks(year, month):
    """{주차: (시작일, 종료일)}"""
    weeks = {}
    d = date(year, month, 1)
    while d.month == month:
        w = week_of(d)
        weeks[w] = (weeks.get(w, (d,))[0], d)
        d += timedelta(days=1)
    return weeks


def parse_dates(df):
    return pd.to_datetime(df["date"], errors="coerce", format="%Y-%m-%d")


def filter_df(df, start, end, cats=None):
    d = parse_dates(df)
    mask = (d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))
    if cats:
        mask &= df["category"].isin(cats)
    return df[mask]


def category_sums(view):
    return view.groupby("category")["amount"].sum().sort_values(ascending=False)


def weekly_sums(view):
    """(연, 월, 주차) -> 합계"""
    if view.empty:
        return pd.Series(dtype="int64")
    keys = parse_dates(view).map(lambda t: (t.year, t.month, week_of(t.date())))
    return view.groupby(keys)["amount"].sum().sort_index()


def point_summary(pts):
    """넘겨받은 포인트 내역의 (총 적립, 총 사용, 잔액). 전체를 넘기면 전체 누적"""
    earn = int(pts.loc[pts["type"] == "적립", "points"].sum())
    used = int(pts.loc[pts["type"] == "사용", "points"].sum())
    return earn, used, earn - used


def md(d):
    return f"{d.month}/{d.day}"


def build_report(df, pts, year, month, w):
    """주간 보고 텍스트 (카톡 복사용 고정 양식)"""
    weeks = month_weeks(year, month)
    start, end = weeks[w]
    view = filter_df(df, start, end)
    lines = ["[주방비 주간 지출보고]", "",
             f"{month}월 {ORDINALS[w - 1]}주 ({md(start)}~{md(end)})",
             f"▶ 주간 지출 : {won(view['amount'].sum())}", "", "① 일별 지출현황"]
    for i, (d, g) in enumerate(view.groupby(parse_dates(view).dt.date)):
        if i:
            lines.append("")  # 날짜 묶음 사이 빈 줄
        lines.append(f"{d:%m/%d}({WEEKDAYS[d.weekday()]}) {won(g['amount'].sum())}")
        for r in g.sort_values("created_at").itertuples():
            place = r.place or r.item  # 사용처 칸이 생기기 전 기록은 품목으로 표시
            note = r.item if r.place else ""  # 괄호엔 품목만 (메모 무시), 없으면 괄호 생략
            lines.append(f"· {place} / {r.category} : {won(r.amount)}" + (f" ({note})" if note else ""))
    if view.empty:
        lines.append("지출 없음")

    lines += ["", "② 주간 지출구분"]
    sums = category_sums(view)
    order = [c for c in CATEGORIES if c in sums] + [c for c in sums.index if c not in CATEGORIES]
    lines += [f"{c} : {won(sums[c])}" for c in order] or ["지출 없음"]

    month_view = filter_df(df, date(year, month, 1), month_end(start))
    weekly = weekly_sums(month_view)
    # 1주차 ~ (보고 주차, 지출 있는 마지막 주차 중 늦은 쪽)까지만. 아직 안 온 빈 주차는 생략
    last = max([w] + [k[2] for k, s in weekly.items() if s])
    lines += ["", f"③ {month}월 누계"]
    lines += [f"{n}주차 : {won(weekly.get((year, month, n), 0))}" for n in weeks if n <= last]
    lines.append(f"▶ {month}월 누계 : {won(month_view['amount'].sum())}")

    earn, used, _ = point_summary(filter_df(pts, start, end))
    balance = point_summary(pts)[2]  # 잔액은 기간 무관 전체 누적
    lines += ["", "④ 네이버포인트", f"이번주 적립 : {earn:,}원", f"이번주 사용 : {used:,}원",
              f"▶ 사용가능포인트 : {balance:,}P"]
    return "\n".join(lines)


# ---------- 화면 ----------

CSS = """
<style>
.stApp { background: #e0f2fe; }
header[data-testid="stHeader"] { background: transparent; }
.element-container:has(#lang-fix) { display: none; }  /* 번역 방지 스크립트용 빈 칸 */
.copy-btn { width: 100%; min-height: 48px; border-radius: 12px; border: 1px solid #0284c7; background: #fff;
            color: #0284c7; font-weight: 600; font-size: .875rem; font-family: inherit; cursor: pointer; }
.copy-btn:active { background: #e0f2fe; }
.st-key-report_box [data-testid="stCode"] button { display: none !important; }
.copy-msg { margin-top: 8px; padding: 12px 16px; border-radius: 10px; font-size: .9rem; }
.copy-msg.ok { background: #dcfce7; color: #166534; }  /* st.success 와 같은 톤 */
.copy-msg.fail { background: #fee2e2; color: #991b1b; }
/* 아이폰 화면 폭 */
/* flex-shrink: 0 → 스크롤 영역(stMain, flex) 안에서 화면 높이로 줄어들지 않고 내용 끝까지 늘어남 (여백·흰 배경이 끝까지) */
.block-container { max-width: 430px; background: #fff; min-height: 100%; height: auto !important; flex-shrink: 0;
                   box-shadow: 0 0 24px rgba(2, 132, 199, .12);
                   /* 하단 여백: 폰 브라우저 하단 툴바·홈 인디케이터에 마지막 내용이 가리지 않게 */
                   padding: 0 16px calc(160px + env(safe-area-inset-bottom)) !important; }
/* 100vh는 모바일에서 툴바 뒤 영역까지 포함해 맨 아래가 스크롤로 닿지 않음 → 실제 보이는 높이(dvh) */
.stApp, [data-testid="stAppViewContainer"] { height: 100dvh !important; }
@media (max-width: 430px) { .block-container { box-shadow: none; } }
.app-header { margin: 0 -16px 8px; padding: 44px 20px 18px; color: #fff;
              background: linear-gradient(135deg, #0284c7, #38bdf8); border-radius: 0 0 24px 24px; }
.app-header h1 { margin: 0; padding: 0; font-size: 1.5rem; color: #fff; }
.app-header p { margin: 4px 0 0; font-size: .85rem; opacity: .9; }
/* 큰 터치 버튼 */
.stButton button, .stFormSubmitButton button, .stDownloadButton button {
    min-height: 48px; border-radius: 12px; font-weight: 600; }
/* 둥근 카드 */
[data-testid="stForm"], [data-testid="stCode"] {
    border-radius: 16px !important; border: 1px solid #bae6fd !important; background: #f0f9ff; }
[data-testid="stForm"] { padding: 16px; }
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="base-input"] { border-radius: 10px !important; }
[data-testid="stForm"] [data-baseweb="input"], [data-testid="stForm"] [data-baseweb="select"] > div {
    background: #fff !important; border: 1px solid #bae6fd !important; }
[data-testid="stForm"] [data-baseweb="base-input"], [data-testid="stForm"] input { background: #fff !important; }
[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }
.stTabs [data-baseweb="tab-list"] { gap: 0; }
.stTabs [data-baseweb="tab-list"] > div:first-child { width: 100%; }
.stTabs button[role="tab"] { flex: 1; justify-content: center; min-height: 48px; font-weight: 600; }
/* 탭 위 요약 카드: 폰 폭에서도 2열 유지 */
.st-key-summary [data-testid="stHorizontalBlock"], [class*="st-key-period_"] [data-testid="stHorizontalBlock"],
.st-key-backup [data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap; gap: 10px; }
.st-key-summary [data-testid="stColumn"], [class*="st-key-period_"] [data-testid="stColumn"],
.st-key-backup [data-testid="stColumn"] {
    min-width: 0 !important; flex: 1 1 0 !important; width: auto !important; }
/* 기간 버튼 6개: 컴팩트 */
[class*="st-key-period_"] [data-testid="stHorizontalBlock"], .st-key-backup [data-testid="stHorizontalBlock"] { gap: 4px; }
[class*="st-key-period_"] button, .st-key-backup button { min-height: 38px; padding: 0 2px; border-radius: 10px; white-space: nowrap; }
[class*="st-key-period_"] button p, .st-key-backup button p { font-size: .75rem; white-space: nowrap; }
.period-label { font-size: .875rem; margin: 0 0 2px; }
.sum-card { text-align: center; padding: 12px 8px; border: 1px solid #bae6fd; border-radius: 16px; background: #fff; }
.sum-card span { display: block; font-size: .85rem; color: #64748b; }
.sum-card b { display: block; font-size: 1.35rem; margin: 2px 0; color: #0f172a; }
.sum-card small { color: #94a3b8; font-size: .75rem; }
.point-balance { padding: 16px 8px; margin-bottom: 4px; }
.point-balance b { font-size: 2rem; color: #0284c7; }
/* 통계: 카테고리 합계 목록 + 포인트 카드 */
.sum-list .row, .point-card .row { display: flex; justify-content: space-between; padding: 9px 0;
                                   border-bottom: 1px solid #e2e8f0; }
.row.total { border-top: 2px solid #cbd5e1; border-bottom: none !important; font-weight: 700; font-size: 1.05rem; }
.row.total b { color: #0284c7; }
.point-card { margin-top: 24px; padding: 14px 16px; border: 1px solid #bae6fd; border-radius: 16px; background: #f0f9ff; }
.point-card .title { font-weight: 700; margin-bottom: 4px; }
.point-card .note { font-size: .75rem; color: #64748b; margin-top: 6px; }
.total { font-size: 1.05rem; color: #0284c7; font-weight: 700; }
</style>
"""


def flash(msg):
    st.session_state["flash"] = msg
    st.rerun()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def period_picker(key):
    """선택한 (시작일, 종료일). 시작일 > 종료일이면 None."""
    today = date.today()
    choice = st.session_state.setdefault(key, "이번 달")
    st.markdown("<p class='period-label'>기간</p>", unsafe_allow_html=True)
    with st.container(key=f"period_{key}"):  # 폰 폭에서도 6칸 한 줄 (CSS)
        for col, opt in zip(st.columns(6), ["이번 주", "지난 주", "이번 달", "지난 달", "전체", "직접 선택"]):
            col.button(opt, key=f"{key}_{opt}", type="primary" if opt == choice else "secondary", width="stretch",
                       on_click=st.session_state.__setitem__, args=(key, opt))
    sunday = week_start(today)
    last_month = today.replace(day=1) - timedelta(days=1)
    if choice == "이번 주":
        start, end = sunday, sunday + timedelta(days=6)
    elif choice == "지난 주":
        start, end = sunday - timedelta(days=7), sunday - timedelta(days=1)
    elif choice == "이번 달":
        start, end = today.replace(day=1), month_end(today)
    elif choice == "지난 달":
        start, end = last_month.replace(day=1), last_month
    elif choice == "전체":
        st.caption("기간: 전체")
        return date(1900, 1, 1), date(2100, 12, 31)
    else:
        c1, c2 = st.columns(2)
        start = c1.date_input("시작일", today.replace(day=1), key=key + "_s")
        end = c2.date_input("종료일", today, key=key + "_e")
        if start > end:
            st.warning("시작일이 종료일보다 늦습니다.")
            return None
    st.caption(f"기간: {start} ~ {end}")
    return start, end


def show_table(view, columns, num_col, fmt=won):
    shown = view.sort_values(["date", "created_at"], ascending=False)[columns]
    shown = shown.assign(**{num_col: shown[num_col].map(fmt)}).rename(columns=LABELS)
    st.dataframe(shown, hide_index=True, width="stretch")


# 저장은 on_click 콜백에서 처리: 콜백은 화면을 다시 그리기 전에 실행되므로 위젯 값을 직접 기본값으로 되돌릴 수 있음
# (키 삭제 + st.rerun 방식은 브라우저가 이전 입력값을 다시 보내 초기화되지 않았음)

def save_expense():
    s = st.session_state
    place, amount = s.x_place.strip(), s.x_amount
    if not place:
        s.x_error = "사용처를 입력해 주세요."
    elif amount < 1:
        s.x_error = "금액은 1원 이상이어야 합니다."
    else:
        df = load_data()
        df.loc[len(df)] = [new_id(), s.x_date.isoformat(), s.x_cat, place, s.x_item.strip(), int(amount),
                           s.x_memo.strip(), now()]
        save_data(df)
        s.flash = f"저장했습니다: {place} {won(amount)}"
        s.x_place, s.x_item, s.x_amount, s.x_memo = "", "", 0, ""


def save_point():
    s = st.session_state
    if s.p_points < 1:
        s.p_error = "포인트는 1 이상이어야 합니다."
        return
    pts = load_points()
    pts.loc[len(pts)] = [new_id(), s.p_date.isoformat(), s.p_type, int(s.p_points), s.p_memo.strip(), now()]
    save_points(pts)
    s.flash = f"포인트 {s.p_type} {int(s.p_points):,}P 저장했습니다."
    s.p_points, s.p_memo = 0, ""


def input_tab():
    st.subheader("지출 입력")
    with st.form("expense_form"):
        st.date_input("날짜", date.today(), key="x_date")
        st.selectbox("카테고리", CATEGORIES, key="x_cat")
        st.text_input("사용처", key="x_place")
        st.text_input("품목 (선택)", key="x_item")
        st.number_input("금액(원)", min_value=0, step=1000, key="x_amount")
        st.text_input("메모 (선택)", key="x_memo")
        st.form_submit_button("지출 저장", width="stretch", type="primary", on_click=save_expense)
        if err := st.session_state.pop("x_error", None):
            st.error(err)


def edit_expense(view):
    labels = {r.id: f"{r.date} · {r.category} · {r.place or r.item} · {won(r.amount)}" for r in view.itertuples()}
    # key 고정: 없으면 항목 문구(금액 등)가 바뀔 때 새 위젯으로 인식돼 선택이 첫 항목으로 튐
    sel = st.selectbox("수정/삭제할 항목", list(labels), format_func=labels.get, key="edit_sel")
    row = view[view["id"] == sel].iloc[0]
    cats = CATEGORIES if row.category in CATEGORIES else CATEGORIES + [row.category]  # 옛 값 보존
    with st.form("edit_form"):
        d = st.date_input("날짜", pd.Timestamp(row.date).date(), key=f"e_d_{sel}")
        cat = st.selectbox("카테고리", cats, index=cats.index(row.category), key=f"e_c_{sel}")
        place = st.text_input("사용처", row.place, key=f"e_p_{sel}")
        item = st.text_input("품목 (선택)", row["item"], key=f"e_i_{sel}")
        amount = st.number_input("금액(원)", min_value=0, step=1000,
                                 value=0 if pd.isna(row.amount) else int(row.amount), key=f"e_a_{sel}")
        memo = st.text_input("메모", row.memo, key=f"e_m_{sel}")
        confirm = st.checkbox("삭제 확인", key=f"e_x_{sel}")
        c1, c2 = st.columns(2)
        save = c1.form_submit_button("수정 저장", width="stretch", type="primary")
        delete = c2.form_submit_button("삭제", width="stretch")

    if not (save or delete):
        return
    df = load_data()  # 최신 파일 기준으로 처리
    idx = df.index[df["id"] == sel]
    if idx.empty:
        st.error("이미 삭제된 항목입니다.")
    elif delete:
        if not confirm:
            st.warning("'삭제 확인'을 체크한 뒤 삭제를 눌러주세요.")
        else:
            save_data(df.drop(idx))
            flash("삭제했습니다.")
    elif not place.strip():
        st.error("사용처를 입력해 주세요.")
    elif amount < 1:
        st.error("금액은 1원 이상이어야 합니다.")
    else:
        df.loc[idx, ["date", "category", "place", "item", "amount", "memo"]] = [
            d.isoformat(), cat, place.strip(), item.strip(), int(amount), memo.strip()]
        save_data(df)
        flash("수정했습니다.")


def list_tab(df):
    period = period_picker("list_period")
    cats = st.multiselect("카테고리", CATEGORIES, placeholder="전체")
    if not period:
        return
    view = filter_df(df, *period, cats)
    st.markdown(f"<div class='total'>{len(view)}건 · 합계 {won(view['amount'].sum())}</div>", unsafe_allow_html=True)
    if view.empty:
        st.info("해당 조건의 지출 내역이 없습니다.")
    else:
        show_table(view, ["date", "category", "place", "item", "amount", "memo", "created_at"], "amount")
        edit_expense(view)


def points_tab(pts):
    st.subheader("N포인트 입력")
    st.caption("지출과 별도로 포인트만 기록합니다.")
    with st.form("point_form"):
        st.date_input("날짜", date.today(), key="p_date")
        st.radio("구분", POINT_TYPES, horizontal=True, key="p_type")
        st.number_input("포인트", min_value=0, step=100, key="p_points")
        st.text_input("메모 (선택)", key="p_memo")
        st.form_submit_button("포인트 저장", width="stretch", type="primary", on_click=save_point)
        if err := st.session_state.pop("p_error", None):
            st.error(err)

    st.subheader("N포인트 내역")
    period = period_picker("point_period")
    if not period:
        return
    pts = filter_df(pts, *period)
    choice = st.session_state["point_period"]
    name = f"{md(period[0])}~{md(period[1])}" if choice == "직접 선택" else choice
    earn, used, _ = point_summary(pts)
    sums = f"적립 {earn:,}P" + (f" · 사용 {used:,}P" if used else "")
    # 지출 표와 같은 방식: 항상 펼침, 10행 넘으면 표 안에서 스크롤 (st.dataframe 기본 높이)
    st.markdown(f"<div class='total'>{name} {len(pts)}건 ({sums})</div>", unsafe_allow_html=True)
    if pts.empty:
        st.info("해당 기간의 포인트 내역이 없습니다.")
        return
    show_table(pts, ["date", "type", "points", "memo"], "points",
               lambda n: "오류" if pd.isna(n) else f"{int(n):,}P")
    edit_point(pts)


def edit_point(view):
    """지출 수정/삭제 폼과 같은 형태"""
    labels = {r.id: f"{r.date} · {r.type} · {r.points}P" + (f" · {r.memo}" if r.memo else "")
              for r in view.sort_values(["date", "created_at"], ascending=False).itertuples()}  # 표와 같은 최신순
    sel = st.selectbox("수정/삭제할 포인트 항목", list(labels), format_func=labels.get, key="edit_point_sel")
    row = view[view["id"] == sel].iloc[0]
    types = POINT_TYPES if row.type in POINT_TYPES else POINT_TYPES + [row.type]  # 옛 값 보존
    with st.form("edit_point_form"):
        d = st.date_input("날짜", pd.Timestamp(row.date).date(), key=f"pe_d_{sel}")
        ptype = st.radio("구분", types, index=types.index(row.type), horizontal=True, key=f"pe_t_{sel}")
        points = st.number_input("포인트", min_value=0, step=100,
                                 value=0 if pd.isna(row.points) else int(row.points), key=f"pe_p_{sel}")
        memo = st.text_input("메모", row.memo, key=f"pe_m_{sel}")
        confirm = st.checkbox("삭제 확인", key=f"pe_x_{sel}")
        c1, c2 = st.columns(2)
        save = c1.form_submit_button("수정 저장", width="stretch", type="primary")
        delete = c2.form_submit_button("삭제", width="stretch")

    if not (save or delete):
        return
    pts = load_points()  # 최신 파일 기준으로 처리
    idx = pts.index[pts["id"] == sel]
    if idx.empty:
        st.error("이미 삭제된 항목입니다.")
    elif delete:
        if not confirm:
            st.warning("'삭제 확인'을 체크한 뒤 삭제를 눌러주세요.")
        else:
            save_points(pts.drop(idx))
            flash("포인트 내역을 삭제했습니다.")
    elif points < 1:
        st.error("포인트는 1 이상이어야 합니다.")
    else:
        pts.loc[idx, ["date", "type", "points", "memo"]] = [d.isoformat(), ptype, int(points), memo.strip()]
        save_points(pts)
        flash("포인트 내역을 수정했습니다.")


def stats_tab(df, pts):
    period = period_picker("stats_period")
    if period:
        view = filter_df(df, *period)
        sums = category_sums(view)
        cats = CATEGORIES + [c for c in sums.index if c not in CATEGORIES]  # 지출 없는 카테고리도 0원으로
        rows = "".join(f"<div class='row'><span>{c}</span><b>{won(sums.get(c, 0))}</b></div>" for c in cats)
        rows += f"<div class='row total'><span>합계 ({len(view)}건)</span><b>{won(view['amount'].sum())}</b></div>"
        st.markdown(f"<div class='sum-list'>{rows}</div>", unsafe_allow_html=True)

    earn, used, bal = point_summary(pts)  # 기간 선택과 무관한 전체 누적
    st.markdown(f"""<div class='point-card'>
<div class='title'>🟢 네이버포인트 (전체 누적)</div>
<div class='row'><span>총 적립 포인트</span><b>{earn:,}P</b></div>
<div class='row'><span>총 차감(사용) 포인트</span><b>{used:,}P</b></div>
<div class='row total'><span>포인트 잔액</span><b>{bal:,}P</b></div>
<div class='note'>기간 선택과 관계없이 전체 내역 기준입니다.</div>
</div>""", unsafe_allow_html=True)


def copy_button(text):
    """보고 텍스트 복사 버튼. 복사는 브라우저에서 해야 하므로 JS로 처리.
    폰에서 http://192.168.. 로 접속하면 navigator.clipboard 가 막혀 있어 execCommand('copy')로 대체."""
    data = json.dumps(text).replace("</", "<\\/")  # 스크립트 태그 탈출 방지
    st.html(f"""<button id="copy-report" class="copy-btn">보고 텍스트 복사</button>
<div id="copy-msg" class="copy-msg" hidden></div>
<script>
document.getElementById("copy-report").onclick = async () => {{
  const text = {data}, msg = document.getElementById("copy-msg");
  let ok = false;
  try {{ await navigator.clipboard.writeText(text); ok = true; }} catch (e) {{}}
  if (!ok) {{
    const t = document.createElement("textarea");
    t.value = text; t.style.cssText = "position:fixed;opacity:0"; document.body.appendChild(t);
    t.select(); ok = document.execCommand("copy"); t.remove();
  }}
  msg.textContent = ok ? "클립보드에 복사되었습니다!" : "복사하지 못했습니다. 위 텍스트를 길게 눌러 복사해 주세요.";
  msg.className = "copy-msg " + (ok ? "ok" : "fail"); msg.hidden = false;
}};
</script>""", unsafe_allow_javascript=True)


def expenses_txt(df):
    """메모장용 지출 전체 내역 (날짜순)"""
    lines = [f"[주방지출 전체 내역] {date.today()} 기준 · {len(df)}건 · 합계 {won(df['amount'].sum())}", ""]
    for r in df.sort_values(["date", "created_at"]).itertuples():
        extra = "".join(f" / {x}" for x in [r.item, r.memo] if x)
        lines.append(f"{r.date} | {r.category} | {won(r.amount)} | {r.place or '-'}{extra}")
    return "\n".join(lines) + "\n"


def points_txt(pts):
    """메모장용 N포인트 전체 내역 (날짜순)"""
    earn, used, bal = point_summary(pts)
    lines = [f"[N포인트 전체 내역] {date.today()} 기준 · {len(pts)}건 · 적립 {earn:,}P · 사용 {used:,}P · 잔액 {bal:,}P", ""]
    for r in pts.sort_values(["date", "created_at"]).itertuples():
        amount = "오류" if pd.isna(r.points) else f"{int(r.points):,}P"
        lines.append(f"{r.date} | {r.type} | {amount}" + (f" | {r.memo}" if r.memo else ""))
    return "\n".join(lines) + "\n"


def report_tab(df, pts):
    today = date.today()
    months = {(t.year, t.month) for t in parse_dates(df).dropna()} | {(today.year, today.month)}
    c1, c2 = st.columns(2)
    year, month = c1.selectbox("보고 월", sorted(months, reverse=True), format_func=lambda m: f"{m[0]}년 {m[1]}월")
    weeks = month_weeks(year, month)
    this_week = week_of(today) if (year, month) == (today.year, today.month) else 1
    w = c2.selectbox("주차", list(weeks), index=this_week - 1,
                     format_func=lambda n: f"{n}주차 ({md(weeks[n][0])}~{md(weeks[n][1])})")
    if st.button("보고 텍스트 생성", width="stretch", type="primary"):
        st.session_state["report"] = (year, month, w)
    if st.session_state.get("report") == (year, month, w):
        text = build_report(df, pts, year, month, w)
        copy_button(text)
        with st.container(key="report_box"):  # st.code 자체 복사 아이콘은 CSS로 숨김 (복사 버튼 하나로 통일)
            st.code(text, language=None)
        st.download_button("보고서 TXT 다운로드", text.encode(ENCODING), f"주방비주간보고_{year}-{month:02d}_{w}주차.txt",
                           "text/plain", width="stretch", on_click="ignore")

    st.divider()
    st.markdown("**전체 데이터 백업**")
    stamp = today.strftime("%Y%m%d")
    csv = lambda p: p.read_bytes() if p.exists() else b""  # CSV는 저장 파일 그대로
    files = [("지출 TXT", expenses_txt(df).encode(ENCODING), f"지출내역_{stamp}.txt", "text/plain"),
             ("포인트 TXT", points_txt(pts).encode(ENCODING), f"포인트내역_{stamp}.txt", "text/plain"),
             ("지출 CSV", csv(DATA_FILE), f"expenses_{stamp}.csv", "text/csv"),
             ("포인트 CSV", csv(POINT_FILE), f"points_{stamp}.csv", "text/csv")]
    with st.container(key="backup"):  # 폰 폭에서도 4칸 한 줄 (CSS)
        for col, (label, data, name, mime) in zip(st.columns(4), files):
            col.download_button(label, data, name, mime, width="stretch", disabled=not data,
                                on_click="ignore")  # 다운로드는 재실행 불필요


def summary_cards(df, pts):
    """탭 위 요약: 이번 주(일~토) / 이번 달(1일~말일) 총지출. N포인트 탭에서는 사용가능포인트 카드 하나"""
    if st.session_state.get("tab") == "N포인트":  # 탭은 key="tab"으로 선택 상태를 서버가 기억
        earn, used, bal = point_summary(pts)
        st.markdown(f"<div class='sum-card point-balance'><span>사용가능포인트</span><b>{bal:,}P</b>"
                    f"<small>총 적립 {earn:,}P · 총 사용 {used:,}P (전체 누적)</small></div>", unsafe_allow_html=True)
        return
    today = date.today()
    sunday = week_start(today)
    periods = [("이번 주", sunday, sunday + timedelta(days=6)), ("이번 달", today.replace(day=1), month_end(today))]
    with st.container(key="summary"):
        for col, (title, start, end) in zip(st.columns(2), periods):
            col.markdown(f"<div class='sum-card'><span>{title}</span><b>{won(filter_df(df, start, end)['amount'].sum())}</b>"
                         f"<small>{start:%m/%d}~{end:%m/%d}</small></div>", unsafe_allow_html=True)


def main():
    st.set_page_config(page_title="주방지출관리", page_icon="🍳", layout="centered")
    st.markdown(CSS, unsafe_allow_html=True)
    # Streamlit 기본 <html lang="en"> 때문에 브라우저 자동번역이 "20P"를 "20펜스"(pence)로 바꿈 → 한국어·번역 금지로 표시
    st.html("<span id='lang-fix'></span><script>const h = document.documentElement; h.lang = 'ko'; h.setAttribute('translate', 'no');"
            " h.classList.add('notranslate');</script>", unsafe_allow_javascript=True)
    st.markdown(f"<div class='app-header'><h1>🍳 주방지출관리</h1><p>{date.today():%Y년 %m월 %d일}</p></div>",
                unsafe_allow_html=True)

    try:
        df = load_data()
        pts = load_points()
    except Exception as e:
        st.error(f"데이터 파일을 읽을 수 없습니다: {e}\n\nexpenses.csv / points.csv 파일을 확인해 주세요. (저장은 중단됨)")
        st.stop()

    if msg := st.session_state.pop("flash", None):
        st.toast(msg, icon="✅")  # 화면 위쪽에 끼어들지 않아 레이아웃이 밀리지 않음
    bad_amount = int(df["amount"].isna().sum()) + int(pts["points"].isna().sum())
    bad_date = int(parse_dates(df).isna().sum()) + int(parse_dates(pts).isna().sum())
    if bad_amount:
        st.warning(f"금액/포인트 오류 {bad_amount}건 (합계에서 제외됨)")
    if bad_date:
        st.warning(f"날짜 오류 {bad_date}건 (기간 조회에서 제외됨)")

    summary_cards(df, pts)

    # key + on_change: 선택 탭을 서버(session_state["tab"])가 기억 → 재실행·저장 후에도 탭 유지
    tab_input, tab_list, tab_points, tab_stats, tab_report = st.tabs(
        ["지출 입력", "지출 내역", "N포인트", "통계·합계", "보고·백업"], key="tab", on_change="rerun")
    with tab_input:
        input_tab()
    with tab_list:
        list_tab(df)
    with tab_points:
        points_tab(pts)
    with tab_stats:
        stats_tab(df, pts)
    with tab_report:
        report_tab(df, pts)


if __name__ == "__main__":
    main()
