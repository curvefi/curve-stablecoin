__version__: constant(String[5]) = "2.0.0"
MAX_TICKS: constant(int256) = 50
MAX_TICKS_UINT: constant(uint256) = 50
MIN_TICKS: constant(int256) = 4
MIN_TICKS_UINT: constant(uint256) = 4
MAX_SKIP_TICKS: constant(int256) = 1024
MAX_SKIP_TICKS_UINT: constant(uint256) = 1024

DEAD_SHARES: constant(uint256) = 1000
WAD: constant(uint256) = 10**18
SWAD: constant(int256) = 10**18

CALLDATA_MAX_SIZE: constant(uint256) = 32 * 300
# keccak("SKIP_CONFIG") in decimal, we just needed a arbitrary high value that is unlikely to be used as a real value
SKIP_CONFIG: constant(uint256) = 34683848501677104821777960696933802007602333377339998839659032476042327981902