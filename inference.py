"""
inference.py - LLM Baseline Agent for SQL Repair Environment.
Must be at repo root for openenv validation.

Usage:
    set OPENAI_API_KEY=gsk_your_groq_key_here
    python inference.py --url https://WALKMAN303-sql-repair-env.hf.space
"""

import os
import sys
import argparse
import json

# Add paths so imports work from repo root
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "OpenEnv"))
sys.path.insert(0, os.path.join(ROOT, "OpenEnv", "src"))

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai not installed. Run: pip install openai")
    sys.exit(1)

try:
    from client import SQLRepairEnv
    from models import SQLAction
except ImportError as e:
    print(f"ERROR importing client/models: {e}")
    sys.exit(1)


SYSTEM_PROMPT = """You are an expert SQL developer who fixes broken SQL queries.
Return ONLY the corrected SQL query. No explanation, no markdown, no code blocks. Just raw SQL.

Common bugs to fix:
- Misspelled keywords: SELCT->SELECT, FORM->FROM, WERE->WHERE, ORDR->ORDER
- Wrong JOIN columns: check which columns link which tables
- WHERE vs HAVING: use HAVING with aggregate functions like AVG(), COUNT()
"""


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


def run_episode(env, client, task_id, verbose=True):
    if verbose:
        print(f"\n{'─'*60}")
        print(f"Task: {task_id.upper()}")
        print(f"{'─'*60}")

    result = env.reset(task_id=task_id)
    obs = result.observation

    if verbose:
        print(f"Broken query:\n{obs.broken_query}\n")

    while not result.done:
        prompt = build_prompt(obs)

        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=500,
            )
            fixed_query = response.choices[0].message.content.strip()
            fixed_query = fixed_query.replace("```sql", "").replace("```", "").strip()
        except Exception as e:
            print(f"LLM call failed: {e}")
            fixed_query = obs.broken_query

        if verbose:
            print(f"Attempt {obs.attempt_number + 1}: Submitting ->")
            print(f"  {fixed_query[:100]}{'...' if len(fixed_query) > 100 else ''}")

        result = env.step(SQLAction(sql_query=fixed_query))
        obs = result.observation

        if verbose:
            print(f"  Score: {result.reward:.4f} | Done: {result.done}")
            if obs.feedback:
                print(f"  Feedback: {obs.feedback[:120]}")

    final_score = result.reward or 0.0
    if verbose:
        status = "SOLVED" if final_score >= 1.0 else f"SCORE: {final_score:.4f}"
        print(f"\n  Final result: {status}")

    return final_score


def main():
    parser = argparse.ArgumentParser(
        description="Run LLM baseline agent on SQL Repair Environment"
    )
    parser.add_argument(
        "--url",
        default="http://localhost:7860",
        help="Base URL of the environment"
    )
    parser.add_argument(
        "--task",
        choices=["easy", "medium", "hard", "all"],
        default="all",
        help="Which task to run"
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("\nERROR: OPENAI_API_KEY is not set!")
        print("Run: set OPENAI_API_KEY=gsk_your_groq_key_here")
        sys.exit(1)

    print(f"API key found: {api_key[:8]}...")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1"
    )

    task_ids = ["easy", "medium", "hard"] if args.task == "all" else [args.task]
    verbose = not args.quiet

    print(f"\n{'='*60}")
    print(f"SQL Repair Environment - LLM Baseline (llama-3.1-8b-instant)")
    print(f"Server: {args.url}")
    print(f"Tasks:  {', '.join(task_ids)}")
    print(f"{'='*60}")

    scores = {}

    with SQLRepairEnv(base_url=args.url).sync() as env:
        for task_id in task_ids:
            try:
                score = run_episode(env, client, task_id, verbose=verbose)
                scores[task_id] = score
            except Exception as exc:
                print(f"ERROR on task {task_id}: {exc}")
                import traceback
                traceback.print_exc()
                scores[task_id] = 0.0

    print(f"\n{'='*60}")
    print(f"BASELINE RESULTS")
    print(f"{'='*60}")
    for task_id, score in scores.items():
        bar = "█" * int(score * 20)
        status = "PASS" if score >= 1.0 else "FAIL"
        print(f"  {task_id:8s}  [{bar:<20}]  {score:.4f}  {status}")

    avg = sum(scores.values()) / len(scores) if scores else 0.0
    print(f"  {'─'*45}")
    print(f"  Average: {avg:.4f}")
    print(f"{'='*60}\n")

    result_payload = {
        "model": "llama-3.1-8b-instant",
        "scores": scores,
        "average_score": round(avg, 4),
    }
    print(json.dumps(result_payload, indent=2))
    return scores


if __name__ == "__main__":
    main()
