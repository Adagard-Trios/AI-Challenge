"""
Columns added to a model must reach databases that already exist.

init_db() calls Base.metadata.create_all, which creates missing TABLES and does
nothing whatsoever to existing ones. So adding a column to a model leaves every
older database with the old shape, and the failure surfaces later as
"no such column" on a query that looks unrelated to the change.

That is not hypothetical. Adding budget_* to SocialConnection broke
/api/connections -- and deleting a user, which cascades through it -- on every
database created before that commit. It was found by trying to delete a test
account, not by any test.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import Column, Integer, String, create_engine, inspect, text

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def engine(tmp_path):
    return create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")


def test_a_missing_column_is_added(engine, monkeypatch):
    from auth import schema_sync

    # A table that exists on disk without a column the model declares.
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)"))

    from sqlalchemy.orm import declarative_base

    Base = declarative_base()

    class Widget(Base):
        __tablename__ = "widgets"
        id = Column(Integer, primary_key=True)
        name = Column(String)
        colour = Column(String, nullable=True)      # added later

    monkeypatch.setattr(schema_sync, "sync", schema_sync.sync)
    import auth.models

    monkeypatch.setattr(auth.models, "Base", Base)

    applied = schema_sync.sync(engine)
    assert "widgets.colour" in applied

    on_disk = {c["name"] for c in inspect(engine).get_columns("widgets")}
    assert "colour" in on_disk


def test_running_twice_is_a_no_op(engine, monkeypatch):
    """Called on every startup, so the second run must do nothing."""
    from sqlalchemy.orm import declarative_base

    from auth import schema_sync

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE widgets (id INTEGER PRIMARY KEY)"))

    Base = declarative_base()

    class Widget(Base):
        __tablename__ = "widgets"
        id = Column(Integer, primary_key=True)
        colour = Column(String, nullable=True)

    import auth.models

    monkeypatch.setattr(auth.models, "Base", Base)

    assert schema_sync.sync(engine) == ["widgets.colour"]
    assert schema_sync.sync(engine) == [], "second run altered the table again"


def test_it_never_drops_or_renames(engine, monkeypatch):
    """
    Additive only. A column the model no longer declares is left alone --
    dropping it is destructive and needs a human decision about the data.
    """
    from sqlalchemy.orm import declarative_base

    from auth import schema_sync

    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE widgets (id INTEGER PRIMARY KEY, retired TEXT)"
        ))

    Base = declarative_base()

    class Widget(Base):
        __tablename__ = "widgets"
        id = Column(Integer, primary_key=True)
        # `retired` deliberately absent from the model

    import auth.models

    monkeypatch.setattr(auth.models, "Base", Base)

    schema_sync.sync(engine)
    on_disk = {c["name"] for c in inspect(engine).get_columns("widgets")}
    assert "retired" in on_disk, "sync dropped a column it no longer knows about"


def test_a_not_null_column_is_reported_not_forced(engine, monkeypatch, caplog):
    """
    NOT NULL with no default cannot be added to a table with rows. Guessing a
    backfill value is how you corrupt a column, so it is logged loudly and
    skipped.
    """
    from sqlalchemy.orm import declarative_base

    from auth import schema_sync

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE widgets (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO widgets (id) VALUES (1)"))

    Base = declarative_base()

    class Widget(Base):
        __tablename__ = "widgets"
        id = Column(Integer, primary_key=True)
        required = Column(String, nullable=False)

    import auth.models

    monkeypatch.setattr(auth.models, "Base", Base)

    with caplog.at_level("ERROR"):
        applied = schema_sync.sync(engine)

    assert "widgets.required" not in applied
    assert any("needs a migration" in r.message for r in caplog.records), (
        "an unaddable column was skipped silently"
    )


def test_init_db_runs_the_sync():
    """A sync nothing calls is decoration."""
    import ast

    source = (PROJECT_ROOT / "auth" / "db.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "init_db"
    )
    body = ast.get_source_segment(source, fn) or ""
    assert "sync(" in body, "init_db does not bring existing tables up to date"


def test_the_social_connection_budget_columns_are_declared():
    """
    The specific columns whose absence broke /api/connections. If they are
    dropped from the model, the dashboard's budget bars silently stop working.
    """
    from auth.models import SocialConnection

    declared = {c.name for c in SocialConnection.__table__.columns}
    for column in ("budget_day", "budget_requests_used", "budget_requests_cap",
                   "budget_posts_used", "budget_posts_cap"):
        assert column in declared


# --- the two silent failures that made login look broken --------------------

def test_the_seeder_says_loudly_when_no_admin_was_created():
    """
    hash_password rejects a short BOOTSTRAP_ADMIN_PASSWORD, and _seed_admin
    used to log one line and return -- leaving an empty user table, correctly
    set env vars, and no way to log in. Editing .env and restarting changed
    nothing, with the only clue lost in startup output.
    """
    import ast

    source = (PROJECT_ROOT / "auth" / "bootstrap.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_seed_admin"
    )
    body = ast.get_source_segment(source, fn) or ""

    assert "NOBODY CAN LOG IN" in body, (
        "a rejected bootstrap password does not announce itself"
    )
    assert "create_admin" in body, "the error does not say how to recover"


def test_the_seeder_explains_why_editing_the_password_does_nothing():
    """
    The seed guards on an EMPTY user table, so changing
    BOOTSTRAP_ADMIN_PASSWORD later cannot take effect. That is correct -- it
    stops a later edit minting a second admin -- but it is deeply confusing
    unless said out loud.
    """
    import ast

    source = (PROJECT_ROOT / "auth" / "bootstrap.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "_seed_admin"
    )
    body = ast.get_source_segment(source, fn) or ""

    assert "is ignored" in body and "--force" in body


def test_preflight_rejects_an_unusable_bootstrap_password(monkeypatch):
    """Present is not the same as usable."""
    from src import preflight

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "short")   # under the minimum
    preflight.reset()

    pf = preflight.run(force=True)
    failed = {c.key for c in pf.failures}
    assert "BOOTSTRAP_ADMIN_PASSWORD" in failed, (
        "a password too short to ever work is reported as fine"
    )
    preflight.reset()


def test_the_dashboard_does_not_block_forever_on_the_first_cycle():
    """
    Index.tsx blocked on LoadingScreen while status was 'initializing' with no
    upper bound. A cycle takes minutes and can stall entirely, so a user who
    had just signed in successfully sat on a spinner -- which reads exactly
    like a failed login.
    """
    index = PROJECT_ROOT.parent / "frontend" / "app" / "pages" / "Index.tsx"
    if not index.exists():
        pytest.skip("frontend not present")

    source = index.read_text(encoding="utf-8")
    assert "setTimeout" in source and "waitedLongEnough" in source, (
        "the loading screen has no time bound"
    )
    # And the empty dashboard must say which it is.
    assert "first collection cycle" in source.lower(), (
        "an empty dashboard does not distinguish itself from a broken one"
    )
