from streamlit.testing.v1 import AppTest


def test_dashboard_opens_without_errors():
    at = AppTest.from_file("../app.py", default_timeout=60).run()
    assert not at.exception
    for ticker in ("AIR", "BNP", "MT"):          # a full table, a bank, a partial report
        at.selectbox[0].set_value(ticker).run()
        assert not at.exception, ticker
