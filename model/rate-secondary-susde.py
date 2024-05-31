import pylab
import numpy as np

beta = 1.5
alpha = 0.33
u0 = 0.85

r0 = 28

u_inf = (beta - 1) * u0 / ((beta - 1) * u0 - (1 - u0) * (1 - alpha))
A = (1 - alpha) * (u_inf - u0) * u_inf / u0
r_minf = alpha - A / u_inf
print(f"""
u_inf = {u_inf}
A = {A}
r_minf = {r_minf}
""")

u = np.linspace(0, 1, 200)
r = r_minf + A / (u_inf - u)
r *= r0

pylab.plot(u, r)
pylab.grid()
pylab.xlabel('Utilization')
pylab.ylabel('r (%)')
pylab.xlim(-0.05, 1.05)
pylab.ylim(-beta * r0 * 0.05, beta * r0 * 1.05)
pylab.show()
