# PI controller

`pi_controller` has two interchangeable relationships. All three public signals
are dimensionless and indexed by time: `signals.setpoint`,
`signals.process_variable`, and `output.value`. Normalize physical measurements
and convert the manipulated output to physical actuator units in the containing
model. Use the same normalization for setpoint and measurement.

Select ideal tracking with `{"relationship": "ideal_tracking"}`. This imposes
`process_variable = setpoint`. The manipulated output is implicit: the connected
process must determine it. Users are responsible for controllability, a feasible
setpoint, and consistent specifications. Do not also prescribe the actuator
output when the loop is intended to calculate it. In a dynamic process this
relationship assumes instantaneous perfect tracking and requires consistent
initial conditions.

Select PI with:

```json
{
  "relationship": "pi",
  "submodels": {"integral": {"relationship": "integrate"}}
}
```

The equations are:

```
error = setpoint - process_variable
d(integral.state.integral)/dt = error
output = bias + kp * error + ki * integral.state.integral
```

Specify scalar inputs `integral.tuning.kp` (dimensionless),
`integral.tuning.ki` (1/s), and `integral.tuning.bias` (dimensionless).
Gains are signed: choose their signs for the process's control action.
There is no derivative action, output saturation, or anti-windup.

In dynamic mode, specify `integral.state.integral` (seconds) at the initial
point through the existing initial-condition specification API. For nonzero
`ki`, `(initial_output - bias - kp * initial_error) / ki` gives an integral
initial value consistent with the desired starting output. When `ki = 0`, the
integral state still evolves but does not affect output.

In steady mode the derivative relation sets error to zero, while the integral
state provides the output required by the process when `ki` is nonzero. With
`ki = 0`, this formulation still imposes zero error and leaves the integral
state unused; select a separate proportional-only model if that behavior is
needed.

Constraint `determines` targets are bookkeeping declarations, not proofs of
local or global mathematical determination. They may be absent from the
equation, as with ideal tracking. Coverage, valid target paths, and duplicate
determination checks still apply.
