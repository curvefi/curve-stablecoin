import boa
from tests.utils.deployers import (
    CONSTANTS_DEPLOYER,
    CONTROLLER_DEPLOYER,
    LENDING_FACTORY_DEPLOYER,
    VAULT_DEPLOYER,
)

from typing import Final

ZERO_ADDRESS: Final[str] = boa.eval("empty(address)")
MAX_UINT256: Final[int] = boa.eval("max_value(uint256)")
MAX_INT256: Final[int] = boa.eval("max_value(int256)")

# Constants from curve_stablecoin/constants.vy
WAD = CONSTANTS_DEPLOYER._constants.WAD
SWAD = CONSTANTS_DEPLOYER._constants.SWAD
DEAD_SHARES = CONSTANTS_DEPLOYER._constants.DEAD_SHARES
MIN_TICKS = CONSTANTS_DEPLOYER._constants.MIN_TICKS
MAX_TICKS = CONSTANTS_DEPLOYER._constants.MAX_TICKS
__version__ = CONSTANTS_DEPLOYER._constants.__version__

MAX_ORACLE_PRICE_DEVIATION = CONTROLLER_DEPLOYER._constants.MAX_ORACLE_PRICE_DEVIATION

MIN_A = LENDING_FACTORY_DEPLOYER._constants.MIN_A
MAX_A = LENDING_FACTORY_DEPLOYER._constants.MAX_A
MIN_FEE = LENDING_FACTORY_DEPLOYER._constants.MIN_FEE
MAX_FEE = LENDING_FACTORY_DEPLOYER._constants.MAX_FEE

MIN_ASSETS = VAULT_DEPLOYER._constants.MIN_ASSETS
