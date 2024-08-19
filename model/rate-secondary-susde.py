import pylab
import numpy as np


def plot_rate(alpha, beta, u0, r0, *args, **kw):
    u_inf = (beta - 1) * u0 / ((beta - 1) * u0 - (1 - u0) * (1 - alpha))
    A = (1 - alpha) * (u_inf - u0) * u_inf / u0
    r_minf = alpha - A / u_inf
    print(f"""
    alpha = {alpha}
    beta = {beta}
    u0 = {u0}
    r0 = {r0}
    """)
    print(f"""
    u_inf = {u_inf}
    A = {A}
    r_minf = {r_minf}
    """)

    u = np.linspace(0, 1, 200)
    r = r_minf + A / (u_inf - u)
    r *= r0
    pylab.plot(u, r, *args, **kw)


if __name__ == '__main__':
    beta = 2.5
    r0 = 10

    plot_rate(0.35, 1.5, 0.85, 10, '--', c="gray")
    plot_rate(0.35, 2.5, 0.8, 10, c="black")

    pylab.grid()
    pylab.xlabel('Utilization')
    pylab.ylabel('r (%)')
    pylab.xlim(-0.05, 1.05)
    pylab.ylim(-beta * r0 * 0.05, beta * r0 * 1.05)
    pylab.show()
