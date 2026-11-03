"""Mix routed phase enthalpies, with an explicit empty-stream state convention."""


def build_phase_mixture(block, config):
    from pyomo.environ import Constraint, Expr_if, Var, units as u

    block.liquid_flow = Var(initialize=1, bounds=(0, None), units=u.kg/u.s)
    block.vapor_flow = Var(initialize=1, bounds=(0, None), units=u.kg/u.s)
    block.liquid_enthalpy = Var(initialize=1, units=u.J/u.kg)
    block.vapor_enthalpy = Var(initialize=1, units=u.J/u.kg)
    block.fallback_vapor = Var(initialize=0, bounds=(0, 1), units=u.dimensionless)
    block.flow = Var(initialize=2, bounds=(0, None), units=u.kg/u.s)
    block.enthalpy = Var(initialize=1, units=u.J/u.kg)
    total = block.liquid_flow + block.vapor_flow
    positive = total > 0*u.kg/u.s
    # Protect the unused division branch as well: the empty-stream convention
    # changes no mass or energy flux and introduces no epsilon leakage.
    denominator = Expr_if(IF=positive, THEN=total, ELSE=1*u.kg/u.s)
    fallback = ((1-block.fallback_vapor)*block.liquid_enthalpy +
                block.fallback_vapor*block.vapor_enthalpy)
    block.flow_equation = Constraint(expr=block.flow == total)
    block.enthalpy_equation = Constraint(expr=block.enthalpy == Expr_if(
        IF=positive,
        THEN=(block.liquid_flow*block.liquid_enthalpy + block.vapor_flow*block.vapor_enthalpy)/denominator,
        ELSE=fallback,
    ))
    return {
        'phases.liquid_flow': block.liquid_flow,
        'phases.vapor_flow': block.vapor_flow,
        'phases.liquid_enthalpy': block.liquid_enthalpy,
        'phases.vapor_enthalpy': block.vapor_enthalpy,
        'phases.fallback_vapor': block.fallback_vapor,
        'stream.flow': block.flow,
        'stream.enthalpy': block.enthalpy,
    }
