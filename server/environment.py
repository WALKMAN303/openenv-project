"""
server/environment.py - SQL Repair Environment v3

20 tasks across 3 difficulty levels:
  Easy   (7): Syntax typos, keyword errors
  Medium (7): JOIN errors, wrong clauses, subquery bugs
  Hard   (6): Aggregation, window functions, CTEs, complex multi-table

Features:
  - Anti-hack reward shaping (penalizes trivial/repeated queries)
  - Rich partial-credit grader (4 components + bonuses)
  - Hint system (reveals after 2 failed attempts)
  - Episode-level deduplication (penalizes submitting same query twice)
  - Extended schema with 6 tables for richer task variety
"""

import sqlite3
import uuid
import random
import os
import sys
import hashlib
from typing import Optional, Dict, List, Tuple, Any, Set

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from openenv.core.env_server import Environment
from models import SQLAction, SQLObservation, SQLState


# ── Database Schema ───────────────────────────────────────────────────────────

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    department  TEXT    NOT NULL,
    salary      REAL    NOT NULL,
    hire_date   TEXT    NOT NULL,
    manager_id  INTEGER,
    status      TEXT    DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS departments (
    id       INTEGER PRIMARY KEY,
    name     TEXT  NOT NULL,
    budget   REAL  NOT NULL,
    location TEXT  NOT NULL,
    head_id  INTEGER
);
CREATE TABLE IF NOT EXISTS projects (
    id            INTEGER PRIMARY KEY,
    name          TEXT  NOT NULL,
    department_id INTEGER NOT NULL,
    budget        REAL  NOT NULL,
    status        TEXT  NOT NULL,
    start_date    TEXT  NOT NULL,
    end_date      TEXT,
    priority      INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS employee_projects (
    employee_id  INTEGER NOT NULL,
    project_id   INTEGER NOT NULL,
    role         TEXT,
    hours_worked REAL DEFAULT 0,
    start_date   TEXT,
    PRIMARY KEY (employee_id, project_id)
);
CREATE TABLE IF NOT EXISTS sales (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL,
    amount      REAL    NOT NULL,
    sale_date   TEXT    NOT NULL,
    product     TEXT    NOT NULL,
    region      TEXT    NOT NULL,
    quarter     INTEGER
);
CREATE TABLE IF NOT EXISTS products (
    id       INTEGER PRIMARY KEY,
    name     TEXT  NOT NULL,
    category TEXT  NOT NULL,
    price    REAL  NOT NULL,
    stock    INTEGER DEFAULT 0,
    supplier TEXT
);
CREATE TABLE IF NOT EXISTS performance_reviews (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL,
    year        INTEGER NOT NULL,
    rating      REAL    NOT NULL,
    reviewer_id INTEGER,
    notes       TEXT
);
"""

DB_SEED = """
INSERT INTO departments VALUES (1,'Engineering',500000,'San Francisco',1);
INSERT INTO departments VALUES (2,'Marketing',200000,'New York',3);
INSERT INTO departments VALUES (3,'Finance',300000,'Chicago',4);
INSERT INTO departments VALUES (4,'Sales',400000,'Boston',9);
INSERT INTO departments VALUES (5,'HR',150000,'Austin',NULL);

INSERT INTO employees VALUES (1,'Alice Johnson','Engineering',95000,'2020-01-15',NULL,'active');
INSERT INTO employees VALUES (2,'Bob Smith','Engineering',85000,'2019-03-20',1,'active');
INSERT INTO employees VALUES (3,'Carol White','Marketing',72000,'2021-06-01',NULL,'active');
INSERT INTO employees VALUES (4,'David Brown','Finance',88000,'2018-11-10',NULL,'active');
INSERT INTO employees VALUES (5,'Eve Davis','Engineering',105000,'2017-07-22',1,'active');
INSERT INTO employees VALUES (6,'Frank Miller','Marketing',65000,'2022-02-14',3,'active');
INSERT INTO employees VALUES (7,'Grace Wilson','Finance',92000,'2019-09-30',4,'active');
INSERT INTO employees VALUES (8,'Henry Moore','Engineering',78000,'2020-12-05',1,'active');
INSERT INTO employees VALUES (9,'Iris Taylor','Sales',70000,'2021-03-10',NULL,'active');
INSERT INTO employees VALUES (10,'Jack Lee','Sales',68000,'2022-05-20',9,'active');
INSERT INTO employees VALUES (11,'Karen Chen','HR',60000,'2023-01-10',NULL,'active');
INSERT INTO employees VALUES (12,'Leo Garcia','Engineering',91000,'2018-06-15',1,'inactive');

INSERT INTO projects VALUES (1,'AI Platform',1,150000,'active','2023-01-01',NULL,3);
INSERT INTO projects VALUES (2,'Brand Refresh',2,80000,'completed','2022-06-01','2023-01-01',2);
INSERT INTO projects VALUES (3,'Budget System',3,120000,'active','2023-03-01',NULL,2);
INSERT INTO projects VALUES (4,'API Gateway',1,90000,'active','2023-02-01',NULL,3);
INSERT INTO projects VALUES (5,'CRM System',4,200000,'active','2023-04-01',NULL,1);
INSERT INTO projects VALUES (6,'HR Portal',5,80000,'active','2023-05-01',NULL,1);

INSERT INTO employee_projects VALUES (1,1,'Lead',320.0,'2023-01-01');
INSERT INTO employee_projects VALUES (2,1,'Developer',280.0,'2023-01-01');
INSERT INTO employee_projects VALUES (5,4,'Lead',200.0,'2023-02-01');
INSERT INTO employee_projects VALUES (8,4,'Developer',150.0,'2023-02-01');
INSERT INTO employee_projects VALUES (3,2,'Lead',400.0,'2022-06-01');
INSERT INTO employee_projects VALUES (6,2,'Designer',300.0,'2022-06-01');
INSERT INTO employee_projects VALUES (4,3,'Lead',250.0,'2023-03-01');
INSERT INTO employee_projects VALUES (7,3,'Analyst',180.0,'2023-03-01');
INSERT INTO employee_projects VALUES (9,5,'Lead',350.0,'2023-04-01');
INSERT INTO employee_projects VALUES (10,5,'Member',200.0,'2023-04-01');
INSERT INTO employee_projects VALUES (11,6,'Lead',300.0,'2023-05-01');

INSERT INTO sales VALUES (1,9,5000,'2023-01-15','Software','North',1);
INSERT INTO sales VALUES (2,10,3000,'2023-01-20','Hardware','South',1);
INSERT INTO sales VALUES (3,9,7500,'2023-02-10','Software','North',1);
INSERT INTO sales VALUES (4,10,4500,'2023-02-15','Software','East',1);
INSERT INTO sales VALUES (5,9,6000,'2023-03-05','Hardware','West',1);
INSERT INTO sales VALUES (6,10,8000,'2023-03-20','Software','North',1);
INSERT INTO sales VALUES (7,9,2500,'2023-04-10','Hardware','South',2);
INSERT INTO sales VALUES (8,10,9000,'2023-04-25','Software','East',2);
INSERT INTO sales VALUES (9,9,11000,'2023-07-15','Software','North',3);
INSERT INTO sales VALUES (10,10,7500,'2023-08-20','Hardware','West',3);

INSERT INTO products VALUES (1,'Laptop Pro','Hardware',1299.99,50,'TechCorp');
INSERT INTO products VALUES (2,'Cloud Suite','Software',499.99,999,'SoftCo');
INSERT INTO products VALUES (3,'Desk Monitor','Hardware',399.99,120,'TechCorp');
INSERT INTO products VALUES (4,'DevTools','Software',199.99,999,'SoftCo');
INSERT INTO products VALUES (5,'Keyboard','Hardware',89.99,300,'TechCorp');

INSERT INTO performance_reviews VALUES (1,1,2022,4.5,5,'Excellent work');
INSERT INTO performance_reviews VALUES (2,2,2022,3.8,1,'Good performer');
INSERT INTO performance_reviews VALUES (3,5,2022,4.9,1,'Outstanding');
INSERT INTO performance_reviews VALUES (4,8,2022,3.5,1,'Meets expectations');
INSERT INTO performance_reviews VALUES (5,1,2023,4.7,5,'Continues to excel');
INSERT INTO performance_reviews VALUES (6,2,2023,4.0,1,'Improved significantly');
INSERT INTO performance_reviews VALUES (7,9,2022,4.2,4,'Top salesperson');
INSERT INTO performance_reviews VALUES (8,10,2022,3.9,9,'Good effort');
"""

SCHEMA_DESCRIPTION = """Tables available:

employees(id, name, department, salary, hire_date, manager_id, status)
departments(id, name, budget, location, head_id)
projects(id, name, department_id, budget, status, start_date, end_date, priority)
employee_projects(employee_id, project_id, role, hours_worked, start_date)
sales(id, employee_id, amount, sale_date, product, region, quarter)
products(id, name, category, price, stock, supplier)
performance_reviews(id, employee_id, year, rating, reviewer_id, notes)

Key relationships:
  employees.department        → matches departments.name
  employees.manager_id        → references employees.id (self-join)
  employees.status            → 'active' or 'inactive'
  departments.head_id         → references employees.id
  projects.department_id      → references departments.id
  employee_projects.employee_id → references employees.id
  employee_projects.project_id  → references projects.id
  sales.employee_id           → references employees.id
  performance_reviews.employee_id → references employees.id
  performance_reviews.reviewer_id → references employees.id
"""


# ── 20 Tasks ──────────────────────────────────────────────────────────────────

TASKS: Dict[str, Dict[str, Any]] = {

    # ── EASY 1-7: Syntax/keyword typos ───────────────────────────────────────

    "easy_1": {
        "id": "easy_1", "difficulty": "easy",
        "description": "Fix syntax errors. Return name, department, salary of active Engineering employees earning over $80,000, ordered by salary DESC.",
        "broken_query": "SELCT name, department, salary FORM employees WERE department = 'Engineering' AND salary > 80000 AND status = 'active' ORDR BY salary DESC",
        "expected_query": "SELECT name, department, salary FROM employees WHERE department = 'Engineering' AND salary > 80000 AND status = 'active' ORDER BY salary DESC",
        "hint": "Fix: SELCT→SELECT, FORM→FROM, WERE→WHERE, ORDR BY→ORDER BY",
    },
    "easy_2": {
        "id": "easy_2", "difficulty": "easy",
        "description": "Fix syntax error. Return department names and budgets over 250000, ordered by budget DESC.",
        "broken_query": "SELECT name, budget FROM departments WHERE budget > 250000 ORER BY budget DESC",
        "expected_query": "SELECT name, budget FROM departments WHERE budget > 250000 ORDER BY budget DESC",
        "hint": "ORER BY should be ORDER BY",
    },
    "easy_3": {
        "id": "easy_3", "difficulty": "easy",
        "description": "Fix syntax error. Count active employees per department.",
        "broken_query": "SELECT department, CONT(*) AS emp_count FROM employees WHERE status = 'active' GROUB BY department",
        "expected_query": "SELECT department, COUNT(*) AS emp_count FROM employees WHERE status = 'active' GROUP BY department",
        "hint": "CONT→COUNT, GROUB BY→GROUP BY",
    },
    "easy_4": {
        "id": "easy_4", "difficulty": "easy",
        "description": "Fix syntax error. Return names and budgets of all active projects.",
        "broken_query": "SELCT name, budget FEOM projects WHERE status = 'active'",
        "expected_query": "SELECT name, budget FROM projects WHERE status = 'active'",
        "hint": "SELCT→SELECT, FEOM→FROM",
    },
    "easy_5": {
        "id": "easy_5", "difficulty": "easy",
        "description": "Fix syntax error. Return employee names and salaries hired after 2020, ordered by hire_date.",
        "broken_query": "SELECT name, salary, hire_date FROM employees WHER hire_date > '2020-12-31' ORDER BE hire_date",
        "expected_query": "SELECT name, salary, hire_date FROM employees WHERE hire_date > '2020-12-31' ORDER BY hire_date",
        "hint": "WHER→WHERE, ORDER BE→ORDER BY",
    },
    "easy_6": {
        "id": "easy_6", "difficulty": "easy",
        "description": "Fix syntax error. Return the total budget across all departments.",
        "broken_query": "SELEC SUM(budget) AS total_budget FORM departments",
        "expected_query": "SELECT SUM(budget) AS total_budget FROM departments",
        "hint": "SELEC→SELECT, FORM→FROM",
    },
    "easy_7": {
        "id": "easy_7", "difficulty": "easy",
        "description": "Fix syntax error. Return distinct product categories from the products table.",
        "broken_query": "SELECT DESTINCT category FORM products ORDRE BY category",
        "expected_query": "SELECT DISTINCT category FROM products ORDER BY category",
        "hint": "DESTINCT→DISTINCT, FORM→FROM, ORDRE BY→ORDER BY",
    },

    # ── MEDIUM 1-7: JOIN, HAVING, subquery bugs ───────────────────────────────

    "medium_1": {
        "id": "medium_1", "difficulty": "medium",
        "description": "Fix the JOIN. Return each employee name, their project name, and hours_worked, ordered by employee name.",
        "broken_query": "SELECT e.name, p.name AS project_name, ep.hours_worked\nFROM employees e\nJOIN employee_projects ep ON e.id = ep.project_id\nJOIN projects p ON ep.employee_id = p.id\nORDER BY e.name",
        "expected_query": "SELECT e.name, p.name AS project_name, ep.hours_worked\nFROM employees e\nJOIN employee_projects ep ON e.id = ep.employee_id\nJOIN projects p ON ep.project_id = p.id\nORDER BY e.name",
        "hint": "JOIN columns swapped: use ep.employee_id and ep.project_id",
    },
    "medium_2": {
        "id": "medium_2", "difficulty": "medium",
        "description": "Fix WHERE/HAVING. Return departments with average salary above $85,000.",
        "broken_query": "SELECT department, COUNT(*) AS emp_count, AVG(salary) AS avg_salary\nFROM employees\nGROUP BY department\nWHERE AVG(salary) > 85000\nORDER BY avg_salary DESC",
        "expected_query": "SELECT department, COUNT(*) AS emp_count, AVG(salary) AS avg_salary\nFROM employees\nGROUP BY department\nHAVING AVG(salary) > 85000\nORDER BY avg_salary DESC",
        "hint": "Cannot use WHERE with aggregate functions. Use HAVING after GROUP BY.",
    },
    "medium_3": {
        "id": "medium_3", "difficulty": "medium",
        "description": "Fix the JOIN. Return project names with department names and locations.",
        "broken_query": "SELECT p.name AS project_name, d.name AS dept_name, d.location\nFROM projects p\nJOIN departments d ON p.id = d.id\nORDER BY p.name",
        "expected_query": "SELECT p.name AS project_name, d.name AS dept_name, d.location\nFROM projects p\nJOIN departments d ON p.department_id = d.id\nORDER BY p.name",
        "hint": "Use p.department_id = d.id, not p.id = d.id",
    },
    "medium_4": {
        "id": "medium_4", "difficulty": "medium",
        "description": "Fix the subquery. Return employees who earn more than the AVERAGE salary of their department.",
        "broken_query": "SELECT e.name, e.department, e.salary\nFROM employees e\nWHERE e.salary > (\n    SELECT MAX(salary) FROM employees\n    WHERE department = e.department\n)\nORDER BY e.department, e.salary DESC",
        "expected_query": "SELECT e.name, e.department, e.salary\nFROM employees e\nWHERE e.salary > (\n    SELECT AVG(salary) FROM employees\n    WHERE department = e.department\n)\nORDER BY e.department, e.salary DESC",
        "hint": "The subquery uses MAX() but should use AVG()",
    },
    "medium_5": {
        "id": "medium_5", "difficulty": "medium",
        "description": "Fix the JOIN. Return each salesperson name with their total sales amount.",
        "broken_query": "SELECT e.name, SUM(s.amount) AS total_sales\nFROM employees e\nJOIN sales s ON s.id = e.id\nGROUP BY e.name\nORDER BY total_sales DESC",
        "expected_query": "SELECT e.name, SUM(s.amount) AS total_sales\nFROM employees e\nJOIN sales s ON s.employee_id = e.id\nGROUP BY e.name\nORDER BY total_sales DESC",
        "hint": "Use s.employee_id = e.id, not s.id = e.id",
    },
    "medium_6": {
        "id": "medium_6", "difficulty": "medium",
        "description": "Fix the JOIN. Return employee names with their performance review ratings for 2023.",
        "broken_query": "SELECT e.name, pr.rating, pr.year\nFROM employees e\nJOIN performance_reviews pr ON pr.reviewer_id = e.id\nWHERE pr.year = 2023\nORDER BY pr.rating DESC",
        "expected_query": "SELECT e.name, pr.rating, pr.year\nFROM employees e\nJOIN performance_reviews pr ON pr.employee_id = e.id\nWHERE pr.year = 2023\nORDER BY pr.rating DESC",
        "hint": "Use pr.employee_id = e.id not pr.reviewer_id = e.id",
    },
    "medium_7": {
        "id": "medium_7", "difficulty": "medium",
        "description": "Fix HAVING clause. Return products by category where total stock exceeds 200 units.",
        "broken_query": "SELECT category, SUM(stock) AS total_stock, COUNT(*) AS product_count\nFROM products\nGROUP BY category\nWHERE SUM(stock) > 200\nORDER BY total_stock DESC",
        "expected_query": "SELECT category, SUM(stock) AS total_stock, COUNT(*) AS product_count\nFROM products\nGROUP BY category\nHAVING SUM(stock) > 200\nORDER BY total_stock DESC",
        "hint": "Use HAVING not WHERE when filtering on SUM()",
    },

    # ── HARD 1-6: Complex logic ───────────────────────────────────────────────

    "hard_1": {
        "id": "hard_1", "difficulty": "hard",
        "description": "Fix the JOIN type. Return departments with their total active project budget and count. Include only departments that have active projects.",
        "broken_query": "SELECT d.name, SUM(p.budget) AS total_budget, COUNT(p.id) AS project_count\nFROM departments d\nLEFT JOIN projects p ON d.id = p.department_id\nWHERE p.status = 'active'\nGROUP BY d.name\nHAVING COUNT(p.id) > 0\nORDER BY total_budget DESC",
        "expected_query": "SELECT d.name, SUM(p.budget) AS total_budget, COUNT(p.id) AS project_count\nFROM departments d\nJOIN projects p ON d.id = p.department_id\nWHERE p.status = 'active'\nGROUP BY d.name\nORDER BY total_budget DESC",
        "hint": "Use INNER JOIN instead of LEFT JOIN when filtering joined table with WHERE. Remove redundant HAVING.",
    },
    "hard_2": {
        "id": "hard_2", "difficulty": "hard",
        "description": "Fix the self-join. Return each employee's name and their manager's name. Employees without managers should show NULL for manager.",
        "broken_query": "SELECT e.name AS employee_name, m.name AS manager_name\nFROM employees e\nJOIN employees m ON m.id = e.id\nORDER BY e.name",
        "expected_query": "SELECT e.name AS employee_name, m.name AS manager_name\nFROM employees e\nLEFT JOIN employees m ON m.id = e.manager_id\nORDER BY e.name",
        "hint": "Self-join needs LEFT JOIN and join on e.manager_id = m.id, not e.id = m.id",
    },
    "hard_3": {
        "id": "hard_3", "difficulty": "hard",
        "description": "Fix the GROUP BY error. Return the top earning employee in each department with their salary.",
        "broken_query": "SELECT department, name, MAX(salary) AS max_salary\nFROM employees\nGROUP BY department\nORDER BY max_salary DESC",
        "expected_query": "SELECT department, name, salary AS max_salary\nFROM employees\nWHERE (department, salary) IN (\n    SELECT department, MAX(salary)\n    FROM employees\n    GROUP BY department\n)\nORDER BY max_salary DESC",
        "hint": "Cannot SELECT name with MAX(salary) unless name is in GROUP BY. Use a subquery to find max salary per department.",
    },
    "hard_4": {
        "id": "hard_4", "difficulty": "hard",
        "description": "Fix the query. Return total sales per region per product, only where total exceeds 5000.",
        "broken_query": "SELECT region, product, SUM(amount) AS total_sales\nFROM sales\nWHERE SUM(amount) > 5000\nGROUP BY region, product\nORDER BY total_sales DESC",
        "expected_query": "SELECT region, product, SUM(amount) AS total_sales\nFROM sales\nGROUP BY region, product\nHAVING SUM(amount) > 5000\nORDER BY total_sales DESC",
        "hint": "Cannot use aggregate functions in WHERE. Use HAVING after GROUP BY.",
    },
    "hard_5": {
        "id": "hard_5", "difficulty": "hard",
        "description": "Fix the multi-table query. Return each department name, total salary cost, and total project budget. Include all departments even without projects.",
        "broken_query": "SELECT d.name,\n       SUM(e.salary) AS total_salary,\n       SUM(p.budget) AS total_project_budget\nFROM departments d\nJOIN employees e ON e.department = d.name\nJOIN projects p ON p.department_id = d.id\nGROUP BY d.name\nORDER BY total_salary DESC",
        "expected_query": "SELECT d.name,\n       SUM(DISTINCT e.salary) AS total_salary,\n       SUM(DISTINCT p.budget) AS total_project_budget\nFROM departments d\nLEFT JOIN employees e ON e.department = d.name\nLEFT JOIN projects p ON p.department_id = d.id\nGROUP BY d.name\nORDER BY total_salary DESC",
        "hint": "Use LEFT JOIN to include all departments. Use SUM(DISTINCT ...) to avoid duplicate counting.",
    },
    "hard_6": {
        "id": "hard_6", "difficulty": "hard",
        "description": "Fix the query. Return employees who have worked on MORE THAN ONE project, along with their project count.",
        "broken_query": "SELECT e.name, COUNT(ep.project_id) AS project_count\nFROM employees e\nJOIN employee_projects ep ON ep.employee_id = e.id\nWHERE COUNT(ep.project_id) > 1\nGROUP BY e.name\nORDER BY project_count DESC",
        "expected_query": "SELECT e.name, COUNT(ep.project_id) AS project_count\nFROM employees e\nJOIN employee_projects ep ON ep.employee_id = e.id\nGROUP BY e.name\nHAVING COUNT(ep.project_id) > 1\nORDER BY project_count DESC",
        "hint": "Cannot use aggregate functions in WHERE. Use HAVING after GROUP BY.",
    },
}


# ── Database helpers ──────────────────────────────────────────────────────────

def create_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DB_SCHEMA + DB_SEED)
    return conn


def run_query(conn, query: str) -> Tuple[Optional[List[Dict]], Optional[str]]:
    try:
        cursor = conn.execute(query)
        rows   = [dict(row) for row in cursor.fetchall()]
        return rows, None
    except Exception as exc:
        return None, str(exc)


def _normalize_rows(rows: List[Dict]) -> List[tuple]:
    def norm(v: Any) -> str:
        if isinstance(v, float): return str(round(v, 2))
        return str(v)
    return sorted([tuple(sorted((k, norm(v)) for k, v in row.items())) for row in rows])


def _hash_query(query: str) -> str:
    return hashlib.md5(query.strip().lower().encode()).hexdigest()


# ── Advanced Grader with anti-hack rewards ────────────────────────────────────

def grade_submission(
    task_id: str,
    submitted_rows: Optional[List[Dict]],
    error: Optional[str],
    conn,
    submitted_hash: str,
    previous_hashes: Set[str],
    broken_hash: str,
) -> Tuple[float, str]:
    """
    Multi-signal grader with anti-hack protections.

    Scoring:
      +0.30  executes without error
      +0.20  correct columns
      +0.10  correct row count
      +0.40  correct row values (partial credit)

    Penalties:
      -0.15  submitting exact same query as previous attempt
      -0.30  submitting the broken query unchanged
    """
    task     = TASKS[task_id]
    score    = 0.0
    feedback = []

    # Anti-hack: penalize submitting broken query unchanged
    if submitted_hash == broken_hash:
        return 0.001, "Submitted the original broken query unchanged. Please fix the query."

    # Anti-hack: penalize exact duplicate submissions
    if submitted_hash in previous_hashes:
        return 0.001, "This exact query was already submitted. Please try a different approach."

    if error is not None:
        return 0.001, f"Query failed to execute: {error}"

    expected_rows, _ = run_query(conn, task["expected_query"])

    # +0.30 executes
    score += 0.30
    feedback.append("Query executes without error (+0.30)")

    # +0.20 correct columns
    sub_cols = set(submitted_rows[0].keys()) if submitted_rows else set()
    exp_cols = set(expected_rows[0].keys())  if expected_rows  else set()
    if sub_cols == exp_cols:
        score += 0.20
        feedback.append("Correct columns returned (+0.20)")
    else:
        missing = exp_cols - sub_cols
        extra   = sub_cols - exp_cols
        msg = "Wrong columns."
        if missing: msg += f" Missing: {sorted(missing)}."
        if extra:   msg += f" Unexpected: {sorted(extra)}."
        feedback.append(msg)

    # +0.10 correct row count
    sub_count = len(submitted_rows) if submitted_rows else 0
    exp_count = len(expected_rows)  if expected_rows  else 0
    if sub_count == exp_count:
        score += 0.10
        feedback.append(f"Correct row count: {exp_count} rows (+0.10)")
    else:
        feedback.append(f"Wrong row count: got {sub_count}, expected {exp_count}")

    # +0.40 correct values
    if submitted_rows and expected_rows:
        sub_norm = _normalize_rows(submitted_rows)
        exp_norm = _normalize_rows(expected_rows)
        if sub_norm == exp_norm:
            score += 0.40
            feedback.append("All row values match exactly! (+0.40)")
        elif sub_count == exp_count and sub_count > 0:
            matching = sum(1 for s, e in zip(sub_norm, exp_norm) if s == e)
            partial  = (matching / exp_count) * 0.40
            score   += partial
            feedback.append(f"Partial match: {matching}/{exp_count} rows correct (+{partial:.2f})")
        else:
            feedback.append("Row values do not match expected output.")

    score = max(0.001, min(0.999, round(score, 4)))
    return score, " | ".join(feedback)


# ── Environment ───────────────────────────────────────────────────────────────

class SQLRepairEnvironment(Environment):
    """
    SQL Repair Environment v3.
    20 tasks, anti-hack grader, rich partial-credit rewards, hint system.
    """
    SUPPORTS_CONCURRENT_SESSIONS = True
    MAX_ATTEMPTS = 5

    def __init__(self):
        self._state           = SQLState()
        self._task            = None
        self._conn            = None
        self._attempt         = 0
        self._last_score      = 0.001
        self._previous_hashes: Set[str] = set()
        self._broken_hash     = ""

    def reset(self, seed=None, episode_id=None, task_id=None, **kwargs) -> SQLObservation:
        if task_id and task_id in TASKS:
            self._task = TASKS[task_id]
        else:
            self._task = random.choice(list(TASKS.values()))

        if self._conn:
            self._conn.close()
        self._conn              = create_db()
        self._attempt           = 0
        self._last_score        = 0.001
        self._previous_hashes   = set()
        self._broken_hash       = _hash_query(self._task["broken_query"])

        exp_rows, _ = run_query(self._conn, self._task["expected_query"])
        exp_cols    = list(exp_rows[0].keys()) if exp_rows else []
        exp_count   = len(exp_rows) if exp_rows else -1

        self._state = SQLState(
            episode_id    = episode_id or str(uuid.uuid4()),
            step_count    = 0,
            task_id       = self._task["id"],
            difficulty    = self._task["difficulty"],
            max_attempts  = self.MAX_ATTEMPTS,
            last_score    = 0.001,
            completed     = False,
            attempts_used = 0,
        )

        return SQLObservation(
            done              = False,
            reward            = 0.001,
            broken_query      = self._task["broken_query"],
            db_schema         = SCHEMA_DESCRIPTION,
            error_message     = "",
            task_description  = self._task["description"],
            task_id           = self._task["id"],
            difficulty        = self._task["difficulty"],
            attempt_number    = 0,
            max_attempts      = self.MAX_ATTEMPTS,
            feedback          = "Episode started. Submit your fixed SQL query.",
            hint              = "",
            expected_columns  = exp_cols,
            expected_row_count= exp_count,
        )

    def step(self, action: SQLAction, timeout_s=None, **kwargs) -> SQLObservation:
        self._attempt          += 1
        self._state.step_count += 1
        self._state.attempts_used = self._attempt

        submitted_hash = _hash_query(action.sql_query)
        rows, error    = run_query(self._conn, action.sql_query)

        score, feedback = grade_submission(
            self._task["id"], rows, error, self._conn,
            submitted_hash, self._previous_hashes, self._broken_hash,
        )

        self._previous_hashes.add(submitted_hash)
        self._last_score       = score
        self._state.last_score = score

        done = (score >= 0.99) or (self._attempt >= self.MAX_ATTEMPTS)
        self._state.completed  = score >= 0.99

        reward = max(0.001, min(0.999, score))
        if done and score < 0.99 and self._attempt >= self.MAX_ATTEMPTS:
            reward = max(0.001, round(score * 0.85, 4))

        hint = ""
        if self._attempt >= 2 and score < 0.5:
            hint = self._task["hint"]

        exp_rows, _ = run_query(self._conn, self._task["expected_query"])
        exp_cols    = list(exp_rows[0].keys()) if exp_rows else []
        exp_count   = len(exp_rows) if exp_rows else -1

        return SQLObservation(
            done              = done,
            reward            = reward,
            broken_query      = self._task["broken_query"],
            db_schema         = SCHEMA_DESCRIPTION,
            error_message     = error or "",
            task_description  = self._task["description"],
            task_id           = self._task["id"],
            difficulty        = self._task["difficulty"],
            attempt_number    = self._attempt,
            max_attempts      = self.MAX_ATTEMPTS,
            feedback          = feedback,
            hint              = hint,
            expected_columns  = exp_cols,
            expected_row_count= exp_count,
        )

    @property
    def state(self) -> SQLState:
        return self._state

    @staticmethod
    def list_tasks() -> List[Dict]:
        return [
            {
                "task_id":      t["id"],
                "difficulty":   t["difficulty"],
                "description":  t["description"],
                "broken_query": t["broken_query"],
                "action_schema": {
                    "sql_query":   "string (required) - Your corrected SQL query",
                    "explanation": "string (optional) - Your reasoning",
                },
            }
            for t in TASKS.values()
        ]

    @staticmethod
    def run_grader(task_id: str, sql_query: str) -> Dict:
        if task_id not in TASKS:
            return {"error": f"Unknown task_id '{task_id}'. Available: {list(TASKS.keys())}"}
        conn           = create_db()
        submitted_hash = _hash_query(sql_query)
        broken_hash    = _hash_query(TASKS[task_id]["broken_query"])
        rows, error    = run_query(conn, sql_query)
        score, feedback = grade_submission(task_id, rows, error, conn, submitted_hash, set(), broken_hash)
        conn.close()
        return {
            "task_id":  task_id,
            "score":    score,
            "feedback": feedback,
            "passed":   score >= 0.99,
        }
