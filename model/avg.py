import pylab
import numpy as np


def calc_price(D, p, sigma=0.001):
    D = np.array(D)
    p = np.array(p)
    p_pre = (D * p).sum() / D.sum()
    e = (p - p_pre) ** 2 / sigma**2
    e -= e.min()
    w = D * np.exp(-e)
    return (w * p).sum() / w.sum()


if __name__ == "__main__":
    N = 4
    D = [100] * N
    p = np.linspace(0.9, 1.1, 1000)
    p_new = [calc_price(D, [_p] + [1] * (N - 1)) for _p in p]
    pylab.plot(p, p_new)
    pylab.show()
