"""공통 유틸리티 (DB·Streamlit에 의존하지 않는 순수 함수).

- 한국 시간 기준 날짜/시각
- 주간·월간 날짜 범위 계산
- 금액 표시
- 입력 검증
"""

import calendar
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    KST = ZoneInfo("Asia/Seoul")
except Exception:  # tzdata가 없는 Windows 환경 대비 (한국은 서머타임이 없어 +9 고정과 동일)
    KST = timezone(timedelta(hours=9))

# 화면 표시·선택 순서도 이 순서를 따른다. (예전 "주방 식재료"는 db.init_db()에서 "평일식재료"로 바뀜)
CATEGORIES = ["평일식재료", "안식일식재료", "주방 소모품", "기타"]

MAX_AMOUNT = 100_000_000
PLACE_MAX_LEN = 50
MEMO_MAX_LEN = 200

DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------------------
# 날짜 / 시각
# ---------------------------------------------------------------------------

def now_kst() -> datetime:
    return datetime.now(KST)


def today_kst() -> date:
    return now_kst().date()


def now_kst_str() -> str:
    """DB created_at 저장용 문자열 (YYYY-MM-DD HH:MM:SS)."""
    return now_kst().strftime(DATETIME_FORMAT)


def to_iso(d: date) -> str:
    return d.strftime(DATE_FORMAT)


def from_iso(s: str) -> date:
    return datetime.strptime(s, DATE_FORMAT).date()


# ---------------------------------------------------------------------------
# 기간 계산 (모든 범위는 시작일·종료일 포함)
# ---------------------------------------------------------------------------

def week_range(base: date) -> tuple[date, date]:
    """base가 속한 주의 월요일 ~ 일요일."""
    start = base - timedelta(days=base.weekday())  # 월=0 ... 일=6
    return start, start + timedelta(days=6)


def last_week_range(base: date) -> tuple[date, date]:
    this_start, _ = week_range(base)
    return this_start - timedelta(days=7), this_start - timedelta(days=1)


def month_range(base: date) -> tuple[date, date]:
    """base가 속한 달의 1일 ~ 말일."""
    last_day = calendar.monthrange(base.year, base.month)[1]
    return base.replace(day=1), base.replace(day=last_day)


def last_month_range(base: date) -> tuple[date, date]:
    first_of_this_month = base.replace(day=1)
    return month_range(first_of_this_month - timedelta(days=1))


def week_of_month(week_start: date) -> tuple[int, int, int]:
    """주(월~일)가 몇 월 몇째주인지 (연, 월, 주차)를 반환한다.

    주는 일요일이 속한 달의 주로 보고, 그 달 1일이 들어 있는 주가 1주차다. (예: 8/31~9/6 → 9월 1주차)
    """
    sunday = week_start + timedelta(days=6)
    return sunday.year, sunday.month, (sunday.day - 1) // 7 + 1


def month_week_ranges(week_start: date) -> list[tuple[int, date, date]]:
    """week_start 주가 속한 달의 1주차 ~ 그 주까지 [(주차, 시작일, 종료일)]. 날짜는 그 달 안으로 자른다."""
    year, month, week_no = week_of_month(week_start)
    first_of_month = date(year, month, 1)
    first_week_start, _ = week_range(first_of_month)
    ranges = []
    for n in range(1, week_no + 1):
        start = first_week_start + timedelta(days=7 * (n - 1))
        ranges.append((n, max(start, first_of_month), start + timedelta(days=6)))
    return ranges


def format_range_short(start: date, end: date) -> str:
    """상단 요약용 짧은 기간 표시 (MM/DD~MM/DD)."""
    return f"{start:%m/%d}~{end:%m/%d}"


# ---------------------------------------------------------------------------
# 금액
# ---------------------------------------------------------------------------

def format_won(amount: int) -> str:
    """35000 -> '35,000원'."""
    return f"{int(amount):,}원"


def format_point(point: int) -> str:
    """네이버포인트 표시: 1500 -> '1,500P'."""
    return f"{int(point):,}P"


# ---------------------------------------------------------------------------
# 입력 검증
# ---------------------------------------------------------------------------

