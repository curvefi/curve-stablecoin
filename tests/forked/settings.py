import os

WEB3_PROVIDER_URL = os.getenv("WEB3_PROVIDER_URL", "http://127.0.0.1:8545")
EXPLORER_URL = os.getenv("EXPLORER_URL", "https://api.etherscan.io/v2/api?chain_id=1")
EXPLORER_TOKEN = os.getenv("EXPLORER_TOKEN")
