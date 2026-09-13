"""주방지출관리 - Streamlit 화면.

실행: run.bat 더블클릭 또는 `streamlit run app.py`
"""

import html
import re

import pandas as pd
import streamlit as st

import db
import utils

st.set_page_config(
    page_title="주방지출관리",
    page_icon="💳",
    layout="centered",
    initial_sidebar_state="collapsed",
)

db.init_db()

PAGE_SIZE = 20
CATEGORY_ALL = "전체"
AMOUNT_STEP = 1000

_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$])")


def md_escape(text) -> str:
    """사용자 입력 문자열이 마크다운으로 해석되지 않도록 이스케이프한다."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", str(text))


def h(text) -> str:
    """사용자 입력 문자열을 HTML에 넣기 전에 이스케이프한다."""
    return html.escape(str(text))


def format_card_date(iso_date: str) -> str:
    """카드 날짜 표시: 올해는 MM/DD, 다른 해는 YYYY/MM/DD."""
    d = utils.from_iso(iso_date)
    return d.strftime("%m/%d") if d.year == utils.today_kst().year else d.strftime("%Y/%m/%d")


# ---------------------------------------------------------------------------
# 모바일 스타일
#
# Streamlit 내부 구조에 최소한으로만 의존한다.
# 용도: 글꼴 크기(iOS 확대 방지 포함), 버튼 터치 영역, 상단 합계/카드/통계의 커스텀 HTML.
# ---------------------------------------------------------------------------

_CSS = """
<style>
/* 전역: 본문 16px, 상단 여백 축소 */
html { font-size: 16px; }
[data-testid="stMainBlockContainer"] { padding-top: 3rem; padding-bottom: 4rem; }

/* iOS Safari는 16px 미만 입력칸을 누르면 화면을 확대하므로 16px 이상 유지 */
input, textarea, select { font-size: 16px !important; }

/* 버튼 터치 영역 44px 이상 (일반/폼/다운로드 버튼, 기간·카테고리 선택 버튼) */
[data-testid^="stBaseButton-"] { min-height: 44px; }

/* 금액 입력(등록·수정): 빈 칸에서 비활성화되는 작은 기본 +/- 대신 큰 ±1,000 버튼을 쓰므로 기본 버튼은 숨김 */
[class*="st-key-add_amount_v"] [data-testid="stNumberInputStepUp"],
[class*="st-key-add_amount_v"] [data-testid="stNumberInputStepDown"],
[class*="st-key-edit_amount_"] [data-testid="stNumberInputStepUp"],
[class*="st-key-edit_amount_"] [data-testid="stNumberInputStepDown"] { display: none; }

/* 앱 제목 / 탭 안 섹션 제목 */
.app-title { font-size: 1.5rem; font-weight: 700; line-height: 1.3; margin: 0; }
.section-title { font-size: 1.2rem; font-weight: 700; margin: 0.25rem 0 0; }

/* 상단 합계 2칸: 금액 20px 이상(PRD U2), 넘치면 금액 줄바꿈 */
.summary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.4rem; }
.summary-card {
  min-width: 0; text-align: center; padding: 0.55rem 0.2rem;
  border: 1px solid rgba(128, 128, 128, 0.35); border-radius: 0.75rem;
}
.summary-label { font-size: 0.875rem; opacity: 0.75; }
.summary-amount {
  font-size: clamp(1.25rem, 5.6vw, 1.75rem); font-weight: 700; line-height: 1.25;
  overflow-wrap: anywhere;
}
.summary-amount .won { font-size: 0.8em; font-weight: 600; }
.summary-sub { font-size: 0.8rem; opacity: 0.6; }

/* 지출 카드 */
.result-summary { font-size: 1.05rem; }
.exp-meta { font-size: 0.875rem; opacity: 0.65; }
.exp-amount { font-size: 1.4rem; font-weight: 700; line-height: 1.3; }
.exp-place { font-size: 1rem; overflow-wrap: anywhere; }
.exp-memo { font-size: 0.9rem; opacity: 0.65; overflow-wrap: anywhere; }

