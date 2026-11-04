# Initialisation through the model hierarchy

We want to investigate solving an aggregate model first, then using its solution
to initialise a more detailed representation of the same system. This is an
interesting use of the multifidelity approach: the simpler representation can
establish consistent operating conditions across a coupled flowsheet before we
introduce the internal detail.

There is some work to do before that. We need sensible starting values, and a
way to initialise individual models and their parents. This note proposes a
bottom-up procedure using the model tree and Dulmage–Mendelsohn (DM) analysis.
It is a research proposal; the recursive procedure is not implemented yet.

## Starting values come first

Every numerical variable needs a usable starting value before evaluating its
equations. These values do not have to satisfy all the equations, but they do
need to keep expressions within their domains. A density used as a denominator
must be positive; a temperature or pressure supplied to a property package must
be within its supported range. Setting every missing value to zero is not a
useful default.

The steam-generating heat-pump system gives us a concrete example. The attempted
aggregate solve was structurally determined, but failed at the first evaluation
of the source-pump work equation because both flow and density started at zero.
The public density variable had no starting value even though the native
property package had its own internal defaults. We need to initialise the
public variables as well as the variables inside the provider.

Starting values could come from property-package defaults, declared model
defaults, available operating information, or a previous solution. The package
and model should provide physically reasonable defaults where information is
missing. Units alone cannot determine a useful value: liquid-water density and
refrigerant-vapour density are quite different despite having the same units.

Keep three concepts separate:

- A **starting value** is a guess that the solver may change.
- An **operating specification** fixes a quantity for the requested problem.
- A **temporary initialisation fix** holds a guessed value during a local solve
  and is released afterwards.

These are steady-state starting guesses. Dynamic initial conditions are a
separate modelling question.

## Proposed bottom-up procedure

Start at the lowest-level models and work upwards through the tree. At each
model, use its equations and the equations of its descendants, with the existing
operating specifications retained. Initialise its children before attempting
the model itself.

For each local problem:

1. Establish valid starting values for its variables, including property-package
   variables and their public projections.
2. Preserve the quantities explicitly fixed by the operating specification.
   A variable having a current value does not make it fixed. A quantity defined
   by an equation should continue to be determined by that equation.
3. Run DM analysis on the active local equality system. Include isolated free
   variables as well as variables appearing in equations.
4. If there is an underconstrained part, select a free input variable in that
   part and trial-fix it to its current value. Consider unmatched variables as
   well as the rest of the underconstrained partition.
5. Recompute the partition. Accept the fix only if it reduces the structural
   deficiency without introducing an overconstrained part. Otherwise undo it
   and try another eligible input.
6. Repeat until the local problem is structurally determined, or there are no
   suitable input variables left to fix.
7. Solve the local problem. On success, retain the resulting variable values.
8. Before solving the parent, release the temporary fixes introduced for this
   local problem. Keep the solved values as the parent's starting guesses.
   The parent's own analysis can then choose its temporary fixes.

We should fix one candidate at a time and recompute the partition, rather than
fixing every input in the original underconstrained set. For example, if a local
equation is `x + y = 10`, fixing either variable closes the problem; fixing both
can impose inconsistent values.

The existing [information-directed specification procedure](information-directed-specification.md)
already uses trial fixes and repeated DM analysis. We can reuse that structural
idea, but the meaning and lifetime of the fixes differ. Here, guessed values
close temporary local problems; they do not become new operating specifications
or measured information.

## What belongs to a local problem?

The model tree gives us an initialisation order, but it does not necessarily
give us independent numerical problems. Sibling models can be coupled through
parent equations, and a recycle can cross several branches of the tree.

A local solve needs a clear boundary: the equations in the selected subtree,
the variables those equations use, and the applicable operating specifications.
Parent connection equations enter when we solve the parent. Independent child
solutions may therefore disagree at a connection; the parent solve reconciles
them using those values as guesses.

Operating specifications on descendant variables must still be respected even
when they were supplied at the top level. For example, if inlet temperature is
specified through a state block, we cannot also fix its enthalpy arbitrarily
and expect the property equations to remain consistent. Trial fixes should
respect that existing temperature specification.

