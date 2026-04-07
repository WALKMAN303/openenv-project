"""
inference.py — SQL Repair Environment agent using required [START]/[STEP]/[END] stdout format.

Required env vars:
    API_BASE_URL      LLM API endpoint  (default: https://api.groq.com/openai/v1)
    MODEL_NAME        Model identifier  (default: llama-3.1-8b-instant)
    HF_TOKEN          Hugging Face / API key
    SPACE_URL         Running environment URL (default: http://localhost:7860)
    LOCAL_IMAGE_NAME  Docker image name if using from_docker_image() (optional)
"""

import os
import sys
from typing import List, Optional

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# ── Required environment variables ────────────────────────────────────────────
API_BASE_URL     = os.getenv("API_BASE_URL", "https://api.groq.com/openai/v1")
MODEL_NAME       = os.getenv("MODEL_NAME",   "llama-3.1-8b-instant")
HF_TOKEN         = os.getenv("HF_TOKEN")
SPACE_URL        = os.getenv("SPACE_URL", "http://localhost:7860")
LOCAL_IMAGE_NAME = os.getenv("LOCAL_IMAGE_NAME")

BENCHMARK = "sql-repair-env"

from openai import OpenAI
from client import SQLRepairEnv
from models import SQLAction

# ── OpenAI client ──────────────────────────────────────────────────────────────
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


# ── Required stdout helpers ────────────────────────────────────────────────────

def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    # Inline the action on one line — strip newlines so the line stays single
    action_inline = action.replace("\n", " ").replace("\r", "")
    error_val = error if error else "null"
    done_val = str(done).lower()
    print(
        f"[STEP] step={step} action={action_inline} reward={reward:.2f} done={done_val} error={error_val}",
        flush=True,
    )


def log_end(task: str, success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(
        f"[END] task={task} success={str(success).lower()} steps={steps} score={score:.2f} rewards={rewards_str}",
        flush=True,
    )


# ── Prompt builder ────────────────────────────────────────────────────────────

def build_prompt(observation) -> str:
    parts = [
        f"Task: {observation.task_description}",
        "",
        "Database Schema:",
        observation.db_schema,
        "",
        "Broken Query:",
        observation.broken_query,
    ]
    if observation.error_message:
        parts += ["", f"Error: {observation.error_message}"]
    if observation.feedback and observation.attempt_number > 0:
        parts += ["", f"Grader feedback: {observation.feedback}"]
    if observation.hint:
        parts += ["", f"Hint: {observation.hint}"]
    parts += ["", "Return ONLY the fixed SQL query:"]
    return "\n".join(parts)


# ── Single-task episode ───────────────────────────────────────────────────────

def run_task(env, task_id: str) -> float:
    """Run one episode; emit [START]/[STEP]/[END] lines; return final score."""
    log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)

    rewards: List[float] = []
    steps_taken = 0
    score = 0.0
    success = False

    try:
        result = env.reset(task_id=task_id)
        obs = result.observation

        while not result.done:
            steps_taken += 1
            prompt = build_prompt(obs)

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

            result = env.step(SQLAction(sql_query=fixed_query))
            obs = result.observation

            reward = result.reward or 0.0
            rewards.append(reward)

            error_msg = obs.error_message if obs.error_message else None
            log_step(
                step=steps_taken,
                action=fixed_query,
                reward=reward,
                done=result.done,
                error=error_msg,
            )

        score = rewards[-1] if rewards else 0.0
        success = score >= 0.99

    finally:
        log_end(task=task_id, success=success, steps=steps_taken, score=score, rewards=rewards)

    return score


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    task_ids = ["easy", "medium", "hard"]
    scores = {}

    with SQLRepairEnv(base_url=SPACE_URL).sync() as env:
        for task_id in task_ids:
            try:
                scores[task_id] = run_task(env, task_id)
            except Exception as exc:
                # Still emit a valid [END] so the validator sees output
                print(
                    f"[END] task={task_id} success=false steps=0 score=0.01 rewards=0.01",
                    flush=True,
                )
                print(f"[DEBUG] Exception on {task_id}: {exc}", flush=True, file=sys.stderr)
                scores[task_id] = 0.01

    avg = sum(scores.values()) / len(scores) if scores else 0.0
    print(
        f"[SUMMARY] model={MODEL_NAME} easy={scores.get('easy', 0):.2f} "
        f"medium={scores.get('medium', 0):.2f} hard={scores.get('hard', 0):.2f} "
        f"average={avg:.2f}",
        flush=True,
    )


if __name__ == "__main__":
    main()