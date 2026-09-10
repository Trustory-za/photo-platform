"""Regression tests for api._normalize_route_segment.

The /events/{slug} route must safely percent-decode an incoming path
segment before comparing it against a freshly computed slug, and must
never raise on malformed percent-encoding.
"""

from api import _normalize_route_segment


def test_decodes_percent_encoded_unicode():
    assert _normalize_route_segment("caf%c3%a9") == "café"


def test_decodes_encoded_percent_sign():
    assert _normalize_route_segment("100%25-off") == "100%-off"


def test_decodes_multibyte_unicode_symbol():
    assert _normalize_route_segment("%e2%98%83") == "☃"  # snowman


def test_malformed_percent_sequence_does_not_crash():
    # "%zz" is not a valid hex escape — must be left as-is, never raise.
    assert _normalize_route_segment("abc%zz") == "abc%zz"


def test_lone_invalid_percent_byte_does_not_crash():
    # "%80" alone is not valid UTF-8 — must not raise UnicodeDecodeError.
    result = _normalize_route_segment("%80")
    assert isinstance(result, str)


def test_plain_ascii_segment_is_unchanged():
    assert _normalize_route_segment("plain-slug-1") == "plain-slug-1"