For native property providers, the lowest useful initialisation boundary may
be the provider as a whole. We should make use of an existing provider
initialiser where appropriate, rather than assuming every internal native
block should be solved independently.

## Limits of the input-fixing rule

Using public inputs first is a reasonable, understandable policy. However,
input and output directions describe the model interface; the equation solver
can determine either from the other. We may encounter an underconstrained part
whose remaining freedom is internal or lies on an output.

For the first experiment, report that situation explicitly rather than silently
fixing arbitrary internal variables. We can then decide whether that model
needs a provider initialiser, an explicitly permitted internal starting
specification, or a larger local solve boundary.

Similarly, an overconstrained system cannot be repaired by fixing more inputs.
It needs a separate diagnostic. A zero overall degrees-of-freedom count is not
enough: underconstrained and overconstrained parts can coexist.

Even a complete structural matching does not prove numerical independence or
physical feasibility. Redundant equations, poor scaling, invalid property
states and incompatible operating specifications can still prevent a solve.
The procedure needs to distinguish structural failure from numerical failure.

## Returning to the full system

All temporary fixes must be tracked and released, including on a failed solve.
The original operating specification and equation activation must be restored.
A successful initialisation supplies values for the final model; it must not
quietly change the problem being solved.

At the root, release any remaining temporary fixes and solve the original full
system. Local initialisation success is not evidence that this final solve will
succeed. In particular, tightly coupled recycles may need more than a single
bottom-up pass.

Record which variables were temporarily fixed, their values and units, the
structural deficiency before and after each accepted fix, and local solver
outcomes. This should make it possible to explain an initialisation failure
without confusing guessed boundary conditions with plant data.

## Adding aggregate-first initialisation

Once the baseline procedure works, we can investigate:

1. Select an aggregate representation under the intended operating conditions.
2. Initialise and solve it using the baseline procedure.
3. Transfer values for shared physical quantities to a more detailed
   representation: stream flows, pressures, enthalpies, temperatures and duties
   where their meanings agree.
4. Initialise the newly introduced internal states, then apply the bottom-up
   procedure to the detailed representation.
5. Solve the full detailed system under the intended operating specification.

Transfer starting values, rather than copying temporary fixity. Check fluid,
units and enthalpy-reference compatibility. A different implementation may also
need a different set of independent specifications to express the same operating
conditions.

An aggregate heat-pump solution will not directly provide compressor suction
conditions or every refrigerant state. Those still need to be constructed by
the detailed model's initialisation procedure. Nor does aggregate feasibility
guarantee detailed feasibility. The question is whether the aggregate solution
provides useful consistent boundary conditions that make the detailed solve
more reliable or less expensive.

## First experiments

Keep the first implementation bounded to steady-state models and the current
heat-pump system. Compare:

- Direct solving with the current starting values.
- Direct solving with valid property and model starting values.
- Bottom-up initialisation with DM-guided temporary input fixes.
- Established initialisation routines where applicable.
- Later, aggregate-first transfer followed by the same detailed initialisation.

Use the same final operating conditions and convergence requirements. Measure
full-system solve success, conservation and equation residuals, sensitivity to
starting guesses, and total computational effort including local and failed
solves. Record the number of temporary fixes as well.

The zero-density failure is a useful regression case for valid starting values,
but avoiding it alone would not demonstrate an advantage for hierarchical or
multifidelity initialisation. Those methods need to improve on a baseline that
already has reasonable guesses.

IDAES's [block triangularisation initialiser](https://idaes-pse.readthedocs.io/en/2.8.0/reference_guides/initialization/bt_initializer.html)
is a relevant existing method: it decomposes a numerical system and solves its
strongly connected components. That decomposition and our model hierarchy can
be complementary. We should investigate where the semantic hierarchy adds
useful boundary choices or fidelity transfer, without assuming the tree itself
captures the numerical coupling.

This note develops the initialisation direction in
[algorithms and hierarchies](algorithms-and-hierarchies.md). It does not establish
a performance result or replace the separate electrical-power model-selection
experiment.
