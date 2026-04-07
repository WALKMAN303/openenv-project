"""
server/environment.py — Core SQL Repair Environment logic.

FIX (Phase 2 compliance): All task scores are now clamped to the open
interval (0.01, 0.99) so they are strictly between 0 and 1, as required
by the OpenEnv evaluator.
"""

import sqlite3
import uuid
import re
from typing import Optional


# ── Score clamping ────────────────────────────────────────────────────────────
# The OpenEnv evaluator requires: 0.0 < score < 1.0  (strictly).
# Use this helper everywhere a score is returned.
def _clamp(score: float, lo: float = 0.01, hi: float = 0.99) -> float:
    """Clamp *score* to the open interval (lo, hi)."""
    return max(lo, min(hi, float(score)))


# ── Task definitions ──────────────────────────────────────────────────────────
TASKS = {
    "easy": {
        "task_id":          "easy",
        "difficulty":       "easy",
        "task_description": (
            "Fix the broken SQL query that retrieves employee names, "
            "departments, and salaries. The query contains misspelled keywords."
        ),
        "broken_query": (
            "SELCT name, department, salary FORM employees WERE salary > 50000"
        ),
        "expected_query": (
            "SELECT name, department, salary FROM employees WHERE salary > 50000"
        ),
        "expected_columns": {"name", "department", "salary"},
    },
    "medium": {
        "task_id":          "medium",
        "difficulty":       "medium",
        "task_description": (
            "Fix the broken SQL query that joins employees with departments "
            "to get names and locations. The JOIN columns are swapped."
        ),
        "broken_query": (
            "SELECT e.name, d.location "
            "FROM employees e "
            "JOIN departments d ON e.id = d.id"      # wrong: should be e.department = d.name (or similar)
        ),
        "expected_query": (
            "SELECT e.name, d.location "
            "FROM employees e "
            "JOIN departments d ON e.department = d.name"
        ),
        "expected_columns": {"name", "location"},
    },
    "hard": {
        "task_id":          "hard",
        "difficulty":       "hard",
        "task_description": (
            "Fix the broken SQL query that finds departments whose average "
            "salary exceeds 60000. The query incorrectly uses WHERE instead "
            "of HAVING for the aggregate filter."
        ),
        "broken_query": (
            "SELECT department, AVG(salary) AS avg_salary "
            "FROM employees "
            "WHERE AVG(salary) > 60000 "
            "GROUP BY department"
        ),
        "expected_query": (
            "SELECT department, AVG(salary) AS avg_salary "
            "FROM employees "
            "GROUP BY department "
            "HAVING AVG(salary) > 60000"
        ),
        "expected_columns": {"department", "avg_salary"},
    },
}

# ── In-memory DB seed ─────────────────────────────────────────────────────────
_SEED_SQL = """
CREATE TABLE employees (
    id         INTEGER PRIMARY KEY,
    name       TEXT,
    department TEXT,
    salary     REAL,
    hire_date  TEXT
);
CREATE TABLE departments (
    id       INTEGER PRIMARY KEY,
    name     TEXT,
    budget   REAL,
    location TEXT
);
CREATE TABLE projects (
    id            INTEGER PRIMARY KEY,
    name          TEXT,
    department_id INTEGER,
    budget        REAL,
    status        TEXT
);
CREATE TABLE employee_projects (
    employee_id  INTEGER,
    project_id   INTEGER,
    role         TEXT,
    hours_worked REAL
);

INSERT INTO departments VALUES
    (1, 'Engineering', 500000, 'San Francisco'),
    (2, 'Marketing',   200000, 'New York'),
    (3, 'HR',          100000, 'Chicago');

INSERT INTO employees VALUES
    (1, 'Alice',   'Engineering', 95000, '2019-03-01'),
    (2, 'Bob',     'Engineering', 80000, '2020-06-15'),
    (3, 'Carol',   'Marketing',   55000, '2018-01-10'),
    (4, 'Dave',    'Marketing',   48000, '2021-09-01'),
    (5, 'Eve',     'HR',          62000, '2017-07-20'),
    (6, 'Frank',   'HR',          58000, '2022-02-28');

INSERT INTO projects VALUES
    (1, 'Alpha', 1, 120000, 'active'),
    (2, 'Beta',  2,  60000, 'active'),
    (3, 'Gamma', 3,  30000, 'closed');

INSERT INTO employee_projects VALUES
    (1, 1, 'lead',   200),
    (2, 1, 'dev',    150),
    (3, 2, 'lead',   100),
    (4, 2, 'dev',     80),
    (5, 3, 'lead',    60),
    (6, 3, 'dev',     40);
"""


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SEED_SQL)
    return conn


# ── Grader ────────────────────────────────────────────────────────────────────

def _normalise_sql(sql: str) -> str:
    """Lower-case + collapse whitespace for rough comparison."""
    return re.sub(r"\s+", " ", sql.strip().lower())


