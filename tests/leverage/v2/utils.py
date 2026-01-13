import boa
import requests

from v2.constants import CRVUSD
from v2.settings import EXPLORER_TOKEN, EXPLORER_URL, ROUTER_1INCH_TOKEN


def get_contract_from_explorer(address: str):
    return boa.from_etherscan(
        address=address, name=address, uri=EXPLORER_URL, api_key=EXPLORER_TOKEN
    )


class Router1inch:
    def __init__(self, chain_id: int):
        self._chain_id = chain_id
        self._headers = {"Authorization": f"Bearer {ROUTER_1INCH_TOKEN}"}
        self._from = CRVUSD

    def get_rate(self, _to: str, amount: int):
        url = "https://api.1inch.dev/swap/v6.0/1/quote"
        params = {"src": self._from, "dst": _to, "amount": amount}
        resp = requests.get(url, headers=self._headers, params=params)
        return int(resp.json()["dstAmount"])
