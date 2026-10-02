# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

주방지출관리 — a single-user, mobile-first (iPhone portrait first, then iPad, then PC) Streamlit app for logging card expenses, with SQLite storage. The user communicates in Korean; UI text, docs, and reports are Korean.

**`prd.md` is the authoritative spec.** Check it before implementing anything; if an implementation must deviate, ask the user first instead of silently changing behavior. Exact text formats for the manager report (PRD §13) and TXT backup (PRD §14) must match the PRD character-for-character.

### Staged workflow

Development proceeds in user-approved stages. After finishing a stage, report and **stop until the user explicitly says to continue** (e.g. "2단계 진행"):

1. Skeleton: db/utils, summary header, 4 tabs, only the 지출 입력 tab working (done)
2. Features: 지출 내역 (filters, card list, inline edit, delete confirm, 더 보기, table toggle), 통계·합계, 보고 텍스트, TXT 백업 (done)
3. Mobile UI polish: minimal CSS only, no logic changes (done)
4. Review against PRD + bug hunt: report first, no code changes until approved (review done; all findings fixed after the user said "전체 수정")

## Commands

```powershell
# Run (normal use): double-click run.bat, or
.\venv\Scripts\python.exe -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501

# Install deps into the project venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# Health check of a running server
curl.exe -s http://localhost:8501/_stcore/health
```

Streamlit's file watcher can reload `app.py` but keep a stale `utils`/`db` module in memory, so after changing a function signature across files a running server may raise `TypeError` until it is restarted (close the window and rerun `run.bat`).

There is no committed test suite or linter. Verify with throwaway scripts kept **outside** the project folder (use the scratchpad), never touching the real `data/expenses.db`:
- Pure logic: import `utils` / `db` directly; point `db.DB_PATH` at a temp file before calling `db.init_db()`.
- UI behavior: `streamlit.testing.v1.AppTest.from_file("app.py")`. Import `db` and patch `db.DB_PATH` first — AppTest runs in-process, so `app.py`'s `import db` picks up the patched module. Widgets are addressable by key, e.g. `at.number_input(key="add_amount")`, `at.button_group[0]` for the segmented control.

## Architecture

Three-layer split, strictly enforced:
- `app.py` — Streamlit UI only. No SQL.
- `db.py` — SQLite access only. No Streamlit import. Opens/closes a connection per operation via `_connect()`; all queries use parameter binding. `DB_PATH` is resolved relative to the module file, not the CWD.
- `seed_data.py` — data only: the backup rows restored once by `db.init_db()`.
- `utils.py` — pure functions, no DB/Streamlit: KST date helpers, week (Sun–Sat) / month (1st–last day) ranges, `format_won`, `validate_expense`. `CATEGORIES` is the single source of the category list.

