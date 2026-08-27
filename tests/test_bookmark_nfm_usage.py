import json
from pathlib import Path


def _load_example_bookmarks():
    p = Path("src/backend/bookmarks.json.example")
    return json.loads(p.read_text())


def _stations_with_tag(data, name):
    if isinstance(data, dict) and isinstance(data.get("bookmarks"), list):
        return [b for b in data["bookmarks"] if name in (b.get("tags") or [])]
    cat = next(c for c in data["categories"] if c.get("name") == name)
    return cat.get("stations", [])


def test_example_bookmarks_include_nfm_entries():
    data = _load_example_bookmarks()
    if isinstance(data, dict) and isinstance(data.get("bookmarks"), list):
        modes = [(b.get("mode") or "").upper() for b in data.get("bookmarks", [])]
    else:
        modes = [
            (s.get("mode") or "").upper()
            for c in data.get("categories", [])
            for s in c.get("stations", [])
        ]
    assert "NFM" in modes


def test_land_mobile_categories_default_to_nfm():
    data = _load_example_bookmarks()
    for name in ["Rail", "EMS/Fire/Police", "Weather", "GMRS", "HAM Radio - SKYWARN"]:
        stations = _stations_with_tag(data, name)
        assert stations
        assert all((s.get("mode") or "").upper() == "NFM" for s in stations)
