# Isolated n-butane heat pump

Run `uv run python -m case_studies.sghp.heat_pump_cycle`.

This case extracts the refrigerant topology from the archived SGHP revision 83:
compressor → condenser → subcooler → IHX hot side → expansion valve → evaporator
→ IHX cold side → compressor. No flash, steam outlet, source-reheat, water makeup,
or circulation-pump loops are constructed.

The original condenser and subcooler heat separate water circuits. To use the
heat-pump model's single sink interface, this example passes the subcooler's
captured water inlet flow, pressure, and enthalpy through subcooler then condenser.
The source inlet uses the captured evaporator hot inlet. Outlet states are
predicted. This is an adapted boundary-value problem, not a reproduction of the
full study's operating point or steam production.

The example reads `data/full_flowsheet_snapshot.json` for refrigerant-state
guesses, boundary conditions, refrigerant circulation, suction/discharge
pressures, and compressor efficiency. It reads `data/full_calibration.json` for
the saved four-cell exchanger conductances and expansion-valve coefficient.
No refitting occurs. Area is fixed to 1 m² so U numerically represents UA, length
to 5 m, and all pressure drops to zero except the captured 14.242 kPa subcooler
refrigerant drop. Valve opening is calculated. The same EOS and mixed-cell
formulations used in the full case are retained, including their validity limits.

With these assumptions, the four-cell high-component model predicts approximately:

- Compressor electrical power (ideal motor): 12.838 kW.
- Heating duty: 59.923 kW.
- Heat extracted from source: 47.085 kW.
- Heating COP: 4.668.
- Internal heat recovery: 0.376 kW.

These values are reconstruction checks, not independently validated predictions.
Condenser sizing, measurement-driven specification, and automatic fidelity
selection remain outside this example. Models are built without solving; the
example initializes with captured endpoint guesses and a simultaneous solve.