Invariants that span files:
- **Totals are never stored** — not in DB columns/tables, `st.session_state`, or `st.cache_*`. Every rerun recomputes from raw rows via `db.get_total` / `db.get_category_totals` (SQL `SUM`). `session_state` holds UI state only.
- **Amounts are `int` end to end** (validation rejects non-integer values, DB has `CHECK (amount >= 0)`). Comma formatting happens only at display/text-output time.
- **Amount is optional**: a row may have `amount = 0` when only 네이버포인트 적립/사용 was entered. `utils.validate_expense` rejects an entry only when amount *and* both point fields are empty (`utils.EMPTY_INPUT_ERROR`), and the `point_used <= amount` rule is skipped when amount is 0. A 0원 row renders like any other row in the 지출 내역 cards/table and the TXT backup and adds 0 to the totals, but `utils.spending_rows` filters it out of the weekly report's ① 일별 지출현황 because it is not real spending (the monthly/custom report has no per-row list) — point totals (both reports' 네이버포인트 sections, 통계·합계) still include it; `app.saved_label` shows the points instead of `0원` in the add/edit toast.
- Dates are stored as `YYYY-MM-DD` TEXT so string comparison gives correct range filtering/sorting. "Today" is always Asia/Seoul (`utils.today_kst()`); a fixed +9 offset is the fallback if `tzdata` is missing.
- Empty `place` / `memo` are stored as `''` (not NULL); reports/backup render them as `-`.
- Ordering: list/backup use `expense_date DESC, id DESC`; the report's detail lines use `order="asc"`.
- Manager report has two formats (PRD §13): 이번 주/지난 주 → `utils.build_weekly_report_text` (`[주방비 주간 지출보고]`, ①–④ sections); 이번 달/지난 달/직접 선택 → `utils.build_report_text` (all titled `[월간 지출 내역]`: 기간, 4 category totals, `▶ 총 지출`, then a 네이버포인트 block — no 상세 내역; categories keep the space, `주방 소모품`). Everywhere in the app (summary header, 지출 내역, 통계·합계, 보고), 이번 주/지난 주 are **split at month end** (`utils.report_week_range` / `last_report_week_range`, used by `resolve_period`): 9/27~10/3 becomes `9월 5째주 (9.27~9.30)` (month close) and `10월 1째주 (10.1~10.3)`; 지난 주 is the segment right before this one. `utils.week_of_month` takes the segment start (its month, week 1 = the week containing the 1st); the month 누계 weeks are clipped to that month on both ends (`utils.month_week_ranges`), and 누계/사용가능포인트 run up to the segment's last day. Weekly report text **and the TXT backup** write categories without spaces (`REPORT_CATEGORY_LABELS`: `주방 소모품` → `주방소모품`); DB/UI names are unchanged. Points are shown in `원` in both manager reports and the TXT backup, `P` in the UI (cards, 통계·합계). Every label/value line in both reports and the TXT backup uses ` : ` (one space on each side of the colon, user request), e.g. `기간 : …`, `▶ 총 지출 : …`, `카테고리 : …`, `네이버포인트 : 적립 …` (backup passes `sep=" : "` to `utils.point_line`; the UI card keeps `네이버포인트: `). The time inside `백업 일시 : 2026-10-02 20:47:29` is not spaced.
- Schema is one `expenses` table (`id, expense_date, amount, category, place, memo, created_at, point_earned, point_used`). No `updated_at`; `created_at` is never modified on update.
- **Existing data must never be lost.** Schema/category changes go through `db.init_db()` as idempotent in-place migrations: `ALTER TABLE ADD COLUMN` (`_ADDED_COLUMNS`) and `UPDATE ... SET category` (`_CATEGORY_RENAMES`, e.g. `주방 식재료` → `평일식재료`). Never drop/recreate the table, with one deliberate exception: `db._relax_amount_check()` rebuilds the table (rename → new table → copy every row incl. `id`/`created_at` → drop old → recreate index, one `executescript` transaction on its own connection) to turn the old `CHECK (amount > 0)` into `CHECK (amount >= 0)`. It runs after the `ADD COLUMN` migrations, is a no-op once the schema is current, and `_needs_migration()` reports it so the pre-migration file copy happens. When a migration is pending, `init_db()` first copies the DB to `data/expenses_before_migration_*.db`. `init_db()` also restores the 23 rows (2026-09-07 ~ 2026-10-02, incl. the 0원 row with 4,523 points) from the 2026-10-02 TXT backup `expense_backup_20261002_204729.txt` (`seed_data.RESTORE_ROWS` as `(date, amount, category, place, memo, point_earned, point_used)`, categories already mapped to app names) once per DB: guarded by `PRAGMA user_version` (`_RESTORE_VERSION`, now 2; it was 1 for the earlier 17-row 2026-09-19 list, so DBs at 1 get the new rows once — bump it whenever the list changes), skipping rows whose date+amount+place already exist, after copying the DB to `data/expenses_before_restore_*.db`. Because of the user_version guard, rows the user deletes later are not re-inserted; don't replace it with a plain "insert if missing" check.
- Categories (in display order): `평일식재료`, `안식일식재료`, `주방 소모품`, `기타`.
- 네이버포인트: per-expense optional `point_earned` (적립) / `point_used` (사용·차감), int ≥ 0, blank → 0, `point_used ≤ amount` (not enforced when amount is 0). `amount` stays the full payment total, so spending totals ignore points. Point totals (`db.get_point_totals`) appear in 통계·합계, at the end of the TXT backup, and in both manager reports (weekly ④ and the monthly/custom 네이버포인트 block): 적립 → 사용 → 사용가능포인트 = all-time 적립 − 사용 up to the period's last day. The monthly/custom block labels them `이번달 적립` / `이번달 사용` (user request; values are the selected period, also for 직접 선택). Both the weekly ④ and the monthly/custom block prefix `▶ ` to 사용가능포인트. In 통계·합계 the points box (`render_point_summary`) is always **all-time** (총 적립 / 총 차감 / 잔액 = 적립 − 차감, may be negative), pinned at the bottom of the tab, and shown even when the period picker has an error. Don't tie it to the selected period.

