"""
models.py - Type-safe data contracts for SQL Repair Environment v3.
Uses Field() descriptors matching reference environment pattern exactly.
"""

from typing import Optional, List
from pydantic import Field
from openenv.core.env_server import Action, Observation, State


class SQLAction(Action):
    """Action: submit a fixed SQL query."""
    sql_query: str = Field(..., description="The corrected SQL query to execute")
    explanation: str = Field(default="", description="Optional agent reasoning")


class SQLObservation(Observation):
    """
    Observation returned after reset() or step().
    done and reward are inherited from Observation base.
    """
    broken_query: str = Field(..., description="The broken SQL query to fix")
    db_schema: str = Field(..., description="Database schema - table and column definitions")
    error_message: str = Field(default="", description="SQL execution error from last attempt")
    task_description: str = Field(default="", description="What the fixed query should return")
    task_id: str = Field(default="", description="Task identifier")
    difficulty: str = Field(default="", description="easy | medium | hard")
    attempt_number: int = Field(default=0, description="Current attempt number")
    max_attempts: int = Field(default=5, description="Maximum allowed attempts")
    feedback: str = Field(default="", description="Detailed grader feedback")
    hint: str = Field(default="", description="Hint revealed after 2 failed attempts")
    expected_columns: List[str] = Field(default_factory=list, description="Expected output column names")
    expected_row_count: int = Field(default=-1, description="Expected number of rows (-1 = unknown)")


class SQLState(State):
    """
    Episode metadata returned by state().
    episode_id and step_count are inherited from State base.
    """
    task_id: str = Field(default="", description="Current task identifier")
    difficulty: str = Field(default="", description="Task difficulty level")
    max_attempts: int = Field(default=5, description="Maximum steps per episode")
    last_score: float = Field(default=0.001, description="Score from most recent step")
    completed: bool = Field(default=False, description="True if agent achieved perfect score")
    attempts_used: int = Field(default=0, description="Number of attempts used so far")
