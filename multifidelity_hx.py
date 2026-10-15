"""Steady-state IDAES heat exchanger with mutually exclusive 0D / 1D models.

Public ports contain independent wrapper-owned Vars. Every coupling equation
lives inside the child it couples, so an inactive fidelity leaves no equations
referencing its private variables. Tested with IDAES 2.8.0 / Pyomo 6.9.2.
"""
from pyomo.common.config import ConfigValue
from pyomo.environ import Block, Constraint, ConstraintList, Param, PositiveReals, Var, value, units as u
from pyomo.network import Port
from idaes.core import UnitModelBlockData, declare_process_block_class
from idaes.core.util.config import is_physical_parameter_block
from idaes.models.unit_models.heat_exchanger import (
    HeatExchanger, HeatExchangerFlowPattern,
    delta_temperature_lmtd_callback,
)
from idaes.models.unit_models.heat_exchanger_1D import HeatExchanger1D


_PORTS = ('hot_side_inlet', 'hot_side_outlet', 'cold_side_inlet', 'cold_side_outlet')


def _convert(source, target):
    return u.convert(source, to_units=u.get_units(target))


def _copy_values(source, target, skip_fixed=False):
    for key, dst in target.items():
        if not (skip_fixed and dst.fixed):
            dst.set_value(value(_convert(source[key], dst)))


