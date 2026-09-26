"""SQLite 데이터 접근 모듈 (Streamlit에 의존하지 않음).

합계는 절대 저장하지 않고, 필요할 때마다 원본 데이터에서 SUM으로 계산한다.
"""

import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from seed_data import RESTORE_ROWS

DB_PATH = Path(__file__).resolve().parent / "data" / "expenses.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_date TEXT    NOT NULL,
    amount       INTEGER NOT NULL CHECK (amount >= 0),
    category     TEXT    NOT NULL,
    place        TEXT    NOT NULL DEFAULT '',
    memo         TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL,
    point_earned INTEGER NOT NULL DEFAULT 0 CHECK (point_earned >= 0),
    point_used   INTEGER NOT NULL DEFAULT 0 CHECK (point_used >= 0)
)
"""

# 예전 DB에 없던 컬럼: 기존 행은 기본값 0으로 채워지고 다른 값은 그대로 남는다.
_ADDED_COLUMNS = {
    "point_earned": "INTEGER NOT NULL DEFAULT 0 CHECK (point_earned >= 0)",  # 네이버포인트 적립
    "point_used": "INTEGER NOT NULL DEFAULT 0 CHECK (point_used >= 0)",      # 네이버포인트 사용(차감)
}

# 이름이 바뀐 카테고리 {예전 이름: 새 이름}. 카테고리 값만 바꾸고 금액·날짜·메모 등은 건드리지 않는다.
_CATEGORY_RENAMES = {
    "주방 식재료": "평일식재료",
}

# PRAGMA user_version: 이 값보다 작으면 백업 17건 복원(seed_data.RESTORE_ROWS)이 아직 안 된 DB다.
_RESTORE_VERSION = 1

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_expenses_expense_date ON expenses (expense_date)
"""

# 예전 DB의 금액 제약. 포인트만 등록하는 0원 건을 허용하려면 amount >= 0으로 바꿔야 한다.
_OLD_AMOUNT_CHECK = "CHECK (amount > 0)"

_COLUMNS = (
    "id, expense_date, amount, category, place, memo, created_at, point_earned, point_used"
)

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

def _needs_migration():
    """기존 DB 파일에 컬럼 추가나 카테고리 이름 변경이 필요한지 확인한다. (읽기만 함)"""
    if not DB_PATH.exists():
        return False
    conn = sqlite3.connect(DB_PATH)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(expenses)")}
        if not columns:  # 테이블이 아직 없음 (빈 파일)
            return False
        if any(name not in columns for name in _ADDED_COLUMNS):
            return True
        if _has_old_amount_check(conn):
            return True
        placeholders = ", ".join("?" for _ in _CATEGORY_RENAMES)
        row = conn.execute(
            f"SELECT COUNT(*) FROM expenses WHERE category IN ({placeholders})",
            list(_CATEGORY_RENAMES),
        ).fetchone()
        return row[0] > 0
    finally:
        conn.close()


def _needs_restore():
    """백업 복원을 아직 하지 않은 기존 DB 파일인지 확인한다. (읽기만 함)"""
    if not DB_PATH.exists():
        return False
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0] < _RESTORE_VERSION
    finally:
        conn.close()


def _has_old_amount_check(conn) -> bool:
    """테이블에 예전 CHECK (amount > 0) 제약이 남아 있는지 확인한다. (읽기만 함)"""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'expenses'"
    ).fetchone()
    return bool(row) and _OLD_AMOUNT_CHECK in row[0]