def _normalize_amount(amount):
    """정수 금액만 허용한다. 소수점이 있는 값, bool, 문자열 등은 None을 반환한다."""
    if isinstance(amount, bool):
        return None
    if isinstance(amount, int):
        return amount
    if isinstance(amount, float) and amount.is_integer():
        return int(amount)
    return None


def validate_expense(expense_date, amount, category, place, memo, point_earned=None, point_used=None):
    """지출 입력값을 검증하고 정리한다.

    네이버포인트(적립·사용)는 선택 입력이며, 비어 있으면 0으로 저장한다.

    반환: (정리된 값 dict 또는 None, 오류 메시지 list)
    오류가 하나라도 있으면 첫 번째 값은 None이다.
    """
    errors = []

    if not isinstance(expense_date, date):
        errors.append("날짜를 선택해 주세요.")

    if amount is None:
        errors.append("금액을 입력해 주세요.")
        amount_int = None
    else:
        amount_int = _normalize_amount(amount)
        if amount_int is None:
            errors.append("금액은 원 단위 정수로 입력해 주세요.")
        elif amount_int < 1:
            errors.append("금액을 1원 이상 입력해 주세요.")
        elif amount_int > MAX_AMOUNT:
            errors.append(f"금액은 {MAX_AMOUNT:,}원 이하로 입력해 주세요.")

    if category not in CATEGORIES:
        errors.append("카테고리를 선택해 주세요.")

    place = (place or "").strip()
    memo = (memo or "").strip()
    if len(place) > PLACE_MAX_LEN:
        errors.append(f"사용처는 {PLACE_MAX_LEN}자 이내로 입력해 주세요.")
    if len(memo) > MEMO_MAX_LEN:
        errors.append(f"메모는 {MEMO_MAX_LEN}자 이내로 입력해 주세요.")

    point_values = {}
    for field, label, value in (
        ("point_earned", "네이버포인트 적립", point_earned),
        ("point_used", "네이버포인트 사용", point_used),
    ):
        if value is None:
            point_values[field] = 0
            continue
        point_int = _normalize_amount(value)
        if point_int is None:
            errors.append(f"{label}는 정수로 입력해 주세요.")
        elif point_int < 0:
            errors.append(f"{label}는 0 이상으로 입력해 주세요.")
        elif point_int > MAX_AMOUNT:
            errors.append(f"{label}는 {MAX_AMOUNT:,} 이하로 입력해 주세요.")
        else:
            point_values[field] = point_int
    if (
        amount_int is not None
        and "point_used" in point_values
        and point_values["point_used"] > amount_int
    ):
        errors.append("네이버포인트 사용은 금액보다 클 수 없습니다.")

    if errors:
        return None, errors

    cleaned = {
        "expense_date": to_iso(expense_date),
        "amount": amount_int,
        "category": category,
        "place": place,
        "memo": memo,
        "point_earned": point_values["point_earned"],
        "point_used": point_values["point_used"],
    }
    return cleaned, []


# ---------------------------------------------------------------------------
# 기간 선택
# ---------------------------------------------------------------------------

PERIOD_THIS_WEEK = "이번 주"
PERIOD_LAST_WEEK = "지난 주"
PERIOD_THIS_MONTH = "이번 달"
PERIOD_LAST_MONTH = "지난 달"
PERIOD_ALL = "전체"
PERIOD_CUSTOM = "직접 선택"

LIST_PERIODS = [PERIOD_THIS_WEEK, PERIOD_THIS_MONTH, PERIOD_LAST_MONTH, PERIOD_ALL, PERIOD_CUSTOM]
STATS_PERIODS = [PERIOD_THIS_WEEK, PERIOD_LAST_WEEK, PERIOD_THIS_MONTH, PERIOD_LAST_MONTH, PERIOD_ALL, PERIOD_CUSTOM]
REPORT_PERIODS = [PERIOD_THIS_WEEK, PERIOD_LAST_WEEK, PERIOD_THIS_MONTH, PERIOD_LAST_MONTH, PERIOD_CUSTOM]


def resolve_period(label, today: date, custom_start=None, custom_end=None):
    """기간 선택 값을 (시작일, 종료일)로 바꾼다. '전체'는 (None, None)."""
    if label == PERIOD_THIS_WEEK:
        return week_range(today)
    if label == PERIOD_LAST_WEEK:
        return last_week_range(today)
    if label == PERIOD_THIS_MONTH:
        return month_range(today)
    if label == PERIOD_LAST_MONTH:
        return last_month_range(today)
    if label == PERIOD_ALL:
        return None, None
    if label == PERIOD_CUSTOM:
        return custom_start, custom_end
    raise ValueError(f"알 수 없는 기간: {label}")