/* 카테고리별 합계: 이름 왼쪽, 금액 오른쪽 */
.stat-row, .stat-total { display: flex; justify-content: space-between; gap: 0.75rem; padding: 0.5rem 0; }
.stat-row { border-bottom: 1px solid rgba(128, 128, 128, 0.2); }
.stat-row .stat-amount { font-weight: 600; white-space: nowrap; }
.stat-total {
  font-size: 1.1rem; font-weight: 700; margin-top: 0.25rem;
  border-top: 2px solid rgba(128, 128, 128, 0.5);
}
.stat-total span:last-child { white-space: nowrap; }

/* 보고 텍스트 복사 버튼 */
.report-copy-btn {
  width: 100%; min-height: 48px; border: 0; border-radius: 0.5rem;
  background: #15803d; color: #ffffff; font-size: 1.05rem; font-weight: 600; cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.report-copy-btn:active { opacity: 0.85; }
.report-copy-msg { min-height: 1.5rem; margin-top: 0.4rem; font-size: 0.95rem; }
.report-copy-msg.ok { color: #15803d; }
.report-copy-msg.fail { color: #b91c1c; }
</style>
"""


def inject_css():
    st.html(_CSS)


# ---------------------------------------------------------------------------
# 콜백
#
# 콜백은 스크립트 재실행 전에 호출되므로 여기서 session_state를 바꾸면
# 바로 다음 화면에 반영된다. session_state에는 UI 상태만 저장하고 합계는 저장하지 않는다.
# ---------------------------------------------------------------------------

def set_flash(message):
    st.session_state["flash"] = message


def add_key(name):
    """등록할 때마다 새로 만드는 입력칸(금액·사용처·메모)의 위젯 key.

    등록에 성공하면 add_version을 올려 새 빈 입력칸으로 교체한다.
    값을 None/""로 덮어쓰는 방식보다 이전 입력값이 되살아날 여지가 없다.
    """
    return f"add_{name}_v{st.session_state.get('add_version', 0)}"


def add_date_key(today):
    """날짜 입력칸 key. 날짜가 바뀌면 새 입력칸이 되어 기본값이 다시 '오늘'이 된다.

    페이지를 열어 둔 채 자정이 지나도 어제 날짜로 등록되지 않게 하기 위함이다.
    같은 날 안에서는 사용자가 고른 날짜가 유지된다.
    """
    return f"add_date_{utils.to_iso(today)}"


def handle_add_expense():
    """[지출 등록] 콜백.

    성공 시 금액·사용처·메모만 새 빈 칸으로 바꾸고 날짜·카테고리는 유지한다.
    실패 시 입력값은 그대로 두고 오류 메시지를 저장한다.
    """
    ss = st.session_state
    cleaned, errors = utils.validate_expense(
        ss.get(ss.get("add_date_key")),  # 화면에 그려진 날짜 입력칸 (render_add_tab에서 기록)
        ss.get(add_key("amount")),
        ss.get("add_category"),
        ss.get(add_key("place")),
        ss.get(add_key("memo")),
    )
    if errors:
        ss["add_errors"] = errors
        return

    db.add_expense(created_at=utils.now_kst_str(), **cleaned)

    ss["add_errors"] = []
    ss["add_version"] = ss.get("add_version", 0) + 1
    set_flash(f"✅ {utils.format_won(cleaned['amount'])} 등록 완료")


def step_amount(key, delta):
    """±1,000 버튼 공통 처리 (등록·수정 폼).

    비어 있을 때 +는 1,000부터 시작한다. 1원 미만이 되는 경우에는 바꾸지 않고 안내한다.
    """
    ss = st.session_state
    current = ss.get(key)
    if delta > 0:
        ss[key] = min((current or 0) + delta, utils.MAX_AMOUNT)
    elif current is not None:
        if current + delta >= 1:
            ss[key] = current + delta
        else:
            set_flash(f"{AMOUNT_STEP:,}원 이하에서는 더 줄일 수 없습니다.")


def increase_add_amount():
    step_amount(add_key("amount"), AMOUNT_STEP)


def decrease_add_amount():
    step_amount(add_key("amount"), -AMOUNT_STEP)


def start_edit(expense_id):
    ss = st.session_state
    ss["editing_id"] = expense_id
    ss["deleting_id"] = None
    ss["edit_errors"] = []


def cancel_edit():
    st.session_state["editing_id"] = None
    st.session_state["edit_errors"] = []


def save_edit(expense_id):
    ss = st.session_state
    cleaned, errors = utils.validate_expense(
        ss.get(f"edit_date_{expense_id}"),
        ss.get(f"edit_amount_{expense_id}"),
        ss.get(f"edit_category_{expense_id}"),
        ss.get(f"edit_place_{expense_id}"),
        ss.get(f"edit_memo_{expense_id}"),
    )
    if errors:
        ss["edit_errors"] = errors
        return

    if db.update_expense(expense_id, **cleaned):
        set_flash(f"✏️ {utils.format_won(cleaned['amount'])} 수정 완료")
    else:
        set_flash("이미 삭제된 내역입니다.")
    ss["editing_id"] = None
    ss["edit_errors"] = []


def request_delete(expense_id):
    st.session_state["deleting_id"] = expense_id
    st.session_state["editing_id"] = None


def cancel_delete():
    st.session_state["deleting_id"] = None


def confirm_delete(expense_id):
    if db.delete_expense(expense_id):
        set_flash("🗑️ 삭제 완료")
    else:
        set_flash("이미 삭제된 내역입니다.")
    st.session_state["deleting_id"] = None


def show_more():
    st.session_state["list_limit"] = st.session_state.get("list_limit", PAGE_SIZE) + PAGE_SIZE


def activate_report(signature):
    st.session_state["report_signature"] = signature


# ---------------------------------------------------------------------------
# 공통 화면 요소
# ---------------------------------------------------------------------------

def render_period_picker(prefix, options, default):
    """기간 선택 + (직접 선택 시) 시작일·종료일. 반환: (라벨, 시작일, 종료일, 오류 메시지).

    선택지가 많아 375px에서 한 줄에 들어가지 않으므로 줄바꿈되는 pills를 사용한다.
    """
    label = st.pills("기간", options, default=default, required=True, key=f"{prefix}_period")
    today = utils.today_kst()
    custom = label == utils.PERIOD_CUSTOM
    custom_start = custom_end = None
    if custom:
        month_start, _ = utils.month_range(today)
        col_start, col_end = st.columns(2, wrap=False)
        with col_start:
            custom_start = st.date_input("시작일", value=month_start, key=f"{prefix}_start", format="YYYY-MM-DD")
        with col_end:
            custom_end = st.date_input("종료일", value=today, key=f"{prefix}_end", format="YYYY-MM-DD")
    start, end = utils.resolve_period(label, today, custom_start, custom_end)
    return label, start, end, utils.validate_period(start, end, custom)


def summary_card_html(label, amount, sub):
    number = f"{int(amount):,}"
    return (
        '<div class="summary-card">'
        f'<div class="summary-label">{h(label)}</div>'
        f'<div class="summary-amount">{number}<span class="won">원</span></div>'
        f'<div class="summary-sub">{h(sub)}</div>'
        "</div>"
    )


def render_summary():
    """상단 합계 요약: 이번 주 / 이번 달 (매번 DB 원본에서 계산)."""
    today = utils.today_kst()
    week_start, week_end = utils.week_range(today)
    month_start, month_end = utils.month_range(today)

    week_total, _ = db.get_total(utils.to_iso(week_start), utils.to_iso(week_end))
    month_total, _ = db.get_total(utils.to_iso(month_start), utils.to_iso(month_end))

    st.html(
        '<div class="summary-grid">'
        + summary_card_html("이번 주", week_total, utils.format_range_short(week_start, week_end))
        + summary_card_html("이번 달", month_total, utils.format_range_short(month_start, month_end))
        + "</div>"
    )


# ---------------------------------------------------------------------------
# [지출 입력] 탭
# ---------------------------------------------------------------------------

def render_add_tab():
    # 모든 입력칸과 ±1,000 버튼을 한 폼에 둔다. ±1,000도 폼 제출 버튼이라 누르는 순간
    # 입력 중인 값이 함께 전달되고, 입력칸이 따로 서버에 값을 보내지 않아
    # "금액 입력 직후 [지출 등록]" 때 신호가 엇갈려 입력칸이 안 비워지는 문제가 생기지 않는다.
    # Enter 키 제출은 끈다. (켜 두면 첫 번째 제출 버튼인 −1,000이 눌릴 수 있음)
    today = utils.today_kst()
    date_key = add_date_key(today)
    st.session_state["add_date_key"] = date_key
    with st.form("add_form", border=False, enter_to_submit=False):
        st.date_input("날짜", value=today, key=date_key, format="YYYY-MM-DD")
        st.number_input(
            "금액 (원)",
            min_value=1,
            max_value=utils.MAX_AMOUNT,
            value=None,
            step=AMOUNT_STEP,
            format="%d",
            key=add_key("amount"),
            placeholder="숫자 입력 또는 +1,000 버튼",
        )
        col_minus, col_plus = st.columns(2, wrap=False)
        with col_minus:
            st.form_submit_button("− 1,000", key="add_minus", width="stretch", on_click=decrease_add_amount)
        with col_plus:
            st.form_submit_button("+ 1,000", key="add_plus", width="stretch", on_click=increase_add_amount)
        # "입력 금액: …" 확인 표시는 두지 않는다. 폼 안 입력값은 제출 전까지 서버에 전달되지 않아
        # 직접 입력 중인 금액과 다른 값을 보여주게 된다.

        st.segmented_control(
            "카테고리",
            utils.CATEGORIES,
            default=utils.CATEGORIES[0],
            required=True,
            key="add_category",
            width="stretch",
        )
        st.text_input(
            "사용처",
            max_chars=utils.PLACE_MAX_LEN,
            key=add_key("place"),
            placeholder="예: 이마트 (선택 입력)",
        )
        st.text_input(
            "메모",
            max_chars=utils.MEMO_MAX_LEN,
            key=add_key("memo"),
            placeholder="(선택 입력)",
        )
        st.form_submit_button(
            "지출 등록",
            type="primary",
            width="stretch",
            on_click=handle_add_expense,
        )

    for message in st.session_state.get("add_errors", []):
        st.error(message)


# ---------------------------------------------------------------------------
# [지출 내역] 탭
# ---------------------------------------------------------------------------

def render_list_tab():
    ss = st.session_state
    period_label, start, end, error = render_period_picker("list", utils.LIST_PERIODS, utils.PERIOD_THIS_MONTH)
    category_label = st.pills(
        "카테고리",
        [CATEGORY_ALL] + utils.CATEGORIES,
        default=CATEGORY_ALL,
        required=True,
        key="list_category",
    )
    if error:
        st.error(error)
        render_table_toggle()  # 오류일 때도 그려야 토글이 꺼지지 않는다
        return

    category = None if category_label == CATEGORY_ALL else category_label

    # 필터가 바뀌면 표시 개수와 수정/삭제 상태를 초기화한다.
    signature = (period_label, utils.iso_or_none(start), utils.iso_or_none(end), category)
    if ss.get("list_signature") != signature:
        ss["list_signature"] = signature
        ss["list_limit"] = PAGE_SIZE
        ss["editing_id"] = None
        ss["deleting_id"] = None

    start_iso, end_iso = utils.iso_or_none(start), utils.iso_or_none(end)
    rows = db.get_expenses(start_iso, end_iso, category)
    total, count = db.get_total(start_iso, end_iso, category)

    st.html(
        f'<div class="result-summary">조회 결과 <b>{count:,}건</b> · 합계 <b>{utils.format_won(total)}</b></div>'
    )

    if count == 0:
        st.info("해당 조건의 지출 내역이 없습니다.")
    elif ss.get("list_table", False):
        render_expense_table(rows)
    else:
        limit = ss.get("list_limit", PAGE_SIZE)
        for row in rows[:limit]:
            render_expense_card(row)
        if count > limit:
            st.button(
                f"더 보기 ({limit:,} / {count:,}건 표시 중)",
                key="list_more",
                width="stretch",
                on_click=show_more,
            )

    render_table_toggle()


def render_table_toggle():
    # PC용 보조 기능이라 목록 아래에 둔다.
    st.toggle("표로 보기 (PC)", key="list_table")


def render_expense_table(rows):
    df = pd.DataFrame(
        [
            {
                "날짜": row["expense_date"],
                "카테고리": row["category"],
                "금액": row["amount"],
                "사용처": row["place"],
                "메모": row["memo"],
            }
            for row in rows
        ]
    )
    st.dataframe(
        df,
        hide_index=True,
        column_config={"금액": st.column_config.NumberColumn("금액(원)", format="localized")},
    )
    st.caption("수정·삭제는 '표로 보기'를 끄고 카드 목록에서 할 수 있습니다. 좁은 화면에서는 표를 옆으로 밀어서 보세요.")


def expense_card_html(row) -> str:
    parts = [
        f'<div class="exp-meta">{h(format_card_date(row["expense_date"]))} · {h(row["category"])}</div>',
        f'<div class="exp-amount">{h(utils.format_won(row["amount"]))}</div>',
    ]
    if row["place"]:
        parts.append(f'<div class="exp-place">{h(row["place"])}</div>')
    if row["memo"]:
        parts.append(f'<div class="exp-memo">{h(row["memo"])}</div>')
    return "".join(parts)


def render_expense_card(row):
    ss = st.session_state
    expense_id = row["id"]

    with st.container(border=True):
        if ss.get("editing_id") == expense_id:
            render_edit_form(row)
            return

        st.html(expense_card_html(row))

        if ss.get("deleting_id") == expense_id:
            st.warning(
                f"정말 삭제할까요? {utils.format_won(row['amount'])} · "
                f"{md_escape(utils.dash_if_empty(row['place']))}"
            )
            col_left, col_right = st.columns(2, wrap=False)
            with col_left:
                st.button(
                    "삭제 확정",
                    key=f"confirm_delete_{expense_id}",
                    type="primary",
                    width="stretch",
                    on_click=confirm_delete,
                    args=(expense_id,),
                )
            with col_right:
                st.button("취소", key=f"cancel_delete_{expense_id}", width="stretch", on_click=cancel_delete)
        else:
            col_left, col_right = st.columns(2, wrap=False)
            with col_left:
                st.button(
                    "수정",
                    key=f"edit_{expense_id}",
                    width="stretch",
                    on_click=start_edit,
                    args=(expense_id,),
                )
            with col_right:
                st.button(
                    "삭제",
                    key=f"delete_{expense_id}",
                    width="stretch",
                    on_click=request_delete,
                    args=(expense_id,),
                )


def render_edit_form(row):
    expense_id = row["id"]
    # 기본 목록에 없는 예전 카테고리도 수정 폼에서 표시는 되도록 한다. (저장 시에는 기본 카테고리만 허용)
    options = utils.CATEGORIES if row["category"] in utils.CATEGORIES else utils.CATEGORIES + [row["category"]]

    amount_key = f"edit_amount_{expense_id}"
    # 금액칸은 value=None으로 만들고 기존 금액은 session_state로 채운다.
    # value에 금액을 넣으면 ±1,000 버튼이 session_state로 값을 바꿀 때 Streamlit 경고가 뜬다.
    # key가 없을 때만 채우므로, 사용자가 지운 값(None)이나 ±로 바꾼 값은 유지된다.
    if amount_key not in st.session_state:
        st.session_state[amount_key] = row["amount"]

    # Enter 키 제출은 끈다. (켜 두면 첫 번째 제출 버튼인 −1,000이 눌릴 수 있음)
    with st.form(f"edit_form_{expense_id}", border=False, enter_to_submit=False):
        st.date_input(
            "날짜",
            value=utils.from_iso(row["expense_date"]),
            key=f"edit_date_{expense_id}",
            format="YYYY-MM-DD",
        )
        st.number_input(
            "금액 (원)",
            min_value=1,
            max_value=utils.MAX_AMOUNT,
            value=None,
            step=AMOUNT_STEP,
            format="%d",
            key=amount_key,
        )
        col_minus, col_plus = st.columns(2, wrap=False)
        with col_minus:
            st.form_submit_button(
                "− 1,000",
                key=f"edit_minus_{expense_id}",
                width="stretch",
                on_click=step_amount,
                args=(amount_key, -AMOUNT_STEP),
            )
        with col_plus:
            st.form_submit_button(
                "+ 1,000",
                key=f"edit_plus_{expense_id}",
                width="stretch",
                on_click=step_amount,
                args=(amount_key, AMOUNT_STEP),
            )
        st.segmented_control(
            "카테고리",
            options,
            default=row["category"],
            required=True,
            key=f"edit_category_{expense_id}",
            width="stretch",
        )
        st.text_input(
            "사용처",
            value=row["place"],
            max_chars=utils.PLACE_MAX_LEN,
            key=f"edit_place_{expense_id}",
            placeholder="(선택 입력)",
        )
        st.text_input(
            "메모",
            value=row["memo"],
            max_chars=utils.MEMO_MAX_LEN,
            key=f"edit_memo_{expense_id}",
            placeholder="(선택 입력)",
        )
        col_save, col_cancel = st.columns(2, wrap=False)
        with col_save:
            st.form_submit_button(
                "저장",
                type="primary",
                width="stretch",
                on_click=save_edit,
                args=(expense_id,),
            )
        with col_cancel:
            st.form_submit_button("취소", width="stretch", on_click=cancel_edit)

    for message in st.session_state.get("edit_errors", []):
        st.error(message)


# ---------------------------------------------------------------------------
# [통계·합계] 탭
# ---------------------------------------------------------------------------

def render_stats_tab():
    _, start, end, error = render_period_picker("stats", utils.STATS_PERIODS, utils.PERIOD_THIS_MONTH)
    if error:
        st.error(error)
        return

    start_iso, end_iso = utils.iso_or_none(start), utils.iso_or_none(end)
    category_totals = utils.order_category_totals(db.get_category_totals(start_iso, end_iso))
    total, count = db.get_total(start_iso, end_iso)

    st.caption(f"기간: {utils.format_period(start, end)}")
    rows_html = "".join(
        f'<div class="stat-row"><span>{h(category)}</span>'
        f'<span class="stat-amount">{h(utils.format_won(amount))}</span></div>'
        for category, amount in category_totals
    )
    st.html(
        rows_html
        + f'<div class="stat-total"><span>합계 ({count:,}건)</span><span>{h(utils.format_won(total))}</span></div>'
    )


# ---------------------------------------------------------------------------
# [보고·백업] 탭
# ---------------------------------------------------------------------------

def build_report(period_label, start, end):
    """보고 텍스트를 매번 DB 원본에서 새로 만든다."""
    start_iso, end_iso = utils.to_iso(start), utils.to_iso(end)
    rows = db.get_expenses(start_iso, end_iso, order="asc")
    total, _ = db.get_total(start_iso, end_iso)
    return utils.build_report_text(
        period_label, start, end, rows, db.get_category_totals(start_iso, end_iso), total
    )


def build_backup_bytes(backup_at):
    """전체 DB로 TXT 백업 내용을 만든다. 백업 일시는 파일명과 같은 backup_at을 쓴다."""
    rows = db.get_expenses(order="desc")
    total, count = db.get_total()
    text = utils.build_backup_text(rows, db.get_category_totals(), total, count, backup_at)
    return text.encode("utf-8-sig")


_REPORT_COPY_SCRIPT = """
<script>
(function () {
  // st.html은 화면이 갱신될 때마다 다시 그려지므로 클릭 처리는 문서에 한 번만 등록한다.
  if (window.__reportCopyInstalled) return;
  window.__reportCopyInstalled = true;

  // iPhone Safari는 http://192.168.x.x 같은 주소(비보안 컨텍스트)에서 navigator.clipboard를 쓸 수 없다.
  // 버튼을 누른 순간(사용자 동작 안에서) 임시 textarea를 선택해 execCommand('copy')로 복사한다.
  function copyWithTextarea(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');  // iOS에서 키보드가 올라오지 않게
    ta.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;padding:0;border:0;opacity:0;font-size:16px;';
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length);  // iOS Safari는 select()만으로는 선택되지 않는다
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    if (window.getSelection) { window.getSelection().removeAllRanges(); }
    return ok;
  }

  document.addEventListener('click', function (event) {
    var btn = event.target.closest ? event.target.closest('.report-copy-btn') : null;
    if (!btn) return;
    var box = btn.closest('.report-copy');
    var text = box.querySelector('.report-copy-src').value;
    var msg = box.querySelector('.report-copy-msg');
    function show(ok) {
      msg.className = 'report-copy-msg ' + (ok ? 'ok' : 'fail');
      msg.textContent = ok
        ? '✅ 복사되었습니다. 카카오톡이나 메모에 붙여넣으세요.'
        : '⚠️ 복사하지 못했습니다. 아래 칸을 길게 눌러 전체 선택 후 복사해 주세요.';
    }
    if (copyWithTextarea(text)) { show(true); return; }
    // https / localhost에서는 표준 클립보드 API로 한 번 더 시도한다.
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { show(true); }, function () { show(false); });
      return;
    }
    show(false);
  });
})();
</script>
"""


def render_report_copy_button(report_text):
    """보고 텍스트 전체를 클립보드에 복사하는 버튼.

    st.code의 복사 아이콘은 navigator.clipboard를 써서 iPhone(http LAN 주소)에서 동작하지 않는다.
    보고 텍스트(사용자 입력 포함)는 스크립트에 넣지 않고, 이스케이프한 숨은 textarea에서 읽는다.
    """
    st.html(
        '<div class="report-copy">'
        '<button type="button" class="report-copy-btn">📋 보고 텍스트 복사</button>'
        '<div class="report-copy-msg" role="status" aria-live="polite"></div>'
        f'<textarea class="report-copy-src" readonly hidden>{h(report_text)}</textarea>'
        "</div>" + _REPORT_COPY_SCRIPT,
        unsafe_allow_javascript=True,
    )


def render_report_tab():
    st.html('<div class="section-title">📋 보고</div>')
    period_label, start, end, error = render_period_picker(
        "report", utils.REPORT_PERIODS, utils.PERIOD_THIS_WEEK
    )
    if error:
        st.error(error)
    else:
        # 생성 버튼을 누른 기간과 현재 선택 기간이 같을 때만 텍스트를 보여준다.
        signature = (period_label, utils.to_iso(start), utils.to_iso(end))
        st.button(
            "보고 텍스트 생성",
            key="report_generate",
            type="primary",
            width="stretch",
            on_click=activate_report,
            args=(signature,),
        )
        if st.session_state.get("report_signature") == signature:
            report_text = build_report(period_label, start, end)
            render_report_copy_button(report_text)
            st.code(report_text, language=None, wrap_lines=True)
            st.text_area(
                "복사 버튼이 안 되면: 아래 칸을 길게 눌러 전체 선택 후 복사",
                value=report_text,
                height=320,
            )

    st.divider()

    st.html('<div class="section-title">💾 TXT 백업</div>')
    total, count = db.get_total()
    st.html(
        f'<div class="result-summary">현재 저장된 지출 <b>{count:,}건</b> · 합계 <b>{utils.format_won(total)}</b></div>'
    )
    # 파일명, 파일 안 백업 일시, 내용, 위의 건수·합계 안내를 모두 같은 화면 갱신 시점 기준으로 맞춘다.
    backup_at = utils.now_kst()
    st.download_button(
        "TXT 백업 다운로드",
        data=build_backup_bytes(backup_at),
        file_name=utils.backup_filename(backup_at),
        mime="text/plain",
        key="backup_download",
        type="primary",
        width="stretch",
        on_click="ignore",
    )
    st.caption("iPhone/iPad: '파일' 앱에 저장됩니다. 미리보기가 열리면 공유 버튼 → '파일에 저장'을 누르세요.")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

inject_css()
st.html('<div class="app-title">💳 주방지출관리</div>')

render_summary()

tab_add, tab_list, tab_stats, tab_report = st.tabs(["지출 입력", "지출 내역", "통계·합계", "보고·백업"])

with tab_add:
    render_add_tab()
with tab_list:
    render_list_tab()
with tab_stats:
    render_stats_tab()
with tab_report:
    render_report_tab()

# 알림은 맨 마지막에 띄운다. 화면 위쪽에 조건부 요소가 끼어들면 뒤따르는 요소 순서가
# 한 칸씩 밀려, 방금 입력하던 칸이 이전 값을 유지하는 문제가 생길 수 있다.
if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"))
