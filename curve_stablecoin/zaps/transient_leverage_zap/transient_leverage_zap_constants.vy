# pragma version 0.4.3

# Exchange calldata is handed straight to a zap and never travels through the
# controller, so it is not bounded by the controller's CALLDATA_MAX_SIZE - which
# aggregator routes regularly exceed.
EXCHANGE_CALLDATA_MAX_SIZE: constant(uint256) = 32 * 1000

# Size the transient zaps accept for the controller's callback `calldata` argument,
# which they do not use. Smallest usable value, so nothing can be routed through the
# controller by mistake.
CALLBACK_CALLDATA_MAX_SIZE: constant(uint256) = 32