@declare_process_block_class('MultiFidelityHeatExchanger')
class MultiFidelityHeatExchangerData(UnitModelBlockData):
    CONFIG = UnitModelBlockData.CONFIG()
    CONFIG.declare('hot_side_property_package', ConfigValue(domain=is_physical_parameter_block))
    CONFIG.declare('cold_side_property_package', ConfigValue(domain=is_physical_parameter_block))
    CONFIG.declare('finite_elements', ConfigValue(default=10, domain=int))
    CONFIG.declare('collocation_points', ConfigValue(default=3, domain=int))

    def build(self):
        super().build()
        if self.config.dynamic or self.config.has_holdup:
            raise ValueError('This prototype supports steady state without holdup only.')
        if self.config.finite_elements < 1 or self.config.collocation_points < 1:
            raise ValueError('Discretization counts must be positive.')
        hot = self.config.hot_side_property_package
        cold = self.config.cold_side_property_package
        kw = dict(dynamic=False, has_holdup=False,
                  flow_pattern=HeatExchangerFlowPattern.countercurrent,
                  hot_side={'property_package': hot},
                  cold_side={'property_package': cold})
        # The 0D API calls this option flow_pattern; the 1D API calls it flow_type.
        self.fidelity_1 = HeatExchanger(
            **kw, delta_temperature_callback=delta_temperature_lmtd_callback)
        kw['flow_type'] = kw.pop('flow_pattern')
        for side in ('hot_side', 'cold_side'):
            kw[side].update(transformation_method='dae.collocation',
                            transformation_scheme='LAGRANGE-RADAU')
        self.fidelity_2 = HeatExchanger1D(
            **kw, finite_elements=self.config.finite_elements,
            collocation_points=self.config.collocation_points)
        # A Python tuple of references; these are not re-parented Pyomo components.
        self.levels = (self.fidelity_1, self.fidelity_2)

        units = hot.get_metadata().get_derived_units
        time = self.flowsheet().time
        self.area = Var(initialize=10, bounds=(1e-8, None), units=units('area'))
        self.overall_heat_transfer_coefficient = Var(
            time, initialize=100, bounds=(1e-8, None),
            units=units('heat_transfer_coefficient'))
        self.heat_duty = Var(time, initialize=1000, units=units('power'),
                             doc='Positive heat transferred to cold side')
        self.length = Param(initialize=5, mutable=True, within=PositiveReals,
                            units=units('length'), doc='1D length; unused in 0D')
        # Clone only port variables, NOT state blocks and their property equations.
        # This avoids redundant composition closure equations at the interface.
        for name in _PORTS:
            original = getattr(self.fidelity_1, name)
            public = Port(noruleinit=True)
            self.add_component(name, public)
            for member, source in original.vars.items():
                if source.ctype is not Var:
                    raise TypeError(f'Port member {name}.{member} must be a Var.')
                first = next(iter(source.values()))
                kwargs = dict(initialize=value(first), units=u.get_units(first))
                variable = Var(source.index_set(), **kwargs) if source.is_indexed() else Var(**kwargs)
                self.add_component(f'{name}_{member}', variable)
                for key, dst in variable.items():
                    src = source[key]
                    dst.domain = src.domain
                    dst.setlb(src.lb)
                    dst.setub(src.ub)
                _copy_values(source, variable)
                public.add(variable, member)

        for level in self.levels:
            level.interface = Block()
            links = level.interface.links = ConstraintList()
            for name in _PORTS:
                for member, public in getattr(self, name).vars.items():
                    private = getattr(level, name).vars[member]
                    for key in public:
                        links.add(private[key] == _convert(public[key], private[key]))
            links.add(level.area == _convert(self.area, level.area))
            if level is self.fidelity_1:
                for t in time:
                    links.add(level.overall_heat_transfer_coefficient[t] ==
                              _convert(self.overall_heat_transfer_coefficient[t],
                                       level.overall_heat_transfer_coefficient[t]))
                    links.add(self.heat_duty[t] == _convert(level.heat_duty[t], self.heat_duty[t]))
            else:
                links.add(level.length == _convert(self.length, level.length))
                for t, x in level.heat_transfer_coefficient:
                    links.add(level.heat_transfer_coefficient[t, x] ==
                              _convert(self.overall_heat_transfer_coefficient[t],
                                       level.heat_transfer_coefficient[t, x]))
                domain = level.cold_side.length_domain
                for t in time:
                    # Countercurrent cold inlet at x=1, outlet at x=0.
                    inlet = level.cold_side.properties[t, domain.last()]
                    outlet = level.cold_side.properties[t, domain.first()]
                    duty = sum(outlet.get_enthalpy_flow_terms(p) -
                               inlet.get_enthalpy_flow_terms(p) for p in cold.phase_list)
                    links.add(self.heat_duty[t] == _convert(duty, self.heat_duty[t]))
        self.select_fidelity(1)

    @property
    def active_fidelity(self):
        selected = [level for level in self.levels if level.active]
        if len(selected) != 1:
            raise RuntimeError('Expected exactly one active fidelity.')
        return selected[0]

    def select_fidelity(self, fidelity):
        """Select 1 (0D), 2 (1D), or one of the child objects; preserve specs.

        Changes activation flags only. Call initialize() to transfer guesses
        and initialize the selected model before solving if needed.
        """
        if isinstance(fidelity, int) and not isinstance(fidelity, bool) and fidelity in (1, 2):
            target = self.levels[fidelity - 1]
        elif any(fidelity is level for level in self.levels):
            target = fidelity
        else:
            raise ValueError('Choose 1, 2, fidelity_1, or fidelity_2.')
        # Change only child block flags, preserving their internal constraint flags.
        for level in self.levels:
            if level is target:
                level.activate()
            else:
                level.deactivate()
        return target

    def _seed_active_fidelity(self):
        """Copy public boundary guesses; linearly interpolate 1D state profiles."""
        level = self.active_fidelity
        level.area.set_value(value(_convert(self.area, level.area)))
        if level is self.fidelity_1:
            _copy_values(self.overall_heat_transfer_coefficient,
                         level.overall_heat_transfer_coefficient)
            _copy_values(self.heat_duty, level.heat_duty)
        else:
            level.length.set_value(value(_convert(self.length, level.length)))
            level.cold_side.length.set_value(value(_convert(self.length, level.cold_side.length)))
            for (t, x), var in level.heat_transfer_coefficient.items():
                var.set_value(value(_convert(self.overall_heat_transfer_coefficient[t], var)))
            for side_name in ('hot_side', 'cold_side'):
                side = getattr(level, side_name)
                for (t, x), state in side.properties.items():
                    a = x if side_name == 'hot_side' else 1 - x
                    for member, var in state.define_state_vars().items():
                        src_in = getattr(self, f'{side_name}_inlet').vars[member]
                        src_out = getattr(self, f'{side_name}_outlet').vars[member]
                        for key, dst in var.items():
                            index = (t,) + (key if isinstance(key, tuple) else (key,)) if var.is_indexed() else t
                            dst.set_value(value(_convert((1-a)*src_in[index] + a*src_out[index], dst)))
        for name in _PORTS:
            for member, public in getattr(self, name).vars.items():
                _copy_values(public, getattr(level, name).vars[member])

    def initialize_build(self, **kwargs):
        """Initialize selected built-in HX with interface temporarily disabled.

        Uses current public inlet/area/U values, even if supplied by an upstream
        unit. Restores every temporary fixation in finally. Solver arguments are
        those of IDAES initialize_build, e.g. solver='ipopt', optarg={...}.
        """
        level = self.active_fidelity
        self._seed_active_fidelity()
        # Built-in initializers also temporarily fix variables and deactivate
        # equations. Preserve their flags even if a solver fails partway through.
        fixed = [(v, v.fixed) for v in level.component_data_objects(Var)]
        constraint_flags = [(c, c.active) for c in
                            level.component_data_objects(Constraint, active=None)]
        block_flags = [(b, b.active) for b in
                       level.component_data_objects(Block, active=None)]
        to_fix = [level.area]
        for name in ('hot_side_inlet', 'cold_side_inlet'):
            for variable in getattr(level, name).vars.values():
                to_fix.extend(variable.values())
        if level is self.fidelity_1:
            to_fix.extend(level.overall_heat_transfer_coefficient.values())
        else:
            to_fix.extend([level.length])
            to_fix.extend(level.heat_transfer_coefficient.values())
        interface_active = level.interface.active
        level.interface.deactivate()
        try:
            for var in to_fix:
                var.fix()
            level.initialize(**kwargs)
        finally:
            for var, was_fixed in fixed:
                var.fix() if was_fixed else var.unfix()
            for con, was_active in constraint_flags:
                con.activate() if was_active else con.deactivate()
            for block, was_active in block_flags:
                block.activate() if was_active else block.deactivate()
            if interface_active:
                level.interface.activate()
        for name in ('hot_side_outlet', 'cold_side_outlet'):
            for member, public in getattr(self, name).vars.items():
                _copy_values(getattr(level, name).vars[member], public, skip_fixed=True)
        if level is self.fidelity_1:
            _copy_values(level.heat_duty, self.heat_duty, skip_fixed=True)
        else:
            cold = self.config.cold_side_property_package
            for t, dst in self.heat_duty.items():
                if not dst.fixed:
                    pi = level.cold_side.properties[t, 1]
                    po = level.cold_side.properties[t, 0]
                    dst.set_value(value(_convert(sum(po.get_enthalpy_flow_terms(p) -
                        pi.get_enthalpy_flow_terms(p) for p in cold.phase_list), dst)))
