import json
from pathlib import Path


def _load_example_bookmarks():
    p = Path("src/backend/bookmarks.json.example")
    return json.loads(p.read_text())


def _stations_with_tag(data, tag_name):
    if isinstance(data, dict) and isinstance(data.get("bookmarks"), list):
        return [
            b for b in data["bookmarks"]
            if tag_name in (b.get("tags") or [])
        ]
    cat = next(c for c in data["categories"] if c.get("name") == tag_name)
    return cat.get("stations", [])


def test_am_radio_category_uses_am_mode():
    data = _load_example_bookmarks()
    am = _stations_with_tag(data, "AM Radio")
    assert am
    assert all((s.get("mode") or "").upper() == "AM" for s in am)


def test_airband_categories_use_am_mode():
    data = _load_example_bookmarks()
    airband = _stations_with_tag(data, "Airband")
    assert airband, "expected airband entries"
    assert all((s.get("mode") or "").upper() == "AM" for s in airband)
