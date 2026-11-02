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
| Implementation document | Recursive relationship choices identifying a root model and exactly the children of each selected relationship. Contains no operating values. | `ImplementationDocument`, containing `ImplementationSelection` entries |
| Implementation | Selected model hierarchy obtained by interpreting an implementation document against a model library. One relationship participates per occurrence. | Traversed by the builder and requirement queries; no standalone class yet |
| Information record | One observation, equipment specification, parameter, setpoint or assumption, with variable path, value(s), units, trust rank and optional uncertainty. | `InformationRecord` |
| Information table | Collection of available records for an operating case, retaining alternative records for the same variable. | Contents of `InformationDocument` |
| Information document | Portable representation of an information table; the JSON format is an array of records. | `InformationDocument` |
| Quantity of interest / prediction target | Variable whose value an analysis aims to predict. | Variable path |
| Quantity-of-interest document | Prediction target paths, without target values or accuracy thresholds. | Proposed JSON shape: `{"quantities": [{"variable_path": "..."}]}`; no typed class yet |
| Specification document | Reviewable instructions choosing which information records to apply to which implementation variables, with applied values/units, provenance, rejected choices and structural completeness. | Proposed; no typed class or application API yet |
| Specification plan | The decisions contained in a specification document; not a separate document type. | Same conceptual artifact as the specification document |
| Numerical instance | Live numerical equation system for an implementation with its specifications applied. Construction alone may leave it unspecified. | Pyomo `ConcreteModel` with IDAES `FlowsheetBlock`; no instance-document class |
| Solve result | Outputs, solver status and provenance from one solve attempt, distinct from structural specification status. | No model-language result type yet |

## Layered architecture

```text
Model documents + Implementation document
    → Implementation

Implementation + Information document + Quantity-of-interest document
    → Specification document

Implementation + Specification document
    → Numerical instance

Numerical instance + numerical solve
    → Solve result
```

The first layer is implemented through library navigation, selected traversal and
construction. Specification generation/application and typed target/result
artifacts remain proposed. Structural algorithms may construct the numerical
equations before generating a specification document; the diagram expresses data
dependencies, not a mandatory construction order.

A specification document should identify the implementation and model-definition
versions it was checked against. Version pinning is a design requirement for
reproducibility, not an implemented feature. Structural completeness and numerical
convergence are separate checks.

Use “document” for portable data, “implementation” for the selected hierarchy, and
“numerical instance” for live numerical objects. Reference resolution is an
operation, not a name for an implementation. See
[the specification proposal](../../../research-ideas/information-directed-specification.md)
for the proposed algorithms and audit contents.

## Python API naming changes

The document JSON shapes and model IDs are unchanged. Python imports use the
following names (old names are not retained as aliases):

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
