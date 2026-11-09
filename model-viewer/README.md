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

Dragged node positions (including group moves) are saved in browser local storage
per model definition ID, relationship, and Summary/Detailed view. Opening the same
model through another parent or alias reuses its layout. Positions survive page
reloads; newly added nodes retain their automatic positions. Storage is local to
this browser and site origin. Summary rotations and flips are saved alongside positions. Previously saved position-only layouts remain compatible.

### Information overlays

Open **Information** (or **Choose information** in the sidebar) and drop an
information-record JSON array onto its upload area, or choose a `.json` file.
The file attaches to the selected root definition, with paths relative to that
root. Switching roots keeps each root's file separate. Uploaded information and
new records are saved in browser local storage and restored after reloading. Replace/Clear controls manage the active overlay.

Detailed variable rows show the highest-trust record's preview in its original
unit, with a count of alternatives. Clicking opens all candidate records, their
source/tag, trust, uncertainty, full values and the model's declared unit. Ties
use record ID order. Summary model sidebar rows show the same previews. These
are information records, not computed values or selected specifications, and
values do not propagate along connections. Series show sample counts or array
shape; no time coordinates are inferred. Paths preserve occurrence aliases when
exploring children, independently of shared layout storage. Unmatched paths are
listed; paths found in another alternative remain available when browsing it.

Loading validates record structure, unique IDs, finite scalar/rectangular numeric
values and metadata. It does not validate physical applicability, convert units,
check series against a solver grid, or apply `specification.json` selections.

### Choosing an implementation

Open **Implementation** (or **Choose implementation** in the sidebar) to choose
relationships recursively for the selected root. The live summary groups remaining
input families by model occurrence and struct, excluding child inputs supplied by
parent equations or struct connections. Partially supplied structs list only their
remaining fields. Derivative initial-state families are listed separately.

Changing a relationship replaces that occurrence's subtree with default choices
for its newly selected children; siblings are preserved. Expand nested models to
change deeper choices. **View diagram** opens that occurrence using its selected
relationship. In the sidebar preview selector, the implementation choice is bold
and marked `(implementation)`. Other relationships can be previewed without editing
the implementation; **View selected implementation** returns to the chosen tree.

Upload/drop an existing implementation against the matching root, or download the
current choices as JSON. Documents contain `relationship` and recursive `submodels`
only (the root model ID is deliberately not embedded, matching the Python API).
Malformed or incompatible uploads leave current choices unchanged. Incomplete
choices, unresolved generics and declaration coverage errors block export.
Implementation choices are saved per root in browser local storage and restored
across reloads; download keeps a portable copy. Layouts and information overlays remain separate.

Input summaries follow the backend's declaration-coverage rules, including external
providers' public interfaces. They do not compile equation expressions, establish
unit/generic compatibility or prove mathematical solvability. Final builds still
perform the backend's complete validation.

### Information table and new records

The **Information** tab uses the same per-root document as the diagram overlay.
Upload a document in that tab, filter the table by path/ID/tag/source/
unit, and expand series rows to inspect full arrays. Every candidate remains a
separate row; the Preview badge follows trust rank and ID ordering. Path status
indicates whether a variable is in the chosen implementation, another available
relationship, or unmatched.

Use **Add information record** to add a unique ID, tag, root-relative variable
path, source type, constant or JSON numeric array, unit, optional uncertainty and
trust rank. Variable-path suggestions come from the selected implementation;
a recognized path initially suggests its declared unit, which can be overridden.
Unknown paths are allowed and marked unmatched. Additions validate the complete
document atomically and immediately update diagram previews. No units are converted,
no values propagated and no solver specifications applied. Download the information
JSON to save the updated document. Changes are saved in browser local storage and do not modify the uploaded source
file.

### Results snapshots

The **Results** tab accepts the version 1 `ResultsDocument` JSON format exported
by Python. Drop a file or choose it; its model ID selects the root. Results are
saved per root in browser local storage, separately from information documents. Replace,
Clear and Download controls manage the snapshot without modifying the source
file. Invalid uploads leave the current snapshot intact.

The tab shows run identity/time, the saved implementation, solve status and
termination, and a searchable table of every public variable family. Each value
has units, explicit index coordinates and export-time fixed/free state. Indexed
families expand to their full entries; unavailable values show `unset` or
`nonfinite`. A failed/not-solved snapshot is labelled as unconverged. Solver
status does not establish physical applicability of an operating point.

If the saved implementation differs from the current choice, the tab offers
**Use saved implementation**. Diagram previews stay hidden until the selections
match, and are also hidden when previewing another relationship. Matching diagram
rows show the saved value and units in blue, independently of information
previews. Clicking a result opens its coordinate/value/fixity details. Solve
status is available in the tooltip and Results tab rather than repeated on each
row. No values are propagated or units converted.

Use `examples/steam_generating_heat_pump_system/results.json` for a complete
SGHP snapshot. Older `attempt_*_result.json` files are diagnostic reports rather
than this upload format. Current-library path checks identify unmatched paths;
they do not prove that model definitions are identical to those used for the run.


Implementation, information and results documents persist separately by root model,
including uploaded filenames and information additions. Reloading also reopens the
last root model. Clearing information or results removes its stored copy. Storage
is local to this browser and site origin; download JSON for portable backups.
Invalid stored documents are skipped with a message, and full or disabled storage
reports that the current document could not be saved. Incomplete implementation
drafts can be restored and completed in the editor.

### Open/save a workspace

**Open workspace** in the sidebar's model controls accepts one JSON bundle with
exactly `implementation`, `information`, and `results`. It validates all three
before applying them, selects the root using the results snapshot's existing
`model_id`, and replaces the three documents for that root. Invalid or unknown-model
bundles leave the current case unchanged. The existing local-storage persistence
then saves each document as usual.

**Save workspace** downloads those three contents in one file, provided the results
match the selected implementation. Information can be an empty record array. No
extra model/root field, model definitions, layout positions, rotations, flips,
current view or navigation state is included. Opening a bundle leaves local diagram
preferences intact. Individual file uploads/downloads remain available in their
tabs. Python can produce the identical format using `export_workspace` or
`WorkspaceDocument.from_results`; see the SGHP example's workspace files.
