# Model-language terminology

This is the authoritative glossary for the JSON model language. It applies to
`model_language`, its examples, research proposals and model viewer. The older
Python unit-model architecture has its own conventions in `docs/design.md`.

A **document** is portable, validated data that can be serialized as JSON.
A document is distinct from a live numerical object. Document filenames are not
model identities: references use the `id` declared inside a model document.

| Term | Definition / ownership | Python representation today |
| --- | --- | --- |
| Model definition | Reusable mathematical interface and its alternative formulations. | Contents of `ModelDocument` |
| Model document | JSON representation of one model definition, owning structs, domains, model parameters and relationships. | `ModelDocument` |
| Variable | Quantity declaration owned by one struct: units, bounds, value type and dimensions; no operating value or fixation. | `Variable` |
| Struct | Named group of variables, wholly input or output, owned by a model definition. Direction does not mean fixed/free. | `Struct` |
| Relationship | One alternative formulation, owning child references, constraints, connections and derivatives, or an external provider declaration. Owns no variables. | `Relationship` |
| Constraint | Equality referring to existing variables, with a `determines` declaration for structural validation. | `Constraint` |
| Connection | Struct link expanded into field-by-field equality equations; variables remain distinct. | `Connection` |
| Domain | Declared indexing axis, such as time or a discrete domain. | `Domain` |
| Derivative | Declared first derivative relating state and rate variable families. | `Derivative` |
| Model reference | Named use of a reusable definition within a relationship. References do not own the referenced definition. | `ConcreteModelReference` / `ParameterModelReference` |
| Model parameter | Required public interface for a replaceable model argument. | `ModelParameter` |
| Model occurrence | One use of a definition at a particular hierarchy path; separate occurrences create separate numerical variables. | Context carried by `ModelView` |
| Model library | Collection of model documents indexed by model ID, plus registered symbolic providers. | `Library` |
| Model view | Navigable definition in a reference and generic-argument context. Exposes all relationship alternatives, without selecting one or building numerical objects. | `ModelView` / `RelationshipView` |
| Implementation document | Recursive relationship choices for a separately supplied root model and exactly the children of each selected relationship. Contains no model IDs or operating values. | `ImplementationDocument`, containing `ImplementationSelection` entries |
| Implementation | Selected model hierarchy obtained by interpreting an implementation document against a model library. One relationship participates per occurrence. | Shared internal traversal used by the builder and requirement queries; no separate public class |
| Information record | One observation, equipment specification, parameter, setpoint or assumption, with variable path, value(s), units, trust rank and optional uncertainty. | `InformationRecord` |
| Information table | Collection of available records for an operating case, retaining alternative records for the same variable. | Contents of `InformationDocument` |
| Information document | Portable representation of an information table; the JSON format is an array of records. | `InformationDocument` |
| Quantity of interest / prediction target | Variable whose value an analysis aims to predict. | Variable path |
| Quantity-of-interest document | Prediction target paths, without target values or accuracy thresholds. | Proposed JSON shape: `{"quantities": [{"variable_path": "..."}]}`; no typed class yet |
| Specification document | Chosen information-record IDs in `specifications` (whole families) and `initial_values` (first time slice). Records own paths and values; context and diagnostics are separate. | `SpecificationDocument` with two arrays of ID strings; `apply_specification()` |
| Specification plan | The decisions contained in a specification document; not a separate document type. | Same conceptual artifact as the specification document |
| Initial condition | A fixed value or profile at the first time point, selected through `initial_values`; distinct from an unfixed solver initial guess. | Applied by `apply_specification()` |
| Numerical instance | Live numerical equation system for an implementation with its specifications applied. Construction alone may leave it unspecified. | Pyomo `ConcreteModel` with IDAES `FlowsheetBlock`; no instance-document class |
| Solve result | Outputs, solver status and provenance from one solve attempt, distinct from structural specification status. | No model-language result type yet |

## Layered architecture

```text
Model documents + Implementation document
    → Implementation (root model supplied separately)

Implementation + Information document + Quantity-of-interest document
    → Specification document

Implementation + Specification document + Information document
    → Numerical instance

Numerical instance + numerical solve
    → Solve result
```

The first layer is implemented through library navigation, selected traversal and
construction. Specification application and initial trust-ranked DM specification
generation are implemented; typed target/result artifacts remain proposed. Structural algorithms may construct the numerical
equations before generating a specification document; the diagram expresses data
dependencies, not a mandatory construction order.

Specification documents contain only specification choices. The caller supplies
the implementation/model instance and information document separately; source
identities, version fingerprints, structural status and unused-information audit
records are not fields of a specification document. Structural completeness and
numerical convergence are separate checks.

Use “document” for portable data, “implementation” for the selected hierarchy, and
“numerical instance” for live numerical objects. Reference resolution is an
operation, not a name for an implementation. See
[the specification proposal](../../../research-ideas/information-directed-specification.md)
for the proposed algorithms and audit contents.

## Python API naming changes

Python imports use the following names (old names are not retained as aliases):

| Previous name | Current name |
| --- | --- |
| `definitions.Model` | `ModelDocument` |
| `implementation.Implementation` | `ImplementationDocument` |
| `InformationTable` | `InformationDocument` |
| `ResolvedModel` | `ModelView` |
| `ResolvedRelationship` | `RelationshipView` |

These current types are also available from `multifidelity.model_language`.
`ImplementationSelection` remains the name for nested selection entries.
`Library.resolve()` remains the reference-navigation operation and returns a
`ModelView`; it does not select an implementation.

## Current document shapes

- Model document: a Pydantic object containing the reusable definition and its `id`.
- Implementation document: a Pydantic object with `relationship` and optional
  recursive `submodels`. No model IDs; the root is supplied to the operation.
- Information document: a Pydantic array of `InformationRecord` objects.
- Specification document: a Pydantic object with `specifications`, an array of
  selected information-record ID strings, plus `initial_values` for initial conditions.
  Both arrays default to empty. No separate entry wrapper type.

All support Pydantic validation/serialization plus `from_json()` and `load_json()`.
`get_variable(model, path)` provides public access to numerical variable families.
