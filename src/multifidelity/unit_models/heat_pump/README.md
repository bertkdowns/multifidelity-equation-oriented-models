# Aggregate heat pump

`HeatPump` owns source/sink inlet and outlet states and ports, and
`electrical_power[t]`. Builders receive the unit directly. The initial `cop`
formulation is `COPHeatPump`; no hierarchy or configuration classes are added.

Heating duty is positive sink enthalpy gain. Cooling duty is positive heat
extracted from the source, equal to heating duty minus electrical power. The
aggregate formulation conserves material, preserves each stream's pressure,
and enforces `heating_duty = COP * electrical_power`.

COP is a dimensionless variable on `hp.fidelities["cop"].COP[t]`, bounded below
by one. Fix it explicitly. For prediction, specify sink outlet temperature or
an external heating-duty constraint and leave electrical power free. For rating,
fix electrical power instead. Inlet flow, temperature and pressure must also
be specified. Initialization temporarily fixes inlet states and preserves all
other specification flags.

Electrical power represents compressor electrical input; the supplied heating
COP includes motor losses, assumed to remain within the heat-pump energy
boundary. Auxiliary pumps/fans and ambient losses are excluded. This is an
assumed performance relation, not a refrigerant-cycle or feasibility model;
it does not enforce a temperature-lift-dependent COP limit. The initial example
uses single-phase linear liquid-water properties and zero pressure drops.

See `examples/heat_pump.py` for aggregate power prediction.

## Explicit cycle

Supply `refrigerant_property_package` and include `"cycle": CycleHeatPump()` in
the `fidelities` mapping to build an explicit cycle. It contains compressor,
condenser, subcooler, IHX, expansion valve, and evaporator, with the refrigerant
returning through the IHX cold side to the compressor. Internal ports and expanded
Pyomo Arcs connect components and the external source/sink interface. One
redundant refrigerant-loop material balance is omitted at the valve; all stream
connections and the other balances remain enforced.

The sink flows through the subcooler and then the condenser, while the source
passes through the evaporator. Electrical power equals compressor shaft work:
the explicit model assumes an ideal motor and excludes auxiliary loads and
ambient losses. Its energy boundary therefore matches the aggregate balance.

Each exchanger offers `low` (Chen) and `high` (segmented) formulations, and the
valve offers `low` (basic) and `high` (pressure-flow) formulations. Select these
directly on `hp.fidelities["cycle"].ihx`, etc. No hierarchy classes are required.
The default component selection is low; the SGHP example explicitly selects high.

Equipment specifications belong to the caller. The SGHP example fixes exchanger
UA/geometry and pressure drops, compressor efficiency, refrigerant circulation,
suction/discharge pressures, valve Cv, and external inlet states. Valve opening,
outlet states, and power are calculated. COP is an output of this representation;
the aggregate formulation's COP variable is irrelevant while inactive. Changing
representations preserves flags and values but does not automatically adapt
specifications. The aggregate power-prediction problem requires its own COP and
heating target.

For a two-phase sink outlet, temperature and pressure do not determine outlet
enthalpy or vapor fraction. Specify duty, enthalpy, or another independent
quantity when preparing the aggregate prediction problem; a temperature target
alone may not define the intended heat load.

Cycle initialization seeds exchanger interiors from supplied endpoint guesses
and solves simultaneously; it does not implement a new recycle initializer.
See `case_studies/sghp/heat_pump_cycle.py` for the isolated n-butane cycle and its
documented case-specific parameterization.
