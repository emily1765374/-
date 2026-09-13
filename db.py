"""SQLite 데이터 접근 모듈 (Streamlit에 의존하지 않음).

합계는 절대 저장하지 않고, 필요할 때마다 원본 데이터에서 SUM으로 계산한다.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "expenses.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_date TEXT    NOT NULL,
    amount       INTEGER NOT NULL CHECK (amount > 0),
    category     TEXT    NOT NULL,
    place        TEXT    NOT NULL DEFAULT '',
    memo         TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_expenses_expense_date ON expenses (expense_date)
"""

_ORDER_BY = {
    "desc": "expense_date DESC, id DESC",  # 내역 화면, 백업
    "asc": "expense_date ASC, id ASC",     # 보고 텍스트 상세 내역
}


@contextmanager
def _connect():
    """작업마다 연결을 열고, 성공 시 commit 후 항상 닫는다."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _build_where(start=None, end=None, category=None):
    """기간(YYYY-MM-DD, 양 끝 포함)과 카테고리 조건을 파라미터 바인딩 형태로 만든다."""
    clauses, params = [], []
    if start is not None:
        clauses.append("expense_date >= ?")
        params.append(start)
    if end is not None:
        clauses.append("expense_date <= ?")
        params.append(end)
    if category is not None:
        clauses.append("category = ?")
        params.append(category)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


# ---------------------------------------------------------------------------
# 초기화
# ---------------------------------------------------------------------------

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_INDEX_SQL)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def add_expense(expense_date, amount, category, place, memo, created_at):
    """지출을 추가하고 새 id를 반환한다."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO expenses (expense_date, amount, category, place, memo, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (expense_date, int(amount), category, place, memo, created_at),
        )
        return cur.lastrowid


def get_expenses(start=None, end=None, category=None, order="desc"):
    """조건에 맞는 지출 목록을 dict 리스트로 반환한다."""
    where, params = _build_where(start, end, category)
    sql = f"SELECT * FROM expenses{where} ORDER BY {_ORDER_BY[order]}"
    with _connect() as conn:
        return [dict(row) for row in conn.execute(sql, params)]


def get_expense(expense_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        return dict(row) if row else None


def update_expense(expense_id, expense_date, amount, category, place, memo):
    """수정 성공 여부를 반환한다. created_at은 변경하지 않는다."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE expenses SET expense_date = ?, amount = ?, category = ?, place = ?, memo = ? "
            "WHERE id = ?",
            (expense_date, int(amount), category, place, memo, expense_id),
        )
        return cur.rowcount > 0


def delete_expense(expense_id):
    """삭제 성공 여부를 반환한다."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# 합계 (항상 원본에서 계산)
# ---------------------------------------------------------------------------

def get_total(start=None, end=None, category=None):
    """(합계 금액, 건수)를 반환한다. 기간을 생략하면 전체 누적이다. 데이터가 없으면 (0, 0)."""
    where, params = _build_where(start, end, category)
    sql = f"SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS cnt FROM expenses{where}"
    with _connect() as conn:
        row = conn.execute(sql, params).fetchone()
        return int(row["total"]), int(row["cnt"])


def get_category_totals(start=None, end=None):
    """기간 내 {카테고리: 합계 금액} dict를 반환한다. 데이터가 없는 카테고리는 포함되지 않는다."""
    where, params = _build_where(start, end)
    sql = (
        f"SELECT category, COALESCE(SUM(amount), 0) AS total FROM expenses{where} "
        "GROUP BY category"
    )
    with _connect() as conn:
        return {row["category"]: int(row["total"]) for row in conn.execute(sql, params)}
