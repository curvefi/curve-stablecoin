import numpy as np
import pylab


def plot_rate(min_rate, max_rate, *args, **kw):
    x = np.linspace(0, 1, 100)
    r = (max_rate / min_rate)**x * min_rate
    pylab.plot(x, r, *args, **kw)


if __name__ == '__main__':
    plot_rate(0.5, 25, '--', c="gray")
    plot_rate(0.5, 40, c="black")

    pylab.grid()
    pylab.xlabel('Utilization')
    pylab.ylabel('r (%)')
    pylab.xlim(-0.05, 1.05)
    pylab.ylim(0, 45)
    pylab.show()
