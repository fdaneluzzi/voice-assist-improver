import httpx
import pytest

from voice_assist_improver.backends import EchoBackend
from voice_assist_improver.config import Settings
from voice_assist_improver.ollama_api import create_app
from voice_assist_improver.store import Store


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", allowed_networks=("127.0.0.0/8", "10.0.0.0/24"), models=("default", "other"))


@pytest.fixture
def make_client(settings):
    """Build an HTTP test client with a chosen backend and caller IP; returns (client, store)."""
    stores = []

    def _make(backend=None, client_ip="127.0.0.1", **overrides):
        s = Settings(**{**settings.__dict__, **overrides})
        store = Store(s.data_dir / "test.sqlite3")
        stores.append(store)
        app = create_app(s, backend or EchoBackend(), store)
        transport = httpx.ASGITransport(app=app, client=(client_ip, 5555))
        return httpx.AsyncClient(transport=transport, base_url="http://app"), store

    yield _make
    for st in stores:
        st.close()
