"""
inference.py - SQL Repair Environment Baseline Agent
Must be at repo root. Follows OpenEnv submission format exactly.
"""

import os
import sys
from typing import List, Optional

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from openai import OpenAI
from client import SQLRepairEnv
from models import SQLAction

# ── Required environment variables ───────────────────────────────────────────
API_BASE_URL     = os.getenv("API_BASE_URL", "https://api.groq.com/openai/v1")
MODEL_NAME       = os.getenv("MODEL_NAME",   "llama-3.1-8b-instant")
HF_TOKEN         = os.getenv("HF_TOKEN")
LOCAL_IMAGE_NAME = os.getenv("LOCAL_IMAGE_NAME")

# Space URL — where the environment is running
SPACE_URL = os.getenv("SPACE_URL", "https://open-env-project-sql-repair-env.hf.space")
BENCHMARK = "sql-repair-env"
TASK_IDS  = ["easy", "medium", "hard"]
MAX_STEPS = 5

# ── OpenAI client configured via environment variables ────────────────────────
client = OpenAI(
    api_key=HF_TOKEN or os.getenv("OPENAI_API_KEY", ""),
    base_url=API_BASE_URL,
)

SYSTEM_PROMPT = """You are an expert SQL developer who fixes broken SQL queries.
Return ONLY the corrected SQL query. No explanation, no markdown, no code blocks.

Common bugs:
- Misspelled keywords: SELCT->SELECT, FORM->FROM, WERE->WHERE, ORDR->ORDER
- Wrong JOIN columns: check which columns link which tables
- WHERE vs HAVING: use HAVING with aggregate functions like AVG(), COUNT()
"""


# ── Required log functions ────────────────────────────────────────────────────

def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    error_val   = error if error else "null"
    done_val    = str(done).lower()
    action_clean = action.replace("\n", " ")[:60]
    print(
        f"[STEP] step={step} action={action_clean!r} reward={reward:.2f} done={done_val} error={error_val}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} score={score:.2f} rewards={rewards_str}",
        flush=True,
    )


def build_prompt(obs) -> str:
    parts = [
        f"Task: {obs.task_description}",
        "",
        "Database Schema:",
        obs.db_schema,
        "",
        "Broken Query:",
        obs.broken_query,
    ]
    if obs.error_message:
        parts += ["", f"Error: {obs.error_message}"]
    if obs.feedback and obs.attempt_number > 0:
        parts += ["", f"Grader feedback: {obs.feedback}"]
    if obs.hint:
        parts += ["", f"Hint: {obs.hint}"]
    parts += ["", "Return ONLY the fixed SQL query:"]
    return "\n".join(parts)


def run_task(env, task_id: str) -> float:
    rewards:     List[float] = []
    steps_taken: int         = 0
    score:       float       = 0.0
    success:     bool        = False

    # ── PRINT [START] IMMEDIATELY ─────────────────────────────────────────────
    log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)

    try:
        result = env.reset(task_id=task_id)
        obs    = result.observation

        for step in range(1, MAX_STEPS + 1):
            if result.done:
                break

            prompt = build_prompt(obs)

            try:
                response = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": prompt},
                    ],
                    temperature=0.0,
                    max_tokens=500,
                )
                fixed_query = response.choices[0].message.content.strip()
                fixed_query = fixed_query.replace("```sql", "").replace("```", "").strip()
            except Exception as e:
                fixed_query = obs.broken_query
                print(f"[DEBUG] LLM error: {e}", flush=True)

            result = env.step(SQLAction(sql_query=fixed_query))
            obs    = result.observation

            reward = result.reward or 0.0
            done   = result.done
            error  = obs.error_message if obs.error_message else None

            rewards.append(reward)
            steps_taken = step

            # ── PRINT [STEP] EVERY STEP ───────────────────────────────────────
            log_step(
                step=step,
                action=fixed_query,
                reward=reward,
                done=done,
                error=error,
            )

            if done:
                break

        score   = max(rewards) if rewards else 0.0
        score   = min(max(score, 0.0), 1.0)
        success = score >= 1.0

    except Exception as e:
        print(f"[DEBUG] Task error: {e}", flush=True)
        score   = 0.0
        success = False

    finally:
        # ── PRINT [END] ALWAYS ────────────────────────────────────────────────
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)

    return score


def main():
    print(f"[DEBUG] Starting inference", flush=True)
    print(f"[DEBUG] API_BASE_URL={API_BASE_URL}", flush=True)
    print(f"[DEBUG] MODEL_NAME={MODEL_NAME}", flush=True)
    print(f"[DEBUG] SPACE_URL={SPACE_URL}", flush=True)

    all_scores = {}

    try:
        with SQLRepairEnv(base_url=SPACE_URL).sync() as env:
            for task_id in TASK_IDS:
                score = 0.0
                try:
                    score = run_task(env, task_id)
                except Exception as e:
                    print(f"[DEBUG] Task {task_id} failed: {e}", flush=True)
                    # Still print START and END even on failure
                    log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)
                    log_end(success=False, steps=0, score=0.0, rewards=[0.0])
                all_scores[task_id] = score

    except Exception as e:
        print(f"[DEBUG] Connection failed: {e}", flush=True)
        # Print required output even if connection fails
        for task_id in TASK_IDS:
            log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)
            log_end(success=False, steps=0, score=0.0, rewards=[0.0])

    avg = sum(all_scores.values()) / len(all_scores) if all_scores else 0.0
    print(f"[SUMMARY] scores={all_scores} average={avg:.2f}", flush=True)


if __name__ == "__main__":
    main()
