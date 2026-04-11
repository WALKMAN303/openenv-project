"""
server/app.py - FastAPI server for SQL Repair Environment v2
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi import Request
from fastapi.responses import JSONResponse, HTMLResponse
from openenv.core.env_server import create_fastapi_app
from models import SQLAction, SQLObservation
from server.environment import SQLRepairEnvironment, TASKS

app = create_fastapi_app(SQLRepairEnvironment, SQLAction, SQLObservation)

# Load UI HTML
_UI_PATH = os.path.join(ROOT, "ui.html")
try:
    with open(_UI_PATH, "r") as f:
        _UI_HTML = f.read()
except FileNotFoundError:
    _UI_HTML = "<h1>SQL Repair Environment</h1><p>UI not found. Use /docs for API.</p>"


@app.get("/", response_class=HTMLResponse)
def root():
    """Serve the interactive UI."""
    return HTMLResponse(content=_UI_HTML)


@app.get("/info")
def info():
    """JSON info for the environment."""
    return JSONResponse(content={
        "name":        "SQL Repair Environment",
        "version":     "2.0.0",
        "status":      "running",
        "total_tasks": len(TASKS),
        "difficulty_breakdown": {
            "easy":   len([t for t in TASKS.values() if t["difficulty"] == "easy"]),
            "medium": len([t for t in TASKS.values() if t["difficulty"] == "medium"]),
            "hard":   len([t for t in TASKS.values() if t["difficulty"] == "hard"]),
        },
        "endpoints": {
            "ui":       "/",
            "health":   "/health",
            "docs":     "/docs",
            "tasks":    "/tasks",
            "grader":   "/grader",
            "baseline": "/baseline",
            "reset":    "/reset",
            "step":     "/step",
            "state":    "/state",
        }
    })


@app.get("/tasks", tags=["Competition"])
def get_tasks():
    """List all 15 tasks with descriptions and action schema."""
    return JSONResponse(content={
        "tasks": SQLRepairEnvironment.list_tasks(),
        "total": len(TASKS),
        "difficulty_breakdown": {
            "easy":   5,
            "medium": 5,
            "hard":   5,
        },
        "action_schema": {
            "sql_query":   "string - The fixed SQL query to submit",
            "explanation": "string (optional) - Agent reasoning",
        },
    })


@app.post("/grader", tags=["Competition"])
def run_grader(task_id: str, sql_query: str):
    """Grade a SQL query against a specific task. Returns score 0.001-0.999."""
    result = SQLRepairEnvironment.run_grader(task_id, sql_query)
    return JSONResponse(content=result)


@app.get("/baseline", tags=["Competition"])
def run_baseline():
    """Run oracle baseline on all 15 tasks. Returns perfect scores."""
    baseline_scores = {}
    for task_id, task in TASKS.items():
        result = SQLRepairEnvironment.run_grader(task_id, task["expected_query"])
        baseline_scores[task_id] = {
            "score":      result["score"],
            "passed":     result["passed"],
            "difficulty": task["difficulty"],
            "feedback":   result["feedback"],
        }

    by_difficulty = {"easy": [], "medium": [], "hard": []}
    for task_id, res in baseline_scores.items():
        by_difficulty[res["difficulty"]].append(res["score"])

    avg = sum(v["score"] for v in baseline_scores.values()) / len(baseline_scores)

    return JSONResponse(content={
        "baseline_agent":  "oracle (submits known correct query)",
        "results":         baseline_scores,
        "average_score":   round(avg, 4),
        "by_difficulty": {
            "easy":   round(sum(by_difficulty["easy"])   / len(by_difficulty["easy"]),   4),
            "medium": round(sum(by_difficulty["medium"]) / len(by_difficulty["medium"]), 4),
            "hard":   round(sum(by_difficulty["hard"])   / len(by_difficulty["hard"]),   4),
        },
    })


def main():
    """Entry point for uv run server and [project.scripts]."""
    import uvicorn
    port    = int(os.environ.get("PORT", 7860))
    host    = os.environ.get("HOST", "0.0.0.0")
    workers = int(os.environ.get("WORKERS", 4))
    uvicorn.run("server.app:app", host=host, port=port, workers=workers)


if __name__ == "__main__":
    main()
