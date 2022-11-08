# @version 0.3.7
"""
@title Curve USD Stablecoin
@author CurveFi
"""


event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256

event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: uint256