### Streamlit patterns used (1.63)

- Form submission logic lives in the `on_click` **callback** (`handle_add_expense`). Setting widget values via `st.session_state[key] = ...` is only legal in callbacks, not after the widget has rendered in the script body.
- **Add form structure is deliberate — keep every add input and the ±1,000 buttons inside one `st.form(enter_to_submit=False)`**; the ± buttons are `form_submit_button`s. Streamlit's native number_input stepper is disabled while the field is empty (so "empty + → 1,000" needs custom buttons), and a regular `st.button` can't live in a form. An earlier layout with the amount input outside the form caused a real-browser race: typing an amount and tapping 등록 immediately saved the row but left the inputs filled, so a second tap saved a duplicate. AppTest did not reproduce it.
- Clearing after a successful add bumps `session_state["add_version"]`; amount/place/memo use versioned keys via `add_key(name)` so fresh widgets replace the old ones. Category keeps a fixed key. The date uses a per-day key (`add_date_key(today)`), recorded in `session_state["add_date_key"]` for the callback, so a page left open past midnight resets to today instead of silently saving yesterday.
- Don't add a live "입력 금액" preview inside a form: form values aren't sent until submit, so it shows a stale amount while the user types (it was removed for this reason).
- The edit form mirrors the add form: ±1,000 `form_submit_button`s calling `step_amount(key, delta)` and `enter_to_submit=False`. Its amount `number_input` uses `value=None` and is pre-filled via `session_state` only when the key is absent. Passing `value=row["amount"]` would trigger Streamlit's "default value + Session State API" warning when ± writes the key.
- `st.toast` for flash messages is emitted at the **end** of the script so conditional elements don't shift the layout.
- TXT backup bytes, the file name, and the "백업 일시" line are all built from one `backup_at` captured when the 보고·백업 tab renders (render-time snapshot, not click-time).
- The report copy button (`render_report_copy_button`) is custom HTML+JS via `st.html(..., unsafe_allow_javascript=True)`. iPhone reaches the app over plain LAN HTTP (a non-secure context), where `navigator.clipboard` and `st.code`'s built-in copy icon don't work.
  - On tap it fills a temporary readonly textarea, selects it (`select()` + `setSelectionRange`, both required on iOS), and calls `document.execCommand('copy')` synchronously inside the user gesture.
  - Only if that fails and `window.isSecureContext` is true does it fall back to `navigator.clipboard.writeText`.
  - The report text is read from an HTML-escaped hidden textarea and never interpolated into the script, because it contains user-entered place/memo.
  - The click listener is installed once on `document` (`window.__reportCopyInstalled`) because `st.html` re-renders on every rerun.
  - The success/failure text goes into `.report-copy-msg`. Don't change the report text or format when touching this.
