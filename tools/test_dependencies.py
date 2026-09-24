"""The dependency rule as a test, so CI enforces it."""

from check_dependencies import check


def test_dependency_direction_is_not_violated() -> None:
    violations = check()
    assert not violations, "Dependency direction violated:\n" + "\n".join(violations)