def validate_period(start, end, custom: bool):
    """기간 오류 메시지를 반환한다. 문제가 없으면 None."""
    if custom and (start is None or end is None):
        return "시작일과 종료일을 선택해 주세요."
    if start is not None and end is not None and start > end:
        return "시작일이 종료일보다 늦을 수 없습니다."
    return None


def iso_or_none(d):
    return to_iso(d) if d is not None else None


def format_period(start, end) -> str:
    if start is None and end is None:
        return "전체"
    return f"{to_iso(start)} ~ {to_iso(end)}"


# ---------------------------------------------------------------------------
# 합계 정리 / 텍스트 생성
# ---------------------------------------------------------------------------

def order_category_totals(category_totals: dict) -> list[tuple[str, int]]:
    """기본 카테고리를 정해진 순서로 항상(0원 포함) 앞에 두고, 그 외 카테고리는 뒤에 붙인다."""
    ordered = [(category, int(category_totals.get(category, 0))) for category in CATEGORIES]
    extras = sorted(c for c in category_totals if c not in CATEGORIES)
    ordered.extend((category, int(category_totals[category])) for category in extras)
    return ordered


def dash_if_empty(text) -> str:
    return text if text else "-"


def report_title(period_label) -> str:
    if period_label in (PERIOD_THIS_WEEK, PERIOD_LAST_WEEK):
        return "[주간 지출 내역]"
    if period_label in (PERIOD_THIS_MONTH, PERIOD_LAST_MONTH):
        return "[월간 지출 내역]"
    return "[지출 내역]"


WEEKLY_REPORT_TITLE = "[주방비 주간 지출보고]"
WEEKDAY_NAMES = "월화수목금토일"
# 주간 보고 텍스트와 TXT 백업에서는 카테고리를 붙여 쓴다. DB·화면의 카테고리 이름은 그대로다.
REPORT_CATEGORY_LABELS = {"주방 소모품": "주방소모품"}


def is_weekly_report(period_label) -> bool:
    return period_label in (PERIOD_THIS_WEEK, PERIOD_LAST_WEEK)


def report_category(category) -> str:
    return REPORT_CATEGORY_LABELS.get(category, category)


def build_weekly_report_text(
    start: date, end: date, rows_asc, category_totals: dict, total: int,
    month_week_totals: list[tuple[int, int]], month_total: int,
    point_earned: int, point_used: int, point_balance: int,
) -> str:
    """주간 보고 텍스트 (PRD 13장). rows_asc는 날짜 오래된 순으로 정렬된 그 주의 지출 목록.

    month_week_totals는 그 달 1주차 ~ 보고 주까지 [(주차, 합계)], point_*는 이번 주 적립·사용과 누적 잔액이다.
    """
    _, month, week_no = week_of_month(start)
    lines = [
        WEEKLY_REPORT_TITLE,
        "",
        f"{month}월 {week_no}째주 ({start.month}.{start.day}~{end.month}.{end.day})",
        f"▶ 주간 지출 : {format_won(total)}",
        "",
        "① 일별 지출현황",
    ]
    if not rows_asc:
        lines.append("지출 없음")
    day_rows: dict[str, list] = {}
    for row in rows_asc:
        day_rows.setdefault(row["expense_date"], []).append(row)
    for i, (day_iso, rows) in enumerate(day_rows.items()):
        day = from_iso(day_iso)
        if i:
            lines.append("")
        lines.append(f"{day.month}/{day.day}({WEEKDAY_NAMES[day.weekday()]}) {format_won(sum(r['amount'] for r in rows))}")
        for row in rows:
            memo = f" ({row['memo']})" if row["memo"] else ""
            lines.append(
                f"· {dash_if_empty(row['place'])} / {report_category(row['category'])} : {format_won(row['amount'])}{memo}"
            )

    lines += ["", "② 주간 지출구분"]
    spent = [(c, a) for c, a in order_category_totals(category_totals) if a]
    if not spent:
        lines.append("지출 없음")
    for category, amount in spent:
        lines.append(f"{report_category(category)} : {format_won(amount)}")

    lines += ["", f"③ {month}월 누계"]
    for n, amount in month_week_totals:
        lines.append(f"{n}주차 : {format_won(amount)}")
    lines.append(f"▶ {month}월 누계 : {format_won(month_total)}")

    lines += [
        "",
        "④ 네이버포인트",
        f"이번주 적립 : {format_won(point_earned)}",
        f"이번주 사용 : {format_won(point_used)}",
        f"사용가능포인트 : {format_won(point_balance)}",
    ]
    return "\n".join(lines)


