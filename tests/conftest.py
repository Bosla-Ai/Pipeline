import os
import sys
from unittest.mock import MagicMock
import pytest

# Set socket timeout to 0 (integer string) so tests don't hang and fail/pass immediately
os.environ["SOCKET_WAIT_TIMEOUT"] = "0"

# Mock undetected_chromedriver at the module level before any tests run
mock_uc = MagicMock()
sys.modules["undetected_chromedriver"] = mock_uc


@pytest.fixture(scope="session", autouse=True)
def mock_chrome_driver():
    return mock_uc
