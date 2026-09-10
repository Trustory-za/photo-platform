"""Regression tests for api.slugify_event_headline.

These pin down the exact slug format so GET /events and GET /events/{slug}
can never drift apart again, and so previously published slugs keep working.
"""

from api import slugify_event_headline


def test_preserves_exact_existing_slug_for_known_headline():
    """This is the load-bearing case: a slug already shared/linked
    externally must keep resolving after the helper is introduced."""
    headline = (
        "1st Class Series, Division 1: Flexbrands Knights v North West "
        "Dragons, Day 1"
    )
    expected = (
        "1st-class-series,-division-1-flexbrands-knights-v-north-west-"
        "dragons,-day-1"
    )
    assert slugify_event_headline(headline) == expected


def test_commas_and_colons():
    headline = "1st Class Series, Division 1: Flexbrands Knights v North West Dragons, Day 1"
    expected = "1st-class-series,-division-1-flexbrands-knights-v-north-west-dragons,-day-1"
    assert slugify_event_headline(headline) == expected


def test_apostrophes_and_quotes_are_stripped():
    headline = "St. Mary's \"Eagles\" vs O'Brien's Team"
    expected = "st.-marys-eagles-vs-obriens-team"
    assert slugify_event_headline(headline) == expected


def test_forward_and_backslashes_are_stripped():
    headline = "Match Day: Team A / Team B \\ Replay"
    expected = "match-day-team-a-team-b-replay"
    assert slugify_event_headline(headline) == expected


def test_ampersands_are_preserved():
    headline = "Cats & Dogs: The Rematch"
    expected = "cats-&-dogs-the-rematch"
    assert slugify_event_headline(headline) == expected


def test_repeated_spaces_and_hyphens_use_legacy_single_pass_collapse():
    """The legacy transform did a single non-recursive `.replace("--", "-")`
    pass, not a full regex collapse. Runs of 3+ hyphens therefore do NOT
    reduce to a single hyphen: 3 hyphens -> 2, 4 hyphens -> 2. This pins
    that exact (surprising) legacy behavior so published slugs relying on
    multi-hyphen runs keep resolving."""
    headline = "Semi   Final -- Replay"
    expected = "semi--final--replay"
    assert slugify_event_headline(headline) == expected


def test_triple_hyphen_run_reduces_to_two_not_one():
    """Direct pin of the single-pass `.replace("--", "-")` semantics on a
    literal run of 3 hyphens already present in the headline text (not
    produced by space substitution): non-overlapping left-to-right scan
    matches one pair, leaving 2 hyphens rather than fully collapsing to 1."""
    headline = "Round A---Round B"
    expected = "round-a--round-b"
    assert slugify_event_headline(headline) == expected


def test_percent_signs_are_preserved_literally():
    headline = "100% Charity Match: Round 2"
    expected = "100%-charity-match-round-2"
    assert slugify_event_headline(headline) == expected


def test_non_ascii_unicode_is_lowercased_and_preserved():
    headline = "Café Müller vs Røde Ørn: Ünïcode Cup"
    expected = "café-müller-vs-røde-ørn-ünïcode-cup"
    assert slugify_event_headline(headline) == expected


def test_empty_headline_returns_empty_string():
    assert slugify_event_headline("") == ""
