import time

import boa
import requests

from .constants import CRVUSD
from .settings import EXPLORER_TOKEN, EXPLORER_URL, ROUTER_1INCH_TOKEN


def get_contract_from_explorer(address: str):
    return boa.from_etherscan(
        address=address, name=address, uri=EXPLORER_URL, api_key=EXPLORER_TOKEN
    )


class Router1inch:
    def __init__(self, chain_id: int):
        self._chain_id = chain_id
        self._headers = {"Authorization": f"Bearer {ROUTER_1INCH_TOKEN}"}
        self._crvusd = CRVUSD

    def get_rate(self, _from: str, _to: str, amount: int):
        url = "https://api.1inch.dev/swap/v6.0/1/quote"
        params = {"src": _from, "dst": _to, "amount": amount}
        resp = requests.get(url, headers=self._headers, params=params)
        time.sleep(1)
        return int(resp.json()["dstAmount"])

    def get_rate_to_crvusd(self, _from: str, amount: int):
        return self.get_rate(_from, CRVUSD, amount)

    def get_rate_from_crvusd(self, _to: str, amount: int):
        return self.get_rate(CRVUSD, _to, amount)

    def get_calldata(self, _from: str, _to: str, amount: int, user: str) -> str:
        url = "https://api.1inch.dev/swap/v6.0/1/swap"
        params = {
            "src": _from,
            "dst": _to,
            "amount": amount,
            "from": user,
            "slippage": 0.1,
            "disableEstimate": True,
        }
        resp = requests.get(url, headers=self._headers, params=params)

        time.sleep(1)
        return resp.json()["tx"]["data"]
