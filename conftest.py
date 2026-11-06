"""Project-wide pytest fixtures.

Fixture modules are registered as plugins rather than imported, so a test file
never has to import a fixture to use it.
"""

pytest_plugins = [
    "tests.fixtures.release",
    "tests.fixtures.django_project",
]
