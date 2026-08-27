from pathlib import Path


def test_spectrum_db_axis_constants_and_padding_exist():
    app_js = Path("src/frontend/app.js").read_text()
    assert "const SPECTRUM_DB_MIN = -120;" in app_js
    assert "const SPECTRUM_DB_MAX = 0;" in app_js
    assert "const SPECTRUM_DB_STEP = 20;" in app_js
    assert "const leftPad = 46;" in app_js


def test_spectrum_draws_db_label_and_axis():
    app_js = Path("src/frontend/app.js").read_text()
    assert "specCtx.fillText('dB'" in app_js
    assert "for (let db = SPECTRUM_DB_MAX; db >= SPECTRUM_DB_MIN; db -= SPECTRUM_DB_STEP)" in app_js
