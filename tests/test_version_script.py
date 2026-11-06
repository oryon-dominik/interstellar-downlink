"""Contract tests for version.py — the script that mints every release number.

The number it computes becomes a git tag, and whatever deploys or installs a release
decides by the ordering of those tags: a silent change here changes what ships.

The `version_script` and `project_pyproject` fixtures locate the script and its pyproject.
Nothing reaches git or a clock — the tag list and the time both arrive through
injected callables.
"""

import re
import tomllib
from datetime import UTC, datetime
from zoneinfo import ZoneInfoNotFoundError

import pytest


def at(year: int, month: int):
    """A clock stuck at the first of a month, for the serial to be read against."""
    return lambda: datetime(year, month, 1, 12, 0, tzinfo=UTC)


def tags(*names: str):
    """A fixed tag list, standing in for what the repository carries."""
    return lambda: list(names)


# -- which names are ours --


def test_only_calver_names_are_parsed(version_script):
    """`latest` and whatever the old scheme left behind are not this script's to touch."""
    parsed = [match[0] for match in version_script.parsed(["2026.9.0", "0.10.0", "latest", "2026.9.0rc1"])]

    assert parsed == ["2026.9.0", "2026.9.0rc1"]


def test_a_two_digit_month_is_calver_too(version_script):
    assert [match[0] for match in version_script.parsed(["2026.10.3"])] == ["2026.10.3"]


# -- the serial --


def test_an_untagged_month_starts_at_zero(version_script):
    """The serial is one above the month's newest release, so an empty month starts at zero."""
    assert version_script.next_release(year=2026, month=9, names=["2026.8.4"]) == "2026.9.0"


def test_the_serial_counts_only_shipped_releases(version_script):
    """A candidate is a candidate *for* a serial — it does not consume one."""
    assert version_script.next_release(year=2026, month=9, names=["2026.9.0rc1", "2026.9.0rc2"]) == "2026.9.0"


def test_each_shipped_release_advances_the_serial(version_script):
    assert version_script.next_release(year=2026, month=9, names=["2026.9.0", "2026.9.1"]) == "2026.9.2"


def test_a_gap_in_the_month_does_not_pull_the_serial_back(version_script):
    """The ladder prunes older tags of the running month — the next one still lands above the newest."""
    survivors = ["2026.9.16", "2026.9.17", "2026.9.18"]

    assert version_script.next_release(year=2026, month=9, names=survivors) == "2026.9.19"


def test_a_release_after_the_ladder_prune_stays_above_it(version_script):
    """Prune, release, prune, release: a serial that counted the survivors restarted at 3 and was pruned itself."""
    names = [f"2026.9.{serial}" for serial in range(19)]
    for expected in ("2026.9.19", "2026.9.20"):
        names = [name for name in names if name not in version_script.expired(names, year=2026, month=9)]
        released = version_script.next_release(year=2026, month=9, names=names)

        assert released == expected
        names.append(released)


def test_another_month_does_not_count(version_script):
    assert version_script.next_release(year=2026, month=9, names=["2026.8.0", "2026.8.1"]) == "2026.9.0"


# -- candidates --


def test_the_first_candidate_of_a_series_is_one(version_script):
    assert version_script.marked(base="2026.9.0", marker="rc", names=[]) == "2026.9.0rc1"


def test_candidates_count_up_within_their_series(version_script):
    assert version_script.marked(base="2026.9.0", marker="rc", names=["2026.9.0rc1"]) == "2026.9.0rc2"


def test_a_candidate_of_another_release_does_not_count(version_script):
    assert version_script.marked(base="2026.9.1", marker="rc", names=["2026.9.0rc1"]) == "2026.9.1rc1"


# -- the modes the release workflow drives --

# The release workflow maps its `mode` input onto exactly these flags. The
# mapping is what a hand-started run picks from, so each one is pinned.
MODES = [
    ("rc", "rc"),
    ("alpha", "a"),
    ("beta", "b"),
    ("dev", "dev"),
    ("post", "post"),
]


