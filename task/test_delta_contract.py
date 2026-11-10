"""Public checks for task/CONTRACT.md; no merge implementation is included.

The small, synthetic manifests exercise client state restoration. They do not
model server-side skip-boundary selection or contain downloadable media.
These checks cover representative cases, not every documented input boundary.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
import pickle

import pytest

import m3u8


FIXTURES = Path(__file__).parent / "fixtures"
URI = "https://media.invalid/live/index.m3u8"
BASE = "https://media.invalid/live/"
EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def load_text(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def pair(previous_text=None, update_text=None):
    return (
        m3u8.loads(previous_text or load_text("window.previous.m3u8"), uri=URI),
        m3u8.loads(update_text or load_text("window.delta.m3u8"), uri=URI),
    )


def api():
    assert callable(getattr(m3u8, "apply_delta", None)), "public apply_delta is missing"
    error = getattr(m3u8, "DeltaUpdateError", None)
    assert isinstance(error, type) and issubclass(error, ValueError)
    return m3u8.apply_delta, error


def frozen(value):
    """Observe a complete input object graph before and after a call."""
    return pickle.dumps(value, protocol=5)


def mutable_ids(value, seen=None):
    """Collect mutable containers and model objects, including nested data."""
    if seen is None:
        seen = set()
    if id(value) in seen:
        return set()
    seen.add(id(value))
    result = set()
    if isinstance(value, dict):
        result.add(id(value))
        children = list(value.keys()) + list(value.values())
    elif isinstance(value, (list, set)):
        result.add(id(value))
        children = list(value)
    elif isinstance(value, tuple):
        children = value
    elif type(value).__module__.startswith("m3u8.") and hasattr(value, "__dict__"):
        result.add(id(value))
        children = [vars(value)]
    else:
        children = ()
    for child in children:
        result.update(mutable_ids(child, seen))
    return result


def location(value):
    if value is None or not value.uri:
        return None
    return value.absolute_uri if value.base_uri else value.uri


def key_state(key):
    if key is None:
        return ("NONE", None, None, "identity", None)
    return (
        key.method,
        location(key),
        key.iv,
        key.keyformat or "identity",
        key.keyformatversions,
    )


def map_state(section):
    return None if section is None else (location(section), section.byterange)


def pdt(item):
    return item.current_program_date_time or item.program_date_time


def segment_view(playlist):
    """Read effective byte ranges and state from one standalone result.

    This is an observer only: it has no previous playlist and cannot restore
    missing context or perform a delta merge.
    """
    rows = []
    previous_range = None
    previous_uri = None
    dsn = playlist.discontinuity_sequence or 0
    for segment in playlist.segments:
        dsn += bool(segment.discontinuity)
        actual_range = None
        if segment.byterange:
            pieces = segment.byterange.split("@")
            length = int(pieces[0])
            if len(pieces) == 2:
                offset = int(pieces[1])
            else:
                assert previous_range is not None, "standalone range lost its offset"
                assert previous_uri == location(segment)
                offset = previous_range[0] + previous_range[1]
            actual_range = (offset, length)
        if segment.uri:
            previous_range = actual_range
            previous_uri = location(segment)
        rows.append(
            (
                segment.media_sequence,
                location(segment),
                segment.duration,
                actual_range,
                key_state(segment.key),
                map_state(segment.init_section),
                dsn,
                bool(segment.gap_tag),
                pdt(segment),
                tuple(
                    (
                        location(part), part.duration,
                        part.byterange.strip('"') if part.byterange else None,
                        part.independent, part.gap, pdt(part),
                    )
                    for part in segment.parts
                ),
            )
        )
    return rows


def merge_unchanged(previous, update):
    apply_delta, _ = api()
    before = frozen((previous, update))
    result = apply_delta(previous, update)
    assert isinstance(result, m3u8.M3U8)
    assert frozen((previous, update)) == before
    assert not mutable_ids(result).intersection(mutable_ids((previous, update)))
    return result


def assert_error(previous, update, reason):
    apply_delta, error = api()
    before = frozen((previous, update))
    with pytest.raises(error) as caught:
        apply_delta(previous, update)
    assert caught.value.reason == reason
    assert frozen((previous, update)) == before


def test_window_state_and_partial_completion():
    previous, update = pair()
    result = merge_unchanged(previous, update)
    rows = segment_view(result)
    assert result.media_sequence == 102
    assert not result.skip
    assert [row[0] for row in rows] == list(range(102, 108))
    assert [row[1] for row in rows] == [
        BASE + "media/a.mp4", BASE + "media/b.mp4", BASE + "media/b.mp4",
        BASE + "media/b.mp4", BASE + "media/c.mp4", None,
    ]
    assert [row[2] for row in rows] == [6, 6, 6, 6, 6, None]
    assert [row[3] for row in rows] == [
        (200, 100), (0, 150), (150, 150), (300, 150), (0, 200), None,
    ]
    assert [row[4][0] for row in rows] == ["AES-128"] * 4 + ["NONE"] * 2
    assert [row[4][1] for row in rows] == [
        BASE + "keys/a.key", *([BASE + "keys/b.key"] * 3), None, None,
    ]
    assert rows[0][4][2] == "0x00000000000000000000000000000064"
    assert rows[3][4][2] == "0x00000000000000000000000000000067"
    assert [row[5] for row in rows] == [
        (BASE + "init/a.mp4", "64@0"),
        *([(BASE + "init/b.mp4", "64@0")] * 3),
        *([(BASE + "init/c.mp4", "64@0")] * 2),
    ]
    assert [row[6] for row in rows] == [7, 8, 8, 8, 8, 8]
    assert [row[8] for row in rows] == [
        EPOCH + timedelta(seconds=value) for value in (12, 60, 66, 72, 78, 84)
    ]
    assert [len(row[9]) for row in rows] == [0, 0, 0, 0, 2, 2]
    assert [part[5] for part in rows[4][9]] == [
        EPOCH + timedelta(seconds=78), EPOCH + timedelta(seconds=81),
    ]
    assert [part[5] for part in rows[5][9]] == [
        EPOCH + timedelta(seconds=84), EPOCH + timedelta(seconds=87),
    ]
    assert rows[5][9][0][:5] == (BASE + "parts/107.mp4", 3, "10@0", "YES", None)
    assert rows[5][9][1][:5] == (BASE + "parts/107.mp4", 3, "10@10", None, "YES")
    assert result.segments[3].title == "105 updated title"


def test_metadata_indexes_and_data_reconstruction():
    previous, update = pair()
    result = merge_unchanged(previous, update)
    assert result.version == 10
    assert result.target_duration == 6
    assert result.part_inf.part_target == 3
    assert result.server_control.part_hold_back == 12
    assert location(result.preload_hint) == BASE + "parts/107.mp4"
    assert result.preload_hint.byterange_start == 20
    assert result.rendition_reports[0].last_msn == 107
    assert result.rendition_reports[0].last_part == 1
    assert [key_state(key)[0:2] for key in result.keys] == [
        ("AES-128", BASE + "keys/a.key"),
        ("AES-128", BASE + "keys/b.key"),
        ("NONE", None),
    ]
    assert [map_state(item) for item in result.segment_map] == [
        (BASE + "init/a.mp4", "64@0"),
        (BASE + "init/b.mp4", "64@0"),
        (BASE + "init/c.mp4", "64@0"),
    ]
    assert all(isinstance(uri, str) for uri in result.files)
    assert [urljoin(BASE, uri) for uri in result.files] == [
        BASE + uri for uri in (
            "keys/a.key", "keys/b.key", "media/a.mp4", "media/b.mp4",
            "media/b.mp4", "media/b.mp4", "media/c.mp4",
        )
    ]
    reconstructed = m3u8.M3U8(base_uri=result.base_uri)
    reconstructed.data = deepcopy(result.data)
    reconstructed._initialize_attributes()
    assert segment_view(reconstructed) == segment_view(result)
    assert reconstructed.files == result.files
    assert not reconstructed.skip


def test_roundtrip_is_standalone_and_does_not_double_count_parts():
    result = merge_unchanged(*pair())
    text = result.dumps(timespec="microseconds")
    assert "#EXT-X-SKIP:" not in text
    assert text.count("#EXTINF:") == 5
    assert text.count("#EXT-X-PART:") == 4
    restored = m3u8.loads(text, uri=URI)
    assert segment_view(restored) == segment_view(result)


def test_repeated_delta_is_idempotent_and_independent():
    previous, update = pair()
    once = merge_unchanged(previous, update)
    twice = merge_unchanged(once, update)
    assert segment_view(twice) == segment_view(once)
    assert [urljoin(BASE, uri) for uri in twice.files] == [
        urljoin(BASE, uri) for uri in once.files
    ]


def test_missing_skipped_history_is_atomic():
    text = load_text("window.previous.m3u8")
    header = text.split("#EXT-X-KEY:", 1)[0].replace(
        "#EXT-X-MEDIA-SEQUENCE:100", "#EXT-X-MEDIA-SEQUENCE:103"
    )
    previous_text = header + text[text.index("#EXT-X-DISCONTINUITY\n"):]
    assert_error(*pair(previous_text=previous_text), "missing-history")


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("#EXTINF:6,105 updated title", "#EXTINF:5,105 updated title"),
        ("#EXT-X-BYTERANGE:150\nmedia/b.mp4", "#EXT-X-BYTERANGE:150@301\nmedia/b.mp4"),
        ("#EXT-X-DISCONTINUITY-SEQUENCE:7", "#EXT-X-DISCONTINUITY-SEQUENCE:8"),
    ],
)
def test_overlapping_complete_state_conflict_is_atomic(old, new):
    update_text = load_text("window.delta.m3u8").replace(old, new)
    assert_error(*pair(update_text=update_text), "conflict")


def test_negative_skip_is_invalid():
    update_text = load_text("window.delta.m3u8").replace(
        "SKIPPED-SEGMENTS=3", "SKIPPED-SEGMENTS=-1"
    )
    assert_error(*pair(update_text=update_text), "invalid-update")


@pytest.mark.parametrize("with_skip", [False, True])
def test_full_replacement_does_not_inherit_old_key_map_or_time(with_skip):
    update_text = (
        "#EXTM3U\n#EXT-X-VERSION:9\n#EXT-X-TARGETDURATION:6\n"
        "#EXT-X-MEDIA-SEQUENCE:200\n"
        + ("#EXT-X-SKIP:SKIPPED-SEGMENTS=0\n" if with_skip else "")
        + "#EXTINF:6,\nplain.ts\n#EXT-X-ENDLIST\n"
    )
    result = merge_unchanged(*pair(update_text=update_text))
    assert result.media_sequence == 200
    assert len(result.segments) == 1
    assert location(result.segments[0]) == BASE + "plain.ts"
    assert key_state(result.segments[0].key)[0] == "NONE"
    assert result.segments[0].init_section is None
    assert pdt(result.segments[0]) is None
    assert result.is_endlist
    assert not result.skip


@pytest.mark.parametrize("case", ["base", "previous-skip", "master", "daterange", "keyformat"])
def test_unsupported_inputs_are_atomic(case):
    previous, update = pair()
    if case == "base":
        update = m3u8.loads(load_text("window.delta.m3u8"), uri="https://other.invalid/index.m3u8")
    elif case == "previous-skip":
        previous = m3u8.loads(load_text("window.delta.m3u8"), uri=URI)
    elif case == "master":
        update = m3u8.loads("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nchild.m3u8\n", uri=URI)
    elif case == "daterange":
        text = load_text("window.previous.m3u8").replace(
            "#EXTINF:6,100",
            '#EXT-X-DATERANGE:ID="event",START-DATE="2026-01-01T00:00:00+00:00"\n#EXTINF:6,100',
        )
        previous = m3u8.loads(text, uri=URI)
    else:
        text = load_text("window.previous.m3u8").replace(
            'URI="keys/a.key"', 'URI="keys/a.key",KEYFORMAT="custom"'
        )
        previous = m3u8.loads(text, uri=URI)
    assert_error(previous, update, "unsupported")
