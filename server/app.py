"""
server/app.py — FastAPI server for the SQL Repair Environment.
"""

import os
import sys
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openenv.core.env_server import create_fastapi_app
from models import SQLAction, SQLObservation
from server.environment import SQLRepairEnvironment, TASKS, run_query, grade_submission, create_db

# Auto-creates /reset /step /state /health /ws /docs
app = create_fastapi_app(SQLRepairEnvironment, SQLAction, SQLObservation)


@app.get("/tasks", tags=["Competition"])
def get_tasks():
    """List all available tasks and their action schema."""
    return JSONResponse(
        content={
            "tasks": SQLRepairEnvironment.list_tasks(),
            "total": len(TASKS),
            "action_schema": {
                "sql_query":   "string — The fixed SQL query to submit",
                "explanation": "string (optional) — Agent's reasoning",
            },
        }
    )


@app.post("/grader", tags=["Competition"])
def run_grader(task_id: str, sql_query: str):
    """Score a SQL query against a task. Returns score 0.0–1.0."""
    result = SQLRepairEnvironment.run_grader(task_id, sql_query)
    return JSONResponse(content=result)


@app.get("/baseline", tags=["Competition"])
def run_baseline():
    """Run oracle baseline against all 3 tasks. Returns scores."""
    baseline_scores = {}
    for task_id, task in TASKS.items():
        result = SQLRepairEnvironment.run_grader(task_id, task["expected_query"])
        baseline_scores[task_id] = {
            "score":    result["score"],
            "passed":   result["passed"],
            "feedback": result["feedback"],
        }
    avg = sum(v["score"] for v in baseline_scores.values()) / len(baseline_scores)
    return JSONResponse(
        content={
            "baseline_agent":  "oracle (submits known correct query)",
            "results":         baseline_scores,
            "average_score":   round(avg, 4),
        }
    )
