"""Regression tests for backward-compatible legacy alias resolution in
GET /events/{slug}.

Scenario: a headline is published solo, so its legacy base slug (e.g.
'ab') is also its canonical slug. Later a second headline is added whose
legacy base collides with the first (e.g. 'AB' also reduces to 'ab').
From then on GET /events emits hash-suffixed canonical slugs for the
whole collision group, but a previously published external link to the
old bare base slug must keep resolving -- to exactly the deterministic
legacy owner, never merged with the other colliding headline's photos.
"""

from urllib.parse import quote

import database
from api import build_event_slug_map, slugify_event_headline
from tests.conftest import make_photo


def test_legacy_base_alias_resolves_after_collision_set_grows(client, monkeypatch):
    headline_a = "A/B"
    headline_b = "AB"

    # Before "AB" exists, "A/B" alone owns the bare legacy slug "ab".
    solo_photos = [make_photo(id=1, headline=headline_a)]
    monkeypatch.setattr(database, "list_all_photos", lambda: solo_photos)
    solo_events = client.get("/events").json()
    published_slug = solo_events[0]["slug"]
    assert published_slug == "ab"

    # "AB" is added later -- the collision set grows.
    grown_photos = [
        make_photo(id=1, headline=headline_a, filename="a.jpg"),
        make_photo(id=2, headline=headline_b, filename="b.jpg"),
    ]
    monkeypatch.setattr(database, "list_all_photos", lambda: grown_photos)

    grown_events = client.get("/events").json()
    slugs = {e["slug"] for e in grown_events}
    # Canonical slugs are now both hash-suffixed -- "ab" itself is no
    # longer emitted as anyone's canonical slug.
    assert "ab" not in slugs

    # The previously published bare slug must still resolve -- as an
    # alias -- to exactly the deterministic legacy owner ("A/B"), never
    # an empty list.
    resp = client.get(f"/events/{published_slug}")
    assert resp.status_code == 200
    body = resp.json()
    assert {p["id"] for p in body} == {1}


def test_legacy_alias_never_merges_photos_from_distinct_events(client, monkeypatch):
    photos = [
        make_photo(id=1, headline="A/B", filename="a.jpg"),
        make_photo(id=2, headline="AB", filename="b.jpg"),
    ]
    monkeypatch.setattr(database, "list_all_photos", lambda: photos)

    resp = client.get("/events/ab")
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert len(ids) == 1  # never both merged together
    assert ids <= {1, 2}


def test_legacy_alias_owner_is_earliest_publisher_not_lexicographic(client, monkeypatch):
    """Inverse-order regression: 'AB' is published alone first (and so
    durably owns the earliest photo id under the shared legacy base
    'ab'). 'A/B' is added later with a later durable photo id. Even
    though 'A/B' sorts lexicographically before 'AB', ownership of the
    bare legacy slug must follow durable creation history (earliest
    persisted photo id), not headline text -- so the collider added
    later can never steal the slug an earlier headline already
    published."""
    headline_first = "AB"
    headline_later = "A/B"

    # "AB" alone owns the bare legacy slug "ab" -- published with photo id 1.
    solo_photos = [make_photo(id=1, headline=headline_first)]
    monkeypatch.setattr(database, "list_all_photos", lambda: solo_photos)
    solo_events = client.get("/events").json()
    published_slug = solo_events[0]["slug"]
    assert published_slug == "ab"

    # "A/B" is added later with a strictly later (higher) durable photo id.
    grown_photos = [
        make_photo(id=1, headline=headline_first, filename="ab.jpg"),
        make_photo(id=2, headline=headline_later, filename="a-b.jpg"),
    ]
    monkeypatch.setattr(database, "list_all_photos", lambda: grown_photos)

    grown_events = client.get("/events").json()
    slugs = {e["slug"] for e in grown_events}
    assert "ab" not in slugs

    # The bare slug must keep resolving to the ORIGINALLY published event
    # ("AB", id 1) -- exactly one event, never the later-added collider,
    # regardless of "A/B" sorting first lexicographically.
    resp = client.get(f"/events/{published_slug}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert {p["id"] for p in body} == {1}


def test_legacy_alias_owner_is_deterministic_regardless_of_input_order(client, monkeypatch):
    forward = [
        make_photo(id=1, headline="A/B", filename="a.jpg"),
        make_photo(id=2, headline="AB", filename="b.jpg"),
    ]
    monkeypatch.setattr(database, "list_all_photos", lambda: forward)
    forward_ids = {p["id"] for p in client.get("/events/ab").json()}

    reversed_photos = [
        make_photo(id=2, headline="AB", filename="b.jpg"),
        make_photo(id=1, headline="A/B", filename="a.jpg"),
    ]
    monkeypatch.setattr(database, "list_all_photos", lambda: reversed_photos)
    reversed_ids = {p["id"] for p in client.get("/events/ab").json()}

    assert forward_ids == reversed_ids == {1}


def test_empty_legacy_slug_round_trips_through_events_route(client, monkeypatch):
    """A headline whose legacy transform reduces to '' (e.g. only
    stripped punctuation) must still get a non-empty canonical slug so
    GET /events/{slug} can resolve it -- an empty path segment can never
    match the {slug} route."""
    headline = "/"
    assert slugify_event_headline(headline) == ""

    photos = [make_photo(id=5, headline=headline)]
    monkeypatch.setattr(database, "list_all_photos", lambda: photos)

    events = client.get("/events").json()
    assert len(events) == 1
    slug = events[0]["slug"]
    assert slug != ""

    resp = client.get(f"/events/{quote(slug, safe='')}")
    assert resp.status_code == 200
    body = resp.json()
    assert {p["id"] for p in body} == {5}


def test_legacy_alias_owner_handles_missing_or_non_integer_ids_defensively():
    """A photo record with a missing or non-integer `id` must never crash
    ownership resolution. Such a headline is treated as having no known
    creation time and ranks after every group member with a usable id,
    so a headline with a real (int-coercible) id always wins ownership
    over one with a broken/absent id, and the map is still built without
    raising."""
    from api import build_legacy_alias_map

    photos_good_id_wins = [
        {"id": None, "headline": "AB"},
        {"id": "3", "headline": "A/B"},
    ]
    alias_map = build_legacy_alias_map(photos_good_id_wins)
    assert alias_map["ab"] == "A/B"

    photos_missing_id_field = [
        {"headline": "AB"},
        {"id": "not-a-number", "headline": "A/B"},
    ]
    alias_map = build_legacy_alias_map(photos_missing_id_field)
    assert alias_map["ab"] == "A/B"

    # Neither headline has a usable id at all -- falls back to
    # deterministic lexicographic order rather than raising.
    photos_no_usable_ids = [
        {"id": None, "headline": "AB"},
        {"id": "nope", "headline": "A/B"},
    ]
    alias_map = build_legacy_alias_map(photos_no_usable_ids)
    assert alias_map["ab"] == "A/B"  # "A/B" < "AB" lexicographically


def test_pinned_legacy_slug_unaffected_when_not_colliding():
    """The exact pinned legacy slug required elsewhere must be completely
    unaffected by the alias/empty-slug handling introduced here, since
    it has no collision partner and its base is non-empty."""
    headline = (
        "1st Class Series, Division 1: Flexbrands Knights v North West "
        "Dragons, Day 1"
    )
    expected_slug = (
        "1st-class-series,-division-1-flexbrands-knights-v-north-west-"
        "dragons,-day-1"
    )
    slug_map = build_event_slug_map([headline])
    assert slug_map[headline] == expected_slug
