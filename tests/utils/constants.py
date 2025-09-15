import boa
from tests.utils.deployers import CONSTANTS_DEPLOYER, CONTROLLER_DEPLOYER

ZERO_ADDRESS = boa.eval("empty(address)")
MAX_UINT256 = boa.eval("max_value(uint256)")

# Constants from contracts/constants.vy
WAD = CONSTANTS_DEPLOYER._constants.WAD
SWAD = CONSTANTS_DEPLOYER._constants.SWAD

# Constants from Controller.vy
MAX_ORACLE_PRICE_DEVIATION = CONTROLLER_DEPLOYER._constants.MAX_ORACLE_PRICE_DEVIATION
