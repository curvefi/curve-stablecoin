import boa
import pytest
from .settings import WEB3_PROVIDER_URL, EXPLORER_URL, EXPLORER_TOKEN


@pytest.fixture(autouse=True)
def boa_fork():
    assert WEB3_PROVIDER_URL is not None, "Provider url is not set, add WEB3_PROVIDER_URL param to env"
    boa.env.fork(url=WEB3_PROVIDER_URL)


@pytest.fixture(scope="module", autouse=True)
def stablecoin_aggregator():
    return boa.from_etherscan("0x18672b1b0c623a30089A280Ed9256379fb0E4E62", "AggregatorStablePrice", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)  # USD/crvUSD
