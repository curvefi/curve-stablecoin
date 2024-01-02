# @version 0.3.10
"""
@title SemiLog monetary policy
@notice Monetary policy to calculate borrow rates in lending markets depending on utilization.
        Calculated as:
        log(rate) = utilization * (log(rate_max) - log(rate_min)) + log(rate_min)
        e.g.
        rate = rate_min * (rate_max / rate_min)**utilization
@author Curve.fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
"""