def grade(task_id: str, submitted_sql: str) -> dict:
    """
    Grade *submitted_sql* against the expected result for *task_id*.

    Returns a dict with:
        score    float  — strictly in (0.01, 0.99)
        feedback str
        passed   bool
    """
    if task_id not in TASKS:
        return {"score": 0.01, "feedback": f"Unknown task_id: {task_id!r}", "passed": False}

    task      = TASKS[task_id]
    expected  = task["expected_query"]
    exp_cols  = task["expected_columns"]

    conn = _make_db()

    # ── Run expected query to get ground-truth rows ───────────────────────────
    try:
        exp_cursor = conn.execute(expected)
        exp_rows   = [dict(r) for r in exp_cursor.fetchall()]
        exp_cols_actual = set(exp_rows[0].keys()) if exp_rows else exp_cols
    except Exception as exc:
        conn.close()
        return {"score": 0.01, "feedback": f"Internal error running expected query: {exc}", "passed": False}

    # ── Run submitted query ───────────────────────────────────────────────────
    error_message = ""
    sub_rows: list[dict] = []
    try:
        sub_cursor = conn.execute(submitted_sql)
        sub_rows   = [dict(r) for r in sub_cursor.fetchall()]
        sub_cols   = set(sub_rows[0].keys()) if sub_rows else set()
    except Exception as exc:
        error_message = str(exc)
        conn.close()
        # Query didn't even run — give a small partial score for trying
        return {
            "score":   _clamp(0.05),
            "feedback": f"Query execution failed: {error_message}",
            "passed":  False,
            "error":   error_message,
        }
    finally:
        conn.close()

    # ── Score components ──────────────────────────────────────────────────────
    raw_score = 0.0

    # +0.30  query executes without error (already passed the try/except above)
    raw_score += 0.30

    # +0.20  correct columns
    if sub_cols and sub_cols == exp_cols_actual:
        raw_score += 0.20
        col_feedback = "✓ Correct columns."
    else:
        col_feedback = f"✗ Column mismatch. Got {sub_cols}, expected {exp_cols_actual}."

    # +0.10  correct row count
    if len(sub_rows) == len(exp_rows):
        raw_score += 0.10
        row_feedback = "✓ Correct row count."
    else:
        row_feedback = f"✗ Row count mismatch. Got {len(sub_rows)}, expected {len(exp_rows)}."

    # +0.40  correct row values (partial credit per matching row)
    if exp_rows:
        matched = sum(1 for r in sub_rows if r in exp_rows)
        value_score = 0.40 * (matched / len(exp_rows))
        raw_score  += value_score
        val_feedback = f"✓ {matched}/{len(exp_rows)} rows matched." if matched else "✗ No rows matched expected values."
    else:
        val_feedback = "No expected rows to compare."

    passed   = raw_score >= 0.99        # perfect or near-perfect
    feedback = f"{col_feedback} {row_feedback} {val_feedback}"

    # ── Clamp to open interval (0.01, 0.99) ──────────────────────────────────
    final_score = _clamp(raw_score)

    return {
        "score":    final_score,
        "feedback": feedback.strip(),
        "passed":   passed,
        "error":    error_message,
    }


# ── Episode management ────────────────────────────────────────────────────────

class SQLRepairEnvironment:
    """Stateful environment instance for one episode."""

    MAX_ATTEMPTS = 5
    HINT_AFTER   = 2           # show hint after this many failed attempts

    def __init__(self, task_id: str):
        if task_id not in TASKS:
            raise ValueError(f"Unknown task_id {task_id!r}. Choose from: {list(TASKS)}")
        self.task        = TASKS[task_id]
        self.episode_id  = str(uuid.uuid4())
        self.step_count  = 0
        self.done        = False
        self.last_score  = 0.0
        self.last_feedback = ""
        self.last_error  = ""

    # ── Public API ────────────────────────────────────────────────────────────

    def reset(self) -> dict:
        """Reset and return the initial observation."""
        self.step_count    = 0
        self.done          = False
        self.last_score    = 0.0
        self.last_feedback = ""
        self.last_error    = ""
        return self._observation(reward=None)

    def step(self, sql_query: str, explanation: str = "") -> dict:
        """Submit a fixed SQL query; returns StepResult-shaped dict."""
        if self.done:
            return {
                "observation": self._observation(reward=self.last_score),
                "reward":      _clamp(self.last_score),
                "done":        True,
            }

        self.step_count += 1
        result           = grade(self.task["task_id"], sql_query)

        self.last_score    = result["score"]
        self.last_feedback = result["feedback"]
        self.last_error    = result.get("error", "")

        # Episode ends on success or exhausted attempts
        if result["passed"] or self.step_count >= self.MAX_ATTEMPTS:
            self.done = True

        reward = _clamp(self.last_score)
        return {
            "observation": self._observation(reward=reward),
            "reward":      reward,
            "done":        self.done,
        }

    def state(self) -> dict:
        return {
            "episode_id":   self.episode_id,
            "step_count":   self.step_count,
            "task_id":      self.task["task_id"],
            "difficulty":   self.task["difficulty"],
            "max_attempts": self.MAX_ATTEMPTS,
            "last_score":   _clamp(self.last_score),
            "completed":    self.done,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _observation(self, reward) -> dict:
        hint = ""
        if self.step_count >= self.HINT_AFTER and not self.done:
            hint = (
                "Hint: Compare the broken query carefully against the "
                "task description and schema. Look for keyword typos, "
                "wrong JOIN columns, or misplaced WHERE/HAVING clauses."
            )

        return {
            "broken_query":     self.task["broken_query"],
            "db_schema":        _DB_SCHEMA_TEXT,
            "error_message":    self.last_error,
            "task_description": self.task["task_description"],
            "task_id":          self.task["task_id"],
            "difficulty":       self.task["difficulty"],
            "attempt_number":   self.step_count,
            "max_attempts":     self.MAX_ATTEMPTS,
            "feedback":         self.last_feedback,
            "hint":             hint,
            "reward":           _clamp(reward) if reward is not None else None,
            "done":             self.done,
        }


_DB_SCHEMA_TEXT = """
employees(id INTEGER, name TEXT, department TEXT, salary REAL, hire_date TEXT)
departments(id INTEGER, name TEXT, budget REAL, location TEXT)
projects(id INTEGER, name TEXT, department_id INTEGER, budget REAL, status TEXT)
employee_projects(employee_id INTEGER, project_id INTEGER, role TEXT, hours_worked REAL)
""".strip()