def _relax_amount_check():
    """금액 제약을 CHECK (amount > 0) -> CHECK (amount >= 0)으로 바꾼다. 필요 없으면 아무것도 하지 않는다.

    SQLite는 제약만 따로 고칠 수 없어, 공식 문서의 테이블 재구성 절차(이름 변경 -> 새 테이블 ->
    전체 행 복사 -> 옛 테이블 삭제)를 한 트랜잭션 안에서 수행한다. id·created_at을 포함한 모든 값을
    그대로 옮기므로 데이터는 사라지지 않고, init_db()가 이 작업 전에 DB 파일을 복사해 둔다.
    포인트 컬럼 추가(_ADDED_COLUMNS)가 끝난 뒤에 호출해야 한다.
    """
    if not DB_PATH.exists():
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        if not _has_old_amount_check(conn):
            return
        conn.executescript(
            "BEGIN;\n"
            "ALTER TABLE expenses RENAME TO expenses_old;\n"
            f"{_CREATE_TABLE_SQL};\n"
            f"INSERT INTO expenses ({_COLUMNS}) SELECT {_COLUMNS} FROM expenses_old;\n"
            "DROP TABLE expenses_old;\n"
            f"{_CREATE_INDEX_SQL};\n"
            "COMMIT;"
        )
    finally:
        conn.close()


def _backup_db_file(prefix="expenses_before_migration"):
    """마이그레이션·복원 전에 DB 파일을 같은 폴더에 복사해 둔다."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(DB_PATH, DB_PATH.with_name(f"{prefix}_{stamp}.db"))


def _restore_seed_rows(conn):
    """백업 17건을 DB마다 한 번만 넣는다. 같은 날짜·금액·사용처 행이 이미 있으면 그 건은 건너뛴다.

    한 번 복원한 뒤에는 user_version을 올려 두므로, 사용자가 나중에 지운 건이 다시 생기지 않는다.
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] >= _RESTORE_VERSION:
        return
    created_at = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")
    for expense_date, amount, category, place, memo in RESTORE_ROWS:
        exists = conn.execute(
            "SELECT 1 FROM expenses WHERE expense_date = ? AND amount = ? AND place = ?",
            (expense_date, amount, place),
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO expenses (expense_date, amount, category, place, memo, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (expense_date, amount, category, place, memo, created_at),
            )
    conn.execute(f"PRAGMA user_version = {_RESTORE_VERSION}")


def init_db():
    """테이블을 만들고, 예전 DB는 데이터를 지우지 않고 새 구조로 맞춘다. 여러 번 실행해도 안전하다."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _needs_migration():
        _backup_db_file()
    if _needs_restore():
        _backup_db_file("expenses_before_restore")
    with _connect() as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_INDEX_SQL)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(expenses)")}
        for name, definition in _ADDED_COLUMNS.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE expenses ADD COLUMN {name} {definition}")
        for old, new in _CATEGORY_RENAMES.items():
            conn.execute("UPDATE expenses SET category = ? WHERE category = ?", (new, old))
    # 포인트 컬럼이 갖춰진 뒤에 금액 제약을 완화한다. (별도 연결에서 한 트랜잭션으로 처리)
    _relax_amount_check()
    with _connect() as conn:
        _restore_seed_rows(conn)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def add_expense(expense_date, amount, category, place, memo, created_at, point_earned=0, point_used=0):
    """지출을 추가하고 새 id를 반환한다."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO expenses "
            "(expense_date, amount, category, place, memo, created_at, point_earned, point_used) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (expense_date, int(amount), category, place, memo, created_at, int(point_earned), int(point_used)),
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


def update_expense(expense_id, expense_date, amount, category, place, memo, point_earned=0, point_used=0):
    """수정 성공 여부를 반환한다. created_at은 변경하지 않는다."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE expenses SET expense_date = ?, amount = ?, category = ?, place = ?, memo = ?, "
            "point_earned = ?, point_used = ? WHERE id = ?",
            (expense_date, int(amount), category, place, memo, int(point_earned), int(point_used), expense_id),
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


def get_point_totals(start=None, end=None):
    """기간 내 네이버포인트 (적립 합계, 사용 합계)를 반환한다. 데이터가 없으면 (0, 0)."""
    where, params = _build_where(start, end)
    sql = (
        "SELECT COALESCE(SUM(point_earned), 0) AS earned, COALESCE(SUM(point_used), 0) AS used "
        f"FROM expenses{where}"
    )
    with _connect() as conn:
        row = conn.execute(sql, params).fetchone()
        return int(row["earned"]), int(row["used"])
