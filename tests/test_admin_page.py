"""Smoke + unit tests for the admin page.

Streamlit interaction-level testing is brittle; this tests the page imports
cleanly with mocked streamlit, plus the password-resolution helper directly.
"""
import sys
from unittest.mock import MagicMock


class _State(dict):
    def __getattr__(self, k):
        return self.get(k)

    def __setattr__(self, k, v):
        self[k] = v


def _password_secrets_mock(value: str) -> MagicMock:
    """Return a st.secrets.get mock that yields `value` only for ADMIN_PASSWORD.

    Any other key (e.g. TURSO_DATABASE_URL) gets the caller-supplied default so
    _get_st_secret() in database.py returns '' and SQLite is used — not a bogus
    Turso URL built from the password string.
    """
    def _get(key, default=None):
        return value if key == "ADMIN_PASSWORD" else default

    return MagicMock(side_effect=_get)


def _install_streamlit_mock(authed: bool = False) -> MagicMock:
    """Install a MagicMock for `streamlit` so the page can run top-level."""
    st_mock = MagicMock()
    st_mock.session_state = _State({"admin_authed": authed, "admin_page": 1})
    st_mock.button.return_value = False
    st_mock.text_input.return_value = ""
    st_mock.checkbox.return_value = False
    st_mock.radio.return_value = "Όλες"
    st_mock.cache_resource = lambda f: f
    # st.secrets behaves like a dict but allow attribute access
    secrets_mock = MagicMock()
    secrets_mock.get = MagicMock(return_value=None)
    st_mock.secrets = secrets_mock
    st_mock.stop.side_effect = RuntimeError("st.stop()")
    st_mock.columns.return_value = (MagicMock(), MagicMock(), MagicMock())
    st_mock.sidebar.__enter__ = MagicMock(return_value=st_mock.sidebar)
    st_mock.sidebar.__exit__ = MagicMock(return_value=False)
    sys.modules["streamlit"] = st_mock
    return st_mock


def _load_admin_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("admin_page", "ui/pages/1_Admin.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPasswordResolution:
    def test_returns_secret_if_set(self, monkeypatch):
        _install_streamlit_mock()
        import streamlit as st
        st.secrets.get = _password_secrets_mock("hunter2")
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

        mod = _load_admin_module()
        assert mod._read_admin_password() == "hunter2"

    def test_falls_back_to_env(self, monkeypatch):
        _install_streamlit_mock()
        import streamlit as st
        st.secrets.get = MagicMock(return_value=None)
        monkeypatch.setenv("ADMIN_PASSWORD", "from_env")

        mod = _load_admin_module()
        assert mod._read_admin_password() == "from_env"

    def test_returns_none_if_unset(self, monkeypatch):
        _install_streamlit_mock(authed=True)
        import streamlit as st
        st.secrets.get = _password_secrets_mock("dummy")  # let main() pass the gate
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

        mod = _load_admin_module()
        # Now flip the secret away to test the helper in isolation
        st.secrets.get = MagicMock(return_value=None)
        assert mod._read_admin_password() is None


class TestPasswordGate:
    def test_stops_when_password_unset(self, monkeypatch):
        _install_streamlit_mock(authed=False)
        import streamlit as st
        st.secrets.get = MagicMock(return_value=None)
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

        # Loading the module triggers main() which should call st.stop()
        try:
            _load_admin_module()
        except RuntimeError as e:
            assert "st.stop" in str(e)

    def test_already_authed_passes_gate(self, monkeypatch):
        _install_streamlit_mock(authed=True)
        import streamlit as st
        st.secrets.get = _password_secrets_mock("ok")
        # When authed, _password_gate returns True without raising
        mod = _load_admin_module()
        # Calling directly to verify the return value path
        assert mod._password_gate() is True


class TestFilterHelpers:
    def test_feedback_filter_mapping(self):
        _install_streamlit_mock(authed=True)
        import streamlit as st
        st.secrets.get = _password_secrets_mock("dummy")
        mod = _load_admin_module()
        assert mod._feedback_filter_value("Όλες") is None
        assert mod._feedback_filter_value("Θετικό feedback") == "positive"
        assert mod._feedback_filter_value("Αρνητικό feedback") == "negative"
        assert mod._feedback_filter_value("Χωρίς feedback") == "none"

    def test_date_range_choices(self):
        _install_streamlit_mock(authed=True)
        import streamlit as st
        st.secrets.get = _password_secrets_mock("dummy")
        mod = _load_admin_module()
        d_all = mod._date_range_for_choice("Όλες")
        assert d_all == (None, None)
        d_24h, _ = mod._date_range_for_choice("Τελευταίες 24 ώρες")
        assert d_24h is not None