def build_report_text(period_label, start: date, end: date, rows_asc, category_totals: dict, total: int) -> str:
    """월간·직접 선택 보고 텍스트 (PRD 13장). rows_asc는 날짜 오래된 순으로 정렬된 지출 목록."""
    lines = [
        report_title(period_label),
        "",
        f"기간: {to_iso(start)} ~ {to_iso(end)}",
        "",
    ]
    for category, amount in order_category_totals(category_totals):
        lines.append(f"{category}: {format_won(amount)}")
    lines += ["", f"총 지출: {format_won(total)}", "", "상세 내역"]

    date_format = "%m/%d" if start.year == end.year else "%Y/%m/%d"
    if not rows_asc:
        lines.append("- 해당 기간 지출 없음")
    for row in rows_asc:
        day = from_iso(row["expense_date"]).strftime(date_format)
        lines.append(
            f"- {day} | {row['category']} | {format_won(row['amount'])} | "
            f"{dash_if_empty(row['place'])} | {dash_if_empty(row['memo'])}"
        )
    return "\n".join(lines)


BACKUP_TITLE = "주방지출 백업"
_BACKUP_RULE = "=" * 40
_BACKUP_SEPARATOR = "-" * 40


def point_line(row, fmt=format_point) -> str | None:
    """카드·백업용 네이버포인트 한 줄. 적립·사용이 모두 0이면 None. 카드는 P, 백업은 원(fmt=format_won)."""
    earned, used = int(row.get("point_earned") or 0), int(row.get("point_used") or 0)
    if not earned and not used:
        return None
    return f"네이버포인트: 적립 {fmt(earned)} / 사용 {fmt(used)}"


def build_backup_text(
    rows_desc, category_totals: dict, total: int, count: int, backup_at: datetime,
    point_earned: int = 0, point_used: int = 0,
) -> str:
    """TXT 백업 내용 (PRD 14장). rows_desc는 날짜 최신순으로 정렬된 전체 지출 목록."""
    lines = [
        _BACKUP_RULE,
        BACKUP_TITLE,
        _BACKUP_RULE,
        "",
        f"백업 일시: {backup_at.strftime(DATETIME_FORMAT)}",
        f"전체 지출 건수: {count:,}건",
        f"전체 지출 합계: {format_won(total)}",
        "",
        "[지출 내역]",
        "",
    ]
    if not rows_desc:
        lines += ["저장된 지출 내역이 없습니다.", "", _BACKUP_SEPARATOR, ""]
    for row in rows_desc:
        lines += [
            row["expense_date"],
            f"카테고리: {report_category(row['category'])}",
            f"금액: {format_won(row['amount'])}",
            f"사용처: {dash_if_empty(row['place'])}",
            f"메모: {dash_if_empty(row['memo'])}",
        ]
        points = point_line(row, format_won)
        if points:
            lines.append(points)
        lines += ["", _BACKUP_SEPARATOR, ""]
    lines += ["카테고리별 합계", ""]
    for category, amount in order_category_totals(category_totals):
        lines.append(f"{report_category(category)}: {format_won(amount)}")
    lines += [
        "",
        f"전체 지출 건수: {count:,}건",
        f"전체 합계: {format_won(total)}",
        "",
        "네이버포인트 합계",
        "",
        f"총 네이버포인트(적립): {format_won(point_earned)}",
        f"차감한 네이버포인트(사용): {format_won(point_used)}",
    ]
    return "\n".join(lines) + "\n"


def backup_filename(at: datetime) -> str:
    return f"expense_backup_{at.strftime('%Y%m%d_%H%M%S')}.txt"
