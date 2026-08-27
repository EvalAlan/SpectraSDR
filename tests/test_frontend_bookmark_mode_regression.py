from pathlib import Path


def test_mode_button_binding_is_scoped_to_real_mode_buttons():
    app_js = Path("src/frontend/app.js").read_text()
    assert "document.querySelectorAll('.mode-grid .mode-btn[data-mode]')" in app_js


def test_bookmark_mode_aliases_and_legacy_ranges_are_normalized():
    app_js = Path("src/frontend/app.js").read_text()
    assert "WFM" in app_js
    assert "NBFM" in app_js
    assert "530000" in app_js and "1710000" in app_js
    assert "108000000" in app_js and "137000000" in app_js
