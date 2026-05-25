"""Tests for the site-wide password gate in ui/streamlit_app.py."""
import sys
from unittest.mock import MagicMock


class _State(dict):
    def __getattr__(self, k):
        return self.get(k)

    def __setattr__(self, k, v):
        self[k] = v


def _install_streamlit_mock(session_state: dict | None = None) -> MagicMock:
    st_mock = MagicMock()
    st_mock.session_state = _State(session_state or {})
    st_mock.button.return_value = False
    # Login forms now use st.form + st.form_submit_button instead of st.button
    st_mock.form_submit_button.return_value = False
    st_mock.text_input.return_value = ""
    st_mock.cache_resource = lambda f: f
    secrets_mock = MagicMock()
    secrets_mock.get = MagicMock(return_value=None)
    st_mock.secrets = secrets_mock
    st_mock.stop.side_effect = RuntimeError("st.stop()")
    sys.modules["streamlit"] = st_mock
    return st_mock


def _stub_heavy_deps() -> None:
    # Force-replace these regardless of what's already in sys.modules so that
    # the app module always uses mocks (real modules loaded by earlier test files
    # would otherwise leak in when run as part of the full suite).
    for mod in [
        "extra_streamlit_components",
        "src.generation.answer_generator",
        "src.generation.claude_client",
        "src.generation.models",
        "src.observability.logger",
        "src.observability.models",
        "src.pipeline.qa_pipeline",
        "src.retrieval.retriever",
    ]:
        sys.modules[mod] = MagicMock()


def _load_app_module(raise_on_stop: bool = True):
    import importlib.util

    for key in list(sys.modules.keys()):
        if "streamlit_app" in key:
            del sys.modules[key]

    _stub_heavy_deps()

    spec = importlib.util.spec_from_file_location("streamlit_app", "ui/streamlit_app.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except RuntimeError:
        if raise_on_stop:
            raise
    return mod


class TestSiteGateNoPassword:
    def test_no_env_var_shows_error_and_stops(self, monkeypatch):
        st = _install_streamlit_mock()
        st.secrets.get = MagicMock(return_value=None)
        monkeypatch.delenv("SITE_PASSWORD", raising=False)

        # st.stop() fires during module-level main() when no password is configured
        try:
            _load_app_module(raise_on_stop=True)
            raise AssertionError("expected st.stop() to be raised")
        except RuntimeError as e:
            assert "st.stop" in str(e)
        st.error.assert_called()


class TestSiteGateAuthenticated:
    def test_already_authenticated_returns_true(self, monkeypatch):
        st = _install_streamlit_mock({"site_authenticated": True})
        monkeypatch.setenv("SITE_PASSWORD", "secret")

        mod = _load_app_module()
        # Reset mock call counts accumulated by module-level main() before testing
        st.reset_mock()

        result = mod.check_site_password()
        assert result is True
        # Gate UI must not have been rendered
        st.text_input.assert_not_called()

    def test_correct_password_sets_flag(self, monkeypatch):
        # Keep form_submit_button=False during module load so check_site_password()
        # doesn't auto-authenticate before our explicit call.
        st = _install_streamlit_mock()  # form_submit_button.return_value = False by default
        st.secrets.get = MagicMock(return_value=None)
        monkeypatch.setenv("SITE_PASSWORD", "secret")

        mod = _load_app_module()
        st.reset_mock()
        st.secrets.get = MagicMock(return_value=None)
        st.text_input.return_value = "secret"
        st.form_submit_button.return_value = True

        mod.check_site_password()

        assert st.session_state.get("site_authenticated") is True
        st.rerun.assert_called_once()

    def test_wrong_password_stays_unauthenticated(self, monkeypatch):
        st = _install_streamlit_mock()
        st.secrets.get = MagicMock(return_value=None)
        monkeypatch.setenv("SITE_PASSWORD", "secret")
        st.text_input.return_value = "wrong"
        st.form_submit_button.return_value = True

        mod = _load_app_module()
        st.reset_mock()
        st.text_input.return_value = "wrong"
        st.form_submit_button.return_value = True

        result = mod.check_site_password()

        assert result is False
        assert not st.session_state.get("site_authenticated")
        st.error.assert_called_once()

    def test_empty_password_stays_unauthenticated(self, monkeypatch):
        st = _install_streamlit_mock()
        st.secrets.get = MagicMock(return_value=None)
        monkeypatch.setenv("SITE_PASSWORD", "secret")
        st.text_input.return_value = ""
        st.form_submit_button.return_value = True

        mod = _load_app_module()
        st.reset_mock()
        st.text_input.return_value = ""
        st.form_submit_button.return_value = True

        result = mod.check_site_password()

        assert result is False
        assert not st.session_state.get("site_authenticated")

    def test_gate_renders_ui_when_unauthenticated(self, monkeypatch):
        st = _install_streamlit_mock()
        st.secrets.get = MagicMock(return_value=None)
        monkeypatch.setenv("SITE_PASSWORD", "secret")

        mod = _load_app_module()
        st.reset_mock()

        result = mod.check_site_password()

        assert result is False
        st.text_input.assert_called_once()
        st.form_submit_button.assert_called_once()

    def test_site_password_from_secrets_takes_precedence(self, monkeypatch):
        # Keep button=False during module load to prevent auto-authentication.
        st = _install_streamlit_mock()  # button.return_value = False by default
        st.secrets.get = MagicMock(return_value="from_secrets")
        monkeypatch.setenv("SITE_PASSWORD", "from_env")

        mod = _load_app_module()
        st.reset_mock()
        st.secrets.get = MagicMock(return_value="from_secrets")
        st.text_input.return_value = "from_secrets"
        st.form_submit_button.return_value = True

        mod.check_site_password()

        assert st.session_state.get("site_authenticated") is True


class TestGateIndependence:
    def test_site_authenticated_does_not_grant_admin_access(self, monkeypatch):
        """site_authenticated in session_state must NOT affect the admin gate."""
        # The admin gate checks admin_authed, not site_authenticated.
        st = _install_streamlit_mock({"site_authenticated": True, "admin_authed": False})
        st.secrets.get = MagicMock(return_value="admin_pass")
        monkeypatch.setenv("ADMIN_PASSWORD", "admin_pass")
        monkeypatch.delenv("SITE_PASSWORD", raising=False)
        st.button.return_value = False
        st.text_input.return_value = ""
        st.columns.return_value = (MagicMock(), MagicMock(), MagicMock())
        st.sidebar.__enter__ = MagicMock(return_value=st.sidebar)
        st.sidebar.__exit__ = MagicMock(return_value=False)

        import importlib.util
        for key in list(sys.modules.keys()):
            if "admin_page" in key:
                del sys.modules[key]

        spec = importlib.util.spec_from_file_location("admin_page", "ui/pages/1_Admin.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # site_authenticated=True but admin gate must NOT pass
        assert mod._password_gate() is False
