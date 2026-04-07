import os
import sys
import json

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# ── Required environment variables (as per submission checklist) ──────────────
API_BASE_URL = os.getenv("API_BASE_URL", "https://api.groq.com/openai/v1")
MODEL_NAME   = os.getenv("MODEL_NAME",   "llama-3.1-8b-instant")
HF_TOKEN     = os.getenv("HF_TOKEN")

# Optional - for from_docker_image()
LOCAL_IMAGE_NAME = os.getenv("LOCAL_IMAGE_NAME")

from openai import OpenAI
from client import SQLRepairEnv
from models import SQLAction

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

ENV_URL = os.getenv("API_BASE_URL", "http://localhost:7860").replace(
    "https://api.groq.com/openai/v1", "http://localhost:7860"
)

# Use a separate env URL variable
SPACE_URL = os.getenv("SPACE_URL", "http://localhost:7860")


def build_prompt(observation):
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


def run_task(env, task_id):
    """Run one episode and return score."""
    # START log
    print(json.dumps({"type": "START", "task_id": task_id}))

    result = env.reset(task_id=task_id)
    obs    = result.observation
    step   = 0

    while not result.done:
        step += 1
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
        obs    = result.observation

        # STEP log
        print(json.dumps({
            "type":     "STEP",
            "task_id":  task_id,
            "step":     step,
            "score":    result.reward,
            "done":     result.done,
            "feedback": obs.feedback,
        }))

    final_score = result.reward or 0.0

    # END log
    print(json.dumps({
        "type":        "END",
        "task_id":     task_id,
        "final_score": final_score,
        "passed":      final_score >= 1.0,
    }))

    return final_score


def main():
    space_url = os.getenv("SPACE_URL", "http://localhost:7860")
    task_ids  = ["easy", "medium", "hard"]
    scores    = {}

    with SQLRepairEnv(base_url=space_url).sync() as env:
        for task_id in task_ids:
            try:
                scores[task_id] = run_task(env, task_id)
            except Exception as exc:
                print(json.dumps({"type": "ERROR", "task_id": task_id, "error": str(exc)}))
                scores[task_id] = 0.0

    avg = sum(scores.values()) / len(scores) if scores else 0.0

    print(json.dumps({
        "type":          "SUMMARY",
        "model":         MODEL_NAME,
        "scores":        scores,
        "average_score": round(avg, 4),
    }))


if __name__ == "__main__":
    main()
