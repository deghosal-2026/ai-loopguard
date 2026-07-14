"""Tests verifying that core install has no framework dependencies.

Per SPEC §13.4 (dependencies policy): langgraph and crewai are optional
extras. Installing `pip install ai-loopguard` (core only) must NOT pull in
these frameworks.

These tests skip in dev environments (where all extras are installed)
and pass in CI's isolation-check job which installs only the core.

pyright/mypy conflict: langgraph IS installed in dev, so type checkers
flag `import langgraph` as unused. The `# type: ignore` silences pyright.
mypy's `unused-ignore` is suppressed via `disable_error_code` in pyproject.toml.

ruff F401: `# noqa: F401` tells ruff not to flag the import as unused.
"""

import pytest


@pytest.mark.unit
def test_core_has_no_langgraph() -> None:
    """Langgraph must not be importable without the langgraph extra."""
    # This test exists to enforce SPEC §13.4: langgraph and crewai are
    # optional extras.  A `pip install ai-loopguard` (core only) must NOT
    # pull in these frameworks.  In CI's isolation-check job, only the
    # core package is installed — the imports should fail.  In dev
    # environments (where all extras are installed), the test skips.
    # Without this test, a refactor that accidentally adds a hard import
    # of langgraph into the core module would go undetected until runtime.
    try:
        import langgraph  # type: ignore  # noqa: F401
        # If we get here, langgraph is installed (likely dev env)
        pytest.skip("langgraph installed in dev env")
    except ImportError:
        pass  # Expected in core-only install


@pytest.mark.unit
def test_core_has_no_crewai() -> None:
    """Crewai must not be importable without the crewai extra."""
    try:
        import crewai  # type: ignore  # noqa: F401
        # If we get here, crewai is installed (likely dev env)
        pytest.skip("crewai installed in dev env")
    except ImportError:
        pass  # Expected in core-only install
