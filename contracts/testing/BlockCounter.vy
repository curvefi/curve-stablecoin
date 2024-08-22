# @version 0.3.10

block_counter: public(uint256)
time_counter: public(uint256)
last_time: public(uint256)

@external
def __init__():
    self.block_counter = 1
    self.time_counter = 0
    self.last_time = block.timestamp

@external
def count(current_ts: uint256):
    assert current_ts == block.timestamp
    self.time_counter = self.time_counter + block.timestamp - self.last_time
    self.last_time = block.timestamp
