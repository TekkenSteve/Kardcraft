from kardcraft.utils import file_storage_client
from kardcraft.utils.logger import logger as app_logger


def test_file_storage_client_uses_bound_logger() -> None:
    assert file_storage_client.logger is app_logger