@pytest.mark.parametrize(("flag", "marker"), MODES)
def test_each_mode_flag_stands_for_its_marker(version_script, flag, marker):
    arguments = version_script.parse_arguments([f"--{flag}", "--next"])

    assert version_script.requested_marker(arguments) == marker


def test_no_flag_means_a_final_release(version_script):
    """`default` in the workflow — the only mode that mints a tag autodeploy.py can see."""
    arguments = version_script.parse_arguments(["--next"])

    assert version_script.requested_marker(arguments) is None


def test_the_mode_flags_are_mutually_exclusive(version_script):
    with pytest.raises(SystemExit):
        version_script.parse_arguments(["--rc", "--beta"])


# -- what each mode actually computes --


def test_a_final_release_takes_the_next_serial(version_script):
    computed = version_script.version(marker=None, compute=True, list_tags=tags("2026.9.0"), clock=at(2026, 9))

    assert computed == "2026.9.1"


def test_a_candidate_marks_the_upcoming_release(version_script):
    computed = version_script.version(marker="rc", compute=True, list_tags=tags("2026.9.0"), clock=at(2026, 9))

    assert computed == "2026.9.1rc1"


def test_a_post_release_looks_backwards_at_what_shipped(version_script):
    """The one mode that repairs a version already out, instead of naming the next."""
    computed = version_script.version(
        marker="post", compute=True, list_tags=tags("2026.9.0", "2026.9.1"), clock=at(2026, 9)
    )

    assert computed == "2026.9.1post1"


def test_without_compute_the_declared_version_is_reported(version_script):
    """What `just info` and the deploy read — the number the checkout carries, not the next one."""
    declared = version_script.version(marker=None, list_tags=tags("2026.9.0"), clock=at(2026, 9))

    assert declared == version_script.read_version_from_pyproject()


# -- the month is a date a person reads --


def test_the_month_follows_the_declared_zone_not_the_runner(version_script, monkeypatch):
    """Between midnight and 02:00 Berlin time on the first, UTC still reports the month before."""
    monkeypatch.setenv("RELEASE_TIMEZONE", "Europe/Berlin")

    assert version_script.release_now().tzinfo is not None


def test_without_a_declared_zone_the_month_follows_the_local_clock(version_script, monkeypatch):
    """UTC is the floor, not the preference: an undeclared machine still dates by its own clock."""
    monkeypatch.delenv("RELEASE_TIMEZONE", raising=False)

    assert version_script.release_now().utcoffset() == datetime.now().astimezone().utcoffset()


def test_an_unresolvable_zone_stops_the_release(version_script, monkeypatch):
    """Dating a release into the wrong month is worse than not cutting one."""
    monkeypatch.setenv("RELEASE_TIMEZONE", "Mars/Olympus_Mons")

    with pytest.raises(ZoneInfoNotFoundError, match="Mars"):
        version_script.release_now()


# -- retention --

# A consumer pins a release tag, so a tag has to outlive the release that follows it.
# The ladder keeps the newest releases, then one per quarter, then one per year.


def test_the_three_newest_releases_stay(version_script):
    """The fourth is neither the newest of its quarter nor of its year."""
    dropped = version_script.expired(["2026.9.3", "2026.9.2", "2026.9.1", "2026.9.0"], year=2026, month=9)

    assert dropped == ["2026.9.0"]


def test_each_of_the_last_four_quarters_keeps_its_newest_release(version_script):
    names = ["2026.9.1", "2026.9.0", "2026.8.0", "2026.5.0", "2026.2.0", "2025.11.0", "2025.10.0", "2025.9.0"]

    dropped = version_script.expired(names, year=2026, month=9)

    assert dropped == ["2025.10.0", "2025.9.0"]


def test_each_of_the_last_ten_years_keeps_its_newest_release(version_script):
    names = [f"{year}.6.0" for year in range(2014, 2027)]

    dropped = version_script.expired(names, year=2026, month=9)

    assert dropped == ["2014.6.0", "2015.6.0", "2016.6.0"]


def test_a_post_release_is_a_release_not_a_candidate(version_script):
    """Its base shipped by definition — deleting it for that would drop the repair itself."""
    assert version_script.expired(["2026.9.0", "2026.9.0post1"], year=2026, month=9) == []


