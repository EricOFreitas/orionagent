import os
from datetime import datetime

from peewee import (
    AutoField,
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
)

# Resolve the database path and ensure the directory exists before Peewee opens the file.
_db_path = os.getenv("DATABASE_PATH", "data/orion.db")
os.makedirs(os.path.dirname(os.path.abspath(_db_path)), exist_ok=True)

database = SqliteDatabase(
    _db_path,
    pragmas={
        "journal_mode": "wal",   # better concurrency
        "foreign_keys": 1,
    },
)


class BaseModel(Model):
    class Meta:
        database = database


class Project(BaseModel):
    """An ongoing project with an optional deadline."""

    id = AutoField()
    name = CharField(max_length=200)
    description = TextField(null=True)
    deadline = DateField(null=True)
    status = CharField(max_length=50, default="active")  # active | completed | paused
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "projects"


class DailyPlan(BaseModel):
    """The result of a morning ritual or /planejar session."""

    id = AutoField()
    date = DateField()
    priorities = TextField()          # summarised top-3 priorities
    energy_level = IntegerField(null=True)
    raw_conversation = TextField(null=True)
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "daily_plans"


class Decision(BaseModel):
    """A recorded decision made with the agent's help."""

    id = AutoField()
    context = TextField()             # original dilemma (first user message)
    conclusion = TextField(null=True) # last assistant recommendation
    rationale = TextField(null=True)  # conversation summary
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "decisions"


class Interaction(BaseModel):
    """Summarised log of each finished agent session."""

    id = AutoField()
    type = CharField(max_length=100)  # morning_ritual | planning | decision | weekly_review
    summary = TextField()
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "interactions"


class Task(BaseModel):
    """A task or appointment with an optional date and time for reminders."""

    id = AutoField()
    title = CharField(max_length=300)
    due_date = DateField(null=True)
    due_time = CharField(max_length=5, null=True)   # "HH:MM"
    reminder_sent = BooleanField(default=False)
    status = CharField(max_length=50, default="pending")  # pending | done | cancelled
    notes = TextField(null=True)
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "tasks"


class Settings(BaseModel):
    """Key–value store for runtime configuration."""

    key = CharField(max_length=100, primary_key=True)
    value = TextField()

    class Meta:
        table_name = "settings"


def initialize_db() -> None:
    """Connect to the database and create all tables if they do not exist."""
    database.connect(reuse_if_open=True)
    database.create_tables(
        [Project, DailyPlan, Decision, Interaction, Task, Settings],
        safe=True,
    )
