"""Compute the version the release pipeline stamps into pyproject.toml and the tag.

The release workflow maps its `mode` input onto the flags below. Contract tests
pin the modes — a change here changes what gets released.

The scheme is CalVer `YYYY.M.serial`. The serial is one above the newest
release the running month carries, so the first one is `.0` and every number
falls out of the tags rather than out of a stamped predecessor. That is what
makes it reproducible on any machine, monotone, and indifferent to rebases —
which neither an increment on the stamped version nor a commit count is. It
reads the newest tag, not the number of tags: the ladder prunes older releases
of the running month, and a count of the survivors would run backwards.
"""

import argparse
import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


CALVER = re.compile(r"^(?P<year>\d{4})\.(?P<month>\d{1,2})\.(?P<serial>\d+)(?:(?P<marker>a|b|rc|post|dev)\d+)?$")
# The retention ladder: the newest releases, then the newest of each recent quarter and year.
KEEP_LATEST = 3
KEEP_QUARTERS = 4
KEEP_YEARS = 10
# Markers that aim at a release not yet shipped. A post release is a release of its own.
CANDIDATES = {"a", "b", "rc", "dev"}


def git_executable() -> str:
    """Resolve git's full path, so argv[0] never depends on PATH order."""
    found = shutil.which("git")
    if found is None:
        raise FileNotFoundError("git is not reachable, so the release series cannot be read from the tags")
    return found


def read_tags() -> list[str]:
    """List every tag in the repository — the source of the release series."""
    completed = subprocess.run(  # noqa: S603 — fixed argument vector, resolved executable, no shell
        [git_executable(), "tag", "--list"],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.split()


def release_now() -> datetime:
    """Return the current time in the zone that decides the release month.

    Which month a release belongs to is a date a person reads, so it follows the
    declared zone and not the runner's clock: in the first hours of a month, UTC
    still reports the month before.

    `RELEASE_TIMEZONE` is the runner's declaration; without one the local clock
    decides, and UTC is only the floor a machine without a zone reports. A name
    that does not resolve stops the release instead of
    dating it into the wrong month. The environment is read through `os` rather
    than `environs`: the release script runs against the default dependency set,
    and pulling a configuration library into a package's runtime to read one
    optional variable is the wrong trade.
    """
    declared = os.environ.get("RELEASE_TIMEZONE")
    return datetime.now().astimezone() if declared is None else datetime.now(ZoneInfo(declared))


def project_pyproject() -> Path:
    """Find the project's pyproject, wherever its layout puts it.

    It sits in the root or under `application/`.
    Deriving it from the tree beats hardcoding one shape in every copy of this
    script — the same derivation `just audit` uses.
    """
    root = Path.cwd()
    for candidate in (root / "pyproject.toml", root / "application" / "pyproject.toml"):
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(f"no pyproject.toml in {root} or its application directory")


def read_version_from_pyproject() -> str | None:
    """Return the version the project declares.

    Raises ValueError when the pyproject cannot be read or parsed.
    """
    pyproject = project_pyproject()
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"Error reading version from {pyproject=}: {error}") from error

    return data.get("project", {}).get("version")


def parsed(names: Iterable[str]) -> list[re.Match]:
    """Keep the names that read as CalVer, in order — the rest is not ours."""
    return [match for name in names if (match := CALVER.match(name))]


def of_month(names: Iterable[str], *, year: int, month: int) -> list[re.Match]:
    """Keep the parsed tags that belong to one month."""
    return [match for match in parsed(names) if int(match["year"]) == year and int(match["month"]) == month]


def next_release(*, year: int, month: int, names: Iterable[str]) -> str:
    """Return the number the next release of that month gets.

    One above the month's newest final release; an untagged month starts at 0.
    Candidates do not consume a number — an rc is a candidate *for* the serial
    it names.
    """
    serials = [int(match["serial"]) for match in of_month(names, year=year, month=month) if match["marker"] is None]
    return f"{year}.{month}.{max(serials, default=-1) + 1}"


def marked(*, base: str, marker: str, names: Iterable[str]) -> str:
    """Append the next marker of its series to `base`; the first is 1."""
    prefix = f"{base}{marker}"
    counted = sum(1 for name in names if CALVER.match(name) and name.startswith(prefix))
    return f"{prefix}{counted + 1}"


def latest_release(names: Iterable[str]) -> str | None:
    """Return the highest final CalVer tag, or None while nothing has shipped."""
    finals = [match for match in parsed(names) if match["marker"] is None]
    if not finals:
        return None

    newest = max(finals, key=lambda match: (int(match["year"]), int(match["month"]), int(match["serial"])))
    return newest[0]


def release_order(match: re.Match) -> tuple[int, int, int, int]:
    """Sort key for releases: year, month, serial, then the number of a post release."""
    post = int(match[0][match.end("marker") :]) if match["marker"] == "post" else 0
    return int(match["year"]), int(match["month"]), int(match["serial"]), post