- Verify copy behavior over the LAN IP, not localhost (localhost is a secure context and hides the iPhone problem). Use Playwright WebKit with iPhone/iPad device descriptors (`playwright install webkit` in the scratch venv): click the button, paste into an injected textarea with `ControlOrMeta+V`, and compare with the report `text_area` value.
- Custom HTML (summary grid, expense cards, stats rows) goes through `st.html` with user text escaped via `html.escape` (`h()`); `md_escape` is only for markdown contexts like `st.warning`. All CSS lives in `_CSS` / `inject_css()`.
- 지출 내역 defaults to the **table** view (user request, deliberately reversing the original card-first PRD). The bottom toggle `카드로 보기 (수정·삭제)` (`key="list_cards"`, default off) or the `✏️ 수정·삭제` button under the table (`show_cards` callback) switches to the card list, where edit/delete live.
  - Selecting a table row (`st.dataframe(on_select=edit_selected_row, selection_mode="single-row")`) switches to cards and opens that row's edit form directly. The callback maps the row index to an id via `session_state["list_table_ids"]` (written right before the dataframe renders, same order), raises `list_limit` so the row is inside the shown cards, and sets `scroll_to_edit`.
  - The dataframe key is versioned (`table_key()` → `list_table_{list_table_version}`) and bumped in the callback, so the selection clears and the same row can be picked again after returning to the table.
  - `render_scroll_to_edit` scrolls once via `st.html` JS to `.st-key-edit_date_{id}`; `st.form` gets no `st-key-*` class in 1.63, so don't target the form.
- Mobile layout: `st.columns(2, wrap=False)` keeps button pairs side by side at 375px; period/category filters use `st.pills` (wraps) instead of `st.segmented_control` (does not wrap). Theme color and minimal toolbar are set in `.streamlit/config.toml`. The app is intentionally **light-theme only** (user decision); don't add dark-theme config.
- `streamlit` is pinned to `1.63.0` in `requirements.txt` because the CSS hooks (`data-testid`, `st-key-*` classes) and the form behavior were verified on that version. Re-verify in a real browser before bumping it.
- UI verification needs a real browser for interaction timing bugs. Playwright works with the installed Chrome (`chromium.launch(channel="chrome")`); install it in a scratch venv, not the project venv, and run the app from a scratch copy so the real DB is untouched.
- To avoid "default value + Session State API" warnings, don't pre-seed session_state for widgets that pass a non-None `value`/`default`; let the widget own that state.
- Use `width="stretch"` rather than the deprecated `use_container_width`. The category picker is `st.segmented_control(..., required=True)`; CSS (`st-key-add_category` / `st-key-edit_category_*`) lays its 4 options out in **one row** (user request) as a 4-column grid, shrinking font/padding so they fit at 375px.
- N포인트 적립/사용 inputs (`render_point_inputs`, shared by add/edit forms): placeholder `숫자 입력`, native steppers hidden (disabled while empty), and a row of four ±1 `form_submit_button`s (`step_point`: empty −1 does nothing, empty +1 → 1, floor 0) under the two inputs. The row is wrapped in `st.container(key="point_btns_...")` whose CSS sets `stColumn { min-width: 0 }`: Streamlit gives each `wrap=False` column a 128px min-width, which made 4 columns overflow at 375px (nesting 2 columns inside each half had the same problem).
- Edit-form point inputs follow the amount pattern (`value=None`, pre-filled via session_state when the key is absent). A non-None `value` makes a number_input impossible to clear.

## run.bat gotchas

- Must be saved with **CRLF** line endings (UTF-8, no BOM). With LF-only endings, cmd misparses lines containing Korean text and the script breaks. The Edit/Write tools produce LF, so re-normalize to CRLF after editing it.
- `venv\.installed` is a copy of the `requirements.txt` that last installed successfully. run.bat reinstalls when the two differ (`fc /b`). Deleting `venv` forces a full reinstall.
- Put user-facing messages under `goto` labels, not inside `( ... )` blocks: a `)` in an `echo` inside a block ends the block early.
- Startup order: an already-listening port → "이미 실행 중" message and browser open. Otherwise, a missing venv → check that `python` actually runs (the Microsoft Store alias passes `where` but fails to run) → create venv → pip install.
- The LAN IP lookup inside `for /f` must call `venv\Scripts\python.exe` **unquoted**; a quoted path breaks the command.
- Launches with `--server.headless true` (skips Streamlit's first-run email prompt), so the browser is opened by a delayed PowerShell `Start-Process`.

## Deployment constraints

Same-Wi-Fi LAN use only (bind `0.0.0.0:8501`). No auth, so no external exposure or cloud deployment in the MVP. The clipboard API doesn't work over plain LAN HTTP on iOS, so copying uses the custom copy-button pattern above. The report `text_area` stays as a long-press fallback.
