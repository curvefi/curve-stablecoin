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

# Sentinel values used in `configure` methods.
# We use an arbitrary high value that is unlikely to be used as a real value (can't use zero address as it might be intentional)

# keccak("SKIP_CONFIG") in decimal
SKIP_CONFIG_UINT256: constant(uint256) = 34683848501677104821777960696933802007602333377339998839659032476042327981902
# Last 20 bytes of keccak("SKIP_CONFIG_ADDRESS"), used as a nonzero sentinel for address config params
SKIP_CONFIG_ADDRESS: constant(address) = 0xEE97C47b4665063dD362c127B31a2d463BDFf91c
