import pytest
from app import api as api_module  # noqa: F401


@pytest.fixture(autouse=True)
def reset_globals(tmp_path):
    from app import api
    api.set_data_dir(tmp_path)
    api.reset_last_action()
    yield
    api.reset_last_action()


def test_import():
    from app import api  # noqa: F401