def test_a_candidate_expires_the_moment_its_release_ships(version_script):
    """2026.9.0 is out, so the candidates that were aiming at it have no reader left."""
    assert "2026.9.0rc1" in version_script.expired(["2026.9.0", "2026.9.0rc1"], year=2026, month=9)


def test_a_candidate_whose_release_is_not_out_survives_its_month(version_script):
    """Deleting it would restart the candidate count at 1 and collide with the tag it used."""
    assert version_script.expired(["2026.9.0", "2026.9.1rc1"], year=2026, month=9) == []


def test_a_candidate_expires_once_its_month_is_over(version_script):
    """A number from a past month is never minted again, so nothing can collide with it."""
    assert version_script.expired(["2026.9.0", "2026.8.1rc1"], year=2026, month=9) == ["2026.8.1rc1"]


def test_names_that_are_not_calver_are_never_deleted(version_script):
    """The old scheme and the asset tags are not this script's to prune."""
    assert version_script.expired(
        ["0.10.0", "latest", "2014.6.0", *[f"{year}.6.0" for year in range(2015, 2027)]], year=2026, month=9
    ) == ["2014.6.0", "2015.6.0", "2016.6.0"]


# -- one declaration, several readers --

# The release-tag shape is declared once, in [tool.git-cliff.git].tag_pattern,
# and every reader gets it from there. Copies drift apart; this guard keeps it one.

SCHEME_NAMES = ["2026.9.0", "2026.9.0rc2", "2026.9.1post1", "2026.10.3dev1", "2026.9.0a1", "2026.9.0b2"]
FOREIGN_NAMES = ["0.0.1", "0.10.0", "profile-pictures-latest", "team-avatars-latest", "latest"]


def test_the_script_reports_the_shape_the_project_declares(version_script, project_pyproject):
    """`--tag-pattern` is how a caller that cannot read TOML gets it."""
    declared = tomllib.loads(project_pyproject.read_text(encoding="utf-8"))

    assert version_script.declared_tag_pattern() == declared["tool"]["git-cliff"]["git"]["tag_pattern"]


@pytest.mark.parametrize("name", SCHEME_NAMES + FOREIGN_NAMES)
def test_the_declared_shape_and_the_parser_agree(version_script, name):
    """CALVER carries capture groups the config cannot express, so a test holds them equal.

    They cannot be one literal: the arithmetic above needs year, month, serial
    and marker as groups, and TOML has no way to name them. What can be
    guaranteed is that the two never disagree about what is a release.
    """
    by_config = bool(re.match(version_script.declared_tag_pattern(), name))
    by_parser = bool(version_script.CALVER.match(name))

    assert by_config == by_parser, f"{name}: config says {by_config}, parser says {by_parser}"


# -- no number twice --


def test_successive_releases_never_repeat_a_number(version_script):
    """Four runs in one month, each seeing what the ones before it cut."""
    minted = []
    for _ in range(4):
        number = version_script.version(marker=None, compute=True, list_tags=tags(*minted), clock=at(2026, 9))
        assert number not in minted, f"{number} was already cut"
        minted.append(number)

    assert minted == ["2026.9.0", "2026.9.1", "2026.9.2", "2026.9.3"]


def test_successive_candidates_never_repeat_a_number(version_script):
    """The candidate series counts up while the serial it aims at stays put."""
    minted = []
    for _ in range(3):
        number = version_script.version(marker="rc", compute=True, list_tags=tags(*minted), clock=at(2026, 9))
        assert number not in minted, f"{number} was already cut"
        minted.append(number)

    assert minted == ["2026.9.0rc1", "2026.9.0rc2", "2026.9.0rc3"]


def test_a_month_boundary_does_not_reuse_the_previous_serial(version_script):
    """September's numbers do not constrain October's, and cannot collide with them."""
    september = version_script.version(
        marker=None, compute=True, list_tags=tags("2026.9.0", "2026.9.1"), clock=at(2026, 9)
    )
    october = version_script.version(
        marker=None, compute=True, list_tags=tags("2026.9.0", "2026.9.1"), clock=at(2026, 10)
    )

    assert september == "2026.9.2"
    assert october == "2026.10.0"
