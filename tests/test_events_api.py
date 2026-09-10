"""Regression tests for GET /events and GET /events/{slug}.

Guards against the two routes' slug logic drifting apart again, and
proves the /events/{slug} route safely handles percent-encoded and
Unicode slugs coming back from a browser.
"""

import asyncio
from urllib.parse import quote

import httpx

import api
import database
from api import slugify_event_headline
from tests.conftest import make_photo


def test_events_list_slug_matches_canonical_helper(client, monkeypatch):
    headline = (
        "1st Class Series, Division 1: Flexbrands Knights v North West "
        "Dragons, Day 1"
    )
    photos = [make_photo(id=1, headline=headline)]
    monkeypatch.setattr(database, "list_all_photos", lambda: photos)

    resp = client.get("/events")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["slug"] == slugify_event_headline(headline)


def test_get_event_photos_filters_by_slug(client, monkeypatch):
    photos = [
        make_photo(id=1, headline="Event One: Round 1"),
        make_photo(id=2, headline="Event Two: Round 1"),
    ]
    monkeypatch.setattr(database, "list_all_photos", lambda: photos)

    slug = slugify_event_headline("Event One: Round 1")
    resp = client.get(f"/events/{slug}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == 1


def test_list_then_detail_round_trip_returns_same_photos(client, monkeypatch):
    """The slug returned by GET /events must be directly usable against
    GET /events/{slug} and resolve to the same set of photos."""
    headline = "Café Müller vs Røde Ørn: Ünïcode Cup, Final"
    photos = [
        make_photo(id=1, headline=headline, filename="a.jpg"),
        make_photo(id=2, headline=headline, filename="b.jpg"),
        make_photo(id=3, headline="Unrelated Event"),
    ]
    monkeypatch.setattr(database, "list_all_photos", lambda: photos)

    list_resp = client.get("/events")
    assert list_resp.status_code == 200
    events = list_resp.json()
    matching = [e for e in events if e["headline"] == headline]
    assert len(matching) == 1
    slug = matching[0]["slug"]

    detail_resp = client.get(f"/events/{quote(slug, safe='')}")
    assert detail_resp.status_code == 200
    detail_photos = detail_resp.json()

    assert {p["id"] for p in detail_photos} == {1, 2}
    assert {p["filename"] for p in detail_photos} == {"a.jpg", "b.jpg"}


def test_percent_encoded_slug_segment_resolves(client, monkeypatch):
    headline = "100% Charity Match: Round 2"
    photos = [make_photo(id=7, headline=headline)]
    monkeypatch.setattr(database, "list_all_photos", lambda: photos)

    slug = slugify_event_headline(headline)
    resp = client.get(f"/events/{quote(slug, safe='')}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == 7


def test_unknown_slug_returns_empty_list(client, monkeypatch):
    monkeypatch.setattr(database, "list_all_photos", lambda: [make_photo(id=1)])

    resp = client.get("/events/does-not-exist")
    assert resp.status_code == 200
    assert resp.json() == []


def _assert_collision_pair_resolves_distinctly(monkeypatch, client, headline_a, headline_b):
    """Shared assertion for a pair of distinct headlines whose legacy
    `slugify_event_headline` bases collide. GET /events must emit two
    distinct deterministic slugs, and each slug must round-trip via
    GET /events/{slug} to only its own photo's id — never both."""
    photos = [
        make_photo(id=1, headline=headline_a, filename="a.jpg"),
        make_photo(id=2, headline=headline_b, filename="b.jpg"),
    ]
    monkeypatch.setattr(database, "list_all_photos", lambda: photos)

    # Sanity: the two headlines really do collide under the legacy helper —
    # otherwise this isn't testing the collision path at all.
    assert slugify_event_headline(headline_a) == slugify_event_headline(headline_b)

    list_resp = client.get("/events")
    assert list_resp.status_code == 200
    events = list_resp.json()
    assert len(events) == 2

    slugs_by_headline = {e["headline"]: e["slug"] for e in events}
    slug_a = slugs_by_headline[headline_a]
    slug_b = slugs_by_headline[headline_b]

    # Distinct, deterministic slugs — no duplicate slug emitted.
    assert slug_a != slug_b
    assert len({e["slug"] for e in events}) == 2

    # Each slug round-trips to only its own photo id.
    resp_a = client.get(f"/events/{quote(slug_a, safe='')}")
    assert resp_a.status_code == 200
    body_a = resp_a.json()
    assert {p["id"] for p in body_a} == {1}

    resp_b = client.get(f"/events/{quote(slug_b, safe='')}")
    assert resp_b.status_code == 200
    body_b = resp_b.json()
    assert {p["id"] for p in body_b} == {2}

    return slug_a, slug_b


def test_slash_stripping_collision_emits_distinct_slugs(client, monkeypatch):
    """'A/B' and 'AB' both reduce to the legacy base 'ab' once '/' is
    stripped — they must not merge into one event or share a slug."""
    _assert_collision_pair_resolves_distinctly(monkeypatch, client, "A/B", "AB")


def test_colon_stripping_collision_emits_distinct_slugs(client, monkeypatch):
    """'Match: Day' and 'Match Day' both reduce to 'match-day' once the
    colon is stripped and the space becomes a hyphen."""
    _assert_collision_pair_resolves_distinctly(monkeypatch, client, "Match: Day", "Match Day")


def test_apostrophe_stripping_collision_emits_distinct_slugs(client, monkeypatch):
    """\"O'Brien\" and 'OBrien' both reduce to 'obrien' once the
    apostrophe is stripped."""
    _assert_collision_pair_resolves_distinctly(monkeypatch, client, "O'Brien", "OBrien")


def test_repeated_spacing_collision_emits_distinct_slugs(client, monkeypatch):
    """'Semi  Final' (double space) and 'Semi-Final' both collapse to
    'semi-final' once repeated separators are collapsed to one hyphen."""
    _assert_collision_pair_resolves_distinctly(monkeypatch, client, "Semi  Final", "Semi-Final")


def test_collision_slug_assignment_is_order_independent(client, monkeypatch):
    """The slug assigned to a given headline must not depend on the order
    photos come back from the database — swapping the order of the two
    colliding photos must yield the exact same headline->slug mapping."""
    headline_a = "A/B"
    headline_b = "AB"

    photos_forward = [
        make_photo(id=1, headline=headline_a, filename="a.jpg"),
        make_photo(id=2, headline=headline_b, filename="b.jpg"),
    ]
    monkeypatch.setattr(database, "list_all_photos", lambda: photos_forward)
    forward_events = client.get("/events").json()
    forward_map = {e["headline"]: e["slug"] for e in forward_events}

    photos_reversed = [
        make_photo(id=2, headline=headline_b, filename="b.jpg"),
        make_photo(id=1, headline=headline_a, filename="a.jpg"),
    ]
    monkeypatch.setattr(database, "list_all_photos", lambda: photos_reversed)
    reversed_events = client.get("/events").json()
    reversed_map = {e["headline"]: e["slug"] for e in reversed_events}

    assert forward_map == reversed_map


def test_non_colliding_headline_keeps_exact_legacy_slug_alongside_collision(client, monkeypatch):
    """A third, non-colliding headline present in the same request must
    keep its exact legacy slug unchanged — only the colliding group gets
    suffixed."""
    collision_a = "A/B"
    collision_b = "AB"
    solo_headline = "Totally Unrelated Match"
    photos = [
        make_photo(id=1, headline=collision_a),
        make_photo(id=2, headline=collision_b),
        make_photo(id=3, headline=solo_headline),
    ]
    monkeypatch.setattr(database, "list_all_photos", lambda: photos)

    events = client.get("/events").json()
    solo_event = next(e for e in events if e["headline"] == solo_headline)
    assert solo_event["slug"] == slugify_event_headline(solo_headline)


def test_double_decoding_collision_returns_only_exact_raw_match(monkeypatch):
    """Two distinct headlines can produce canonical slugs where one is the
    once-decoded form of the other ('sale-%25-off' decodes to
    'sale-%-off'). A request whose ASGI-decoded path param is the literal
    raw canonical slug 'sale-%25-off' must match ONLY that headline —
    never both, via the once-decoded fallback candidate."""
    headline_exact = "Sale %25 Off"
    headline_collision = "Sale % Off"
    photos = [
        make_photo(id=1, headline=headline_exact),
        make_photo(id=2, headline=headline_collision),
    ]
    monkeypatch.setattr(database, "list_all_photos", lambda: photos)

    slug = slugify_event_headline(headline_exact)
    assert slug == "sale-%25-off"
    assert slugify_event_headline(headline_collision) == "sale-%-off"

    async def fetch():
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            return await ac.get(f"/events/{quote(slug, safe='')}")

    resp = asyncio.run(fetch())
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == 1


def test_generated_slug_never_collides_with_reserved_legacy_base(monkeypatch):
    """A generated collision slug (`base-<digest>`) must never coincide
    with another, unrelated headline's reserved non-colliding legacy base
    — even in the adversarial case where the digest happens to produce
    exactly that value. Forces the collision by controlling the digest
    for one specific headline via monkeypatched hashlib.sha256, leaving
    every other call to the real implementation."""
    from api import build_event_slug_map

    collision_a = "Match: Day"
    collision_b = "Match Day"
    assert (
        slugify_event_headline(collision_a)
        == slugify_event_headline(collision_b)
        == "match-day"
    )

    forced_digest = "deadbeef" * 8  # 64 hex chars, like a real sha256 hexdigest
    reserved_conflict_headline = "Match Day Deadbeefde"
    assert (
        slugify_event_headline(reserved_conflict_headline)
        == f"match-day-{forced_digest[:10]}"
    )

    real_sha256 = api.hashlib.sha256

    def fake_sha256(data):
        if data == collision_a.encode("utf-8"):
            class _Forced:
                def hexdigest(self):
                    return forced_digest

            return _Forced()
        return real_sha256(data)

    monkeypatch.setattr(api.hashlib, "sha256", fake_sha256)

    headlines = [collision_a, collision_b, reserved_conflict_headline]
    slug_map = build_event_slug_map(headlines)

    # All three headlines must resolve to distinct slugs.
    assert len(slug_map) == 3
    assert len(set(slug_map.values())) == 3

    # The untouched, non-colliding legacy base is preserved exactly.
    assert slug_map[reserved_conflict_headline] == f"match-day-{forced_digest[:10]}"

    # The colliding headline whose forced digest would have produced that
    # exact reserved slug must have been reassigned to something else.
    assert slug_map[collision_a] != f"match-day-{forced_digest[:10]}"

    # Deterministic / order-independent: reversing input order yields the
    # exact same headline -> slug mapping.
    reversed_map = build_event_slug_map(list(reversed(headlines)))
    assert reversed_map == slug_map


def test_slug_with_literal_percent_escape_round_trips(monkeypatch):
    """A headline containing literal '%2F' text yields a canonical slug
    with that literal text preserved (slugify only strips real '/').

    A well-behaved client percent-encodes the canonical slug for use in
    a URL path segment: '%' becomes '%25', so the literal text '%2f'
    is sent over the wire as '%252f'. A real ASGI server (uvicorn)
    percent-decodes the raw wire path exactly once before handing the
    segment to the route function, so the route receives
    'encoded-%2f-marker-...' — already equal to the canonical slug.
    Blindly unquoting that value again turns '%2f' into an actual '/'
    and breaks the lookup.

    This uses httpx's ASGITransport directly (single wire-accurate
    decode) rather than Starlette's TestClient/`client` fixture, which
    unquotes the path an extra time internally and would misrepresent
    real server behaviour for this exact edge case.
    """
    headline = "Encoded %2F Marker: Café"
    photos = [make_photo(id=9, headline=headline)]
    monkeypatch.setattr(database, "list_all_photos", lambda: photos)

    slug = slugify_event_headline(headline)
    assert "%2f" in slug  # sanity check: literal percent-escape text survived

    async def fetch():
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            return await ac.get(f"/events/{quote(slug, safe='')}")

    resp = asyncio.run(fetch())
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == 9