def newest_per_period(releases: list[re.Match], *, period: Callable[[re.Match], tuple], count: int) -> set[str]:
    """The newest release of each of the `count` most recent periods that shipped one; `releases` runs newest first."""
    newest: dict[tuple, str] = {}
    for match in releases:
        newest.setdefault(period(match), match[0])
    return set(list(newest.values())[:count])


def expired(names: Iterable[str], *, year: int, month: int) -> list[str]:
    """List the CalVer tags the pipeline may delete, in the order given.

    A consumer pins a release tag, so releases stay on a ladder: the three newest,
    the newest of each of the last four quarters and of each of the last ten years
    that shipped one. A candidate expires once its release ships or its month is
    over — before that, deleting it would restart the candidate count at 1 and
    collide with the tag it already used.

    Tags that do not read as CalVer are never returned. `latest` and whatever the
    old scheme left behind are not the pipeline's to delete.
    """
    matches = parsed(names)
    releases = sorted(
        (match for match in matches if match["marker"] not in CANDIDATES), key=release_order, reverse=True
    )
    kept = {match[0] for match in releases[:KEEP_LATEST]}
    kept |= newest_per_period(
        releases, period=lambda match: (int(match["year"]), (int(match["month"]) - 1) // 3), count=KEEP_QUARTERS
    )
    kept |= newest_per_period(releases, period=lambda match: (int(match["year"]),), count=KEEP_YEARS)
    shipped = {match[0] for match in matches if match["marker"] is None}

    def is_expired(match: re.Match) -> bool:
        if match["marker"] not in CANDIDATES:
            return match[0] not in kept
        base = f"{match['year']}.{int(match['month'])}.{match['serial']}"
        return base in shipped or (int(match["year"]), int(match["month"])) < (year, month)

    return [match[0] for match in matches if is_expired(match)]


def version(
    *,
    marker: str | None,
    compute: bool = False,
    list_tags: Callable[[], list[str]] = read_tags,
    clock: Callable[[], datetime] = release_now,
) -> str:
    """Return the declared version, or the next one the tags call for.

    A post release is the one mode that looks backwards — it repairs a version
    that already shipped, so it marks the newest tag instead of the next number.
    Raises KeyError when the pyproject declares no version.
    """
    declared = read_version_from_pyproject()
    if declared is None:
        raise KeyError("Version key not found in pyproject.toml")

    if not compute:
        return declared

    names = list_tags()
    if marker == "post":
        return marked(base=latest_release(names) or declared, marker="post", names=names)

    now = clock()
    upcoming = next_release(year=now.year, month=now.month, names=names)
    return upcoming if marker is None else marked(base=upcoming, marker=marker, names=names)


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line the release workflow drives."""
    parser = argparse.ArgumentParser(description="Compute the release version (CalVer).")
    parser.add_argument(
        "--next",
        dest="compute",
        action="store_true",
        default=False,
        help="Compute the next version instead of reporting the declared one.",
    )

    parser.add_argument(
        "--expired",
        action="store_true",
        default=False,
        help="List the CalVer tags that fell off the retention ladder, one per line.",
    )

    parser.add_argument(
        "--tag-pattern",
        action="store_true",
        default=False,
        help="Print the release-tag shape this project declares, for a caller that has to match it.",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--rc", action="store_true", help="Mark the upcoming release as a candidate.")
    group.add_argument("--alpha", action="store_true", help="Mark the upcoming release as alpha.")
    group.add_argument("--beta", action="store_true", help="Mark the upcoming release as beta.")
    group.add_argument("--post", action="store_true", help="Mark a post release of what already shipped.")
    group.add_argument("--dev", action="store_true", help="Mark the upcoming release as a dev build.")

    return parser.parse_args(argv)


def requested_marker(arguments: argparse.Namespace) -> str | None:
    """Map the chosen mode flag to the PEP 440 marker it stands for."""
    match True:
        case arguments.rc:
            return "rc"
        case arguments.alpha:
            return "a"
        case arguments.beta:
            return "b"
        case arguments.post:
            return "post"
        case arguments.dev:
            return "dev"
        case _:
            return None


def declared_tag_pattern() -> str:
    """Read the release-tag shape declared in `[tool.git-cliff.git]`.

    One declaration, several readers: the changelog bounds its range with it, and
    anything else that has to match a release tag asks here rather than keeping
    another copy that drifts. Raises KeyError
    when nothing is declared.
    """
    data = tomllib.loads(project_pyproject().read_text(encoding="utf-8"))
    declared = data.get("tool", {}).get("git-cliff", {}).get("git", {}).get("tag_pattern")
    if declared is None:
        raise KeyError(
            "no tool.git-cliff.git.tag_pattern in pyproject.toml — nothing declares what a release tag looks like"
        )

    return declared


if __name__ == "__main__":
    arguments = parse_arguments()
    if arguments.tag_pattern:
        print(declared_tag_pattern())
    elif arguments.expired:
        now = release_now()
        for tag in expired(read_tags(), year=now.year, month=now.month):
            print(tag)
    else:
        print(version(marker=requested_marker(arguments), compute=arguments.compute))
