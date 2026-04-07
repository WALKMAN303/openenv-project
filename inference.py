"""
inference.py — Baseline LLM agent for the SQL Repair Environment.

Required env vars:
    API_BASE_URL   The API endpoint for the LLM (OpenAI-compatible)
    MODEL_NAME     The model identifier to use for inference
    HF_TOKEN       Your Hugging Face / API key

Usage:
    python inference.py
    python inference.py --url https://WALKMAN303-sql-repair-env.hf.space
"""

import os
import json
import time
import argparse
import requests
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────
ENV_URL     = os.environ.get("ENV_URL", "https://WALKMAN303-sql-repair-env.hf.space")
API_BASE_URL = os.environ.get("API_BASE_URL", "https://api.groq.com/openai/v1")
MODEL_NAME  = os.environ.get("MODEL_NAME", "llama3-8b-8192")
HF_TOKEN    = os.environ.get("HF_TOKEN", "")

TASKS       = ["easy", "medium", "hard"]
MAX_STEPS   = 5

# ── OpenAI-compatible client ──────────────────────────────────────────────────
client = OpenAI(
    base_url=API_BASE_URL,
    api_key=HF_TOKEN or "dummy",
)

# ── Helper: call LLM ──────────────────────────────────────────────────────────
def llm_fix_sql(broken_query: str, db_schema: str, task_description: str,
                error_message: str, feedback: str, hint: str) -> str:
    """Ask the LLM to repair a broken SQL query. Returns the fixed SQL string."""
    system_prompt = (
        "You are an expert SQL debugger. "
        "Your job is to fix the broken SQL query provided by the user. "
        "Return ONLY the corrected SQL query — no markdown, no explanation, "
        "no code fences. Just the raw SQL."
    )

    hint_section = f"\nHint: {hint}" if hint else ""
    feedback_section = f"\nPrevious feedback: {feedback}" if feedback else ""
    error_section = f"\nExecution error: {error_message}" if error_message else ""

    user_prompt = (
        f"Task: {task_description}\n\n"
        f"Database schema:\n{db_schema}\n\n"
        f"Broken SQL:\n{broken_query}"
        f"{error_section}"
        f"{feedback_section}"
        f"{hint_section}\n\n"
        "Return ONLY the fixed SQL query."
    )

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.0,
        max_tokens=512,
    )
    return response.choices[0].message.content.strip()


# ── Helper: env HTTP calls ────────────────────────────────────────────────────
def env_reset(base_url: str, task_id: str) -> dict:
    resp = requests.post(f"{base_url}/reset", json={"task_id": task_id}, timeout=30)
    resp.raise_for_status()
    return resp.json()

def env_step(base_url: str, sql_query: str, explanation: str = "") -> dict:
    resp = requests.post(
        f"{base_url}/step",
        json={"sql_query": sql_query, "explanation": explanation},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ── Main loop ─────────────────────────────────────────────────────────────────
def run_task(base_url: str, task_id: str) -> float:
    """Run one full episode for a task. Returns the final score."""

    # Reset environment
    reset_result = env_reset(base_url, task_id)
    obs = reset_result.get("observation", reset_result)

    episode_id   = reset_result.get("episode_id", "unknown")
    broken_query = obs.get("broken_query", "")
    db_schema    = obs.get("db_schema", "")
    task_desc    = obs.get("task_description", "")

    print(json.dumps({
        "event":      "[START]",
        "task_id":    task_id,
        "episode_id": episode_id,
        "broken_sql": broken_query,
    }))

    final_score  = 0.0
    step_count   = 0

    for step in range(1, MAX_STEPS + 1):
        error_msg = obs.get("error_message", "")
        feedback  = obs.get("feedback", "")
        hint      = obs.get("hint", "")

        # Ask LLM to fix
        fixed_sql = llm_fix_sql(
            broken_query=broken_query,
            db_schema=db_schema,
            task_description=task_desc,
            error_message=error_msg,
            feedback=feedback,
            hint=hint,
        )

        # Submit to environment
        step_result = env_step(base_url, fixed_sql, explanation="LLM fix")
        obs         = step_result.get("observation", step_result)
        reward      = step_result.get("reward", 0.0)
        done        = step_result.get("done", False)
        step_count  = step

        print(json.dumps({
            "event":     "[STEP]",
            "task_id":   task_id,
            "step":      step,
            "sql":       fixed_sql,
            "reward":    reward,
            "done":      done,
            "feedback":  obs.get("feedback", ""),
        }))

        final_score = reward
        if done:
            break

    print(json.dumps({
        "event":       "[END]",
        "task_id":     task_id,
        "episode_id":  episode_id,
        "steps":       step_count,
        "final_score": final_score,
    }))

    return final_score


def main():
    parser = argparse.ArgumentParser(description="SQL Repair Environment — LLM Baseline")
    parser.add_argument("--url", default=ENV_URL, help="Base URL of the environment")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    scores   = {}

    for task_id in TASKS:
        try:
            score = run_task(base_url, task_id)
            scores[task_id] = score
        except Exception as exc:
            print(json.dumps({"event": "[ERROR]", "task_id": task_id, "error": str(exc)}))
            scores[task_id] = 0.0
        time.sleep(1)   # small pause between tasks

    print(json.dumps({
        "event":        "[SUMMARY]",
        "scores":       scores,
        "average":      round(sum(scores.values()) / len(scores), 4),
    }))


if __name__ == "__main__":
    main()
