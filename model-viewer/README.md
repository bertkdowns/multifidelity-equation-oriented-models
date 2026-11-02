# Model explorer

Separate, read-only React Flow app for the JSON model language. From this directory:

```bash
npm install
npm run dev
```

Open the URL printed by Vite (normally http://localhost:5173). `npm run build`
creates a standalone static site in `dist`; `npm run preview` serves that build.
`npm test` verifies graph construction against the real model library.

The library is loaded directly from `../src/multifidelity/model_language/models/*.json`.
Select any definition and one of its alternative relationships. Click a child model
to drill down; breadcrumb buttons return to ancestors. Each level remembers its
relationship selection. Generic arguments propagate through concrete wrappers;
opening a generic definition directly displays its required interface and a warning
for unbound children. This browses definitions, rather than loading implementation
selection documents or constructing solver objects.

Input/output structs list all variables and units. Child model nodes expose their
structs and variable handles. Teal arrows represent named struct connections;
purple arrows join referenced variables to equations and equations to their
`determines` targets. These arrows describe declarations, not a numerical solve
order or proof of solvability. Click constraints or edges for details, drag nodes,
pan/zoom, and use the minimap and fit-view control to navigate larger graphs.
Click a struct header to collapse its variables, or the model's Structs toggle to
collapse its entire interface list. Links remain attached to the collapsed header;
expanding restores their individual variable endpoints. These toggles do not open
the child model; click its model header to drill down.

React Flow handles follow the [official handle API](https://reactflow.dev/learn/customization/handles).

Indexed/dynamic definitions are displayed at variable-family level: `flow[time]`
(or ordered multiple dimensions) appears on variable rows and in the sidebar.
Equation links retain authored subscripts such as `[t, j]` but connect to the
corresponding family port. Detailed equations display `for_each` loop bindings.
Derivative declarations appear as constraint nodes labelled DERIVATIVE, connecting
state/rate families according to their `determines` declaration. Their full
metadata is available on click. The sidebar lists index domains and child-to-parent
domain bindings when drilling down. The viewer does not expand numerical domain
members, simulate trajectories, or choose steady/dynamic solver modes.

See the [model-language glossary](../src/multifidelity/model_language/terminology.md) for the shared terminology.
