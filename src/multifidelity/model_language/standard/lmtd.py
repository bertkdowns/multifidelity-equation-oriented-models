"""Scalar smoothed LMTD using the expression from IDAES' exchanger callback."""


def build_lmtd(block, config):
    from pyomo.environ import Constraint, Var, log, units as u

    block.hot = Var(initialize=10, bounds=(1e-8, None), units=u.K)
    block.cold = Var(initialize=10, bounds=(1e-8, None), units=u.K)
    block.mean = Var(initialize=10, units=u.K)
    ratio = block.cold / block.hot
    # Kazi et al. smoothing as implemented by IDAES 2.8
    # delta_temperature_lmtd_smooth_callback. Equal ends have the exact limit.
    epsilon = 1e-10
    block.mean_equation = Constraint(expr=block.mean == block.hot *
        ((ratio - 1)**2 + epsilon)**0.5 / (log(ratio)**2 + epsilon)**0.5)
    return {'ends.hot': block.hot, 'ends.cold': block.cold,
            'mean.temperature_difference': block.mean}
