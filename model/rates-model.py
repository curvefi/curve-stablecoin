import numpy as np
import pylab

M = 3.0  # 300% is max rate
x = np.linspace(0, 1, 100)

for S in [1.1, 2, 5, 10, 15]:
    a = M / (2 * (S - 1))
    b = (S - 1) / (S - 0.5)
    r = a * b * x / (1 - b * x)
    pylab.plot(x, r)

pylab.show()
