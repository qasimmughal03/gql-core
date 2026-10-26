# GQL-Core Ontology Schema Specification

**Version**: 1.0  
**Package**: `gql_core.ontology`  
**Reference Models**: [`EntityType`](gql_core/ontology/model.py), [`RelationshipType`](gql_core/ontology/model.py), [`OntologySchema`](gql_core/ontology/schema.py)  

---

## 1. Overview

GQL-Core provides a declarative ontology definition framework extending SHACL-style constraints with rich ontological relationship semantics:
- Subtype/supertype hierarchies with transitive inheritance
- Cardinality bounds (min/max incoming and outgoing)
- Relationship algebraic properties (inverse, symmetric, transitive, reflexive, irreflexive, asymmetric)
- Explicit Closed-World (CWA) vs Open-World (OWA) reasoning declarations
- Complete graph constraint validation.

---

## 2. Entity Types

Entity types define the structural and semantic constraints for graph nodes.

```yaml
nodes:
  Person:
    required: [id, name]
    optional: [email, age]
    types:
      id: str
      name: str
      email: str
      age: int
    patterns:
      email: "^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+$"
    min:
      age: 0

  Employee:
    subClassOf: [Person]  # Subtype inheritance
    required: [employee_id, department]
    types:
      employee_id: str
      department: str
```

### 2.1 Entity Properties

| Attribute | Type | Description |
| :--- | :--- | :--- |
| `name` | `str` | Unique label of the entity class. |
| `properties` | `dict[str, PropertyDef]` | Property definitions with types, nullability, enums, patterns, and bounds. |
| `supertypes` | `tuple[str, ...]` | List of parent entity classes from which properties and type membership are inherited. |
| `is_abstract` | `bool` | If true, entity cannot be directly instantiated without a concrete subtype. |
| `identity_prop`| `str` | Canonical identifier property (default `"id"`). |

---

## 3. Relationship Types

Relationship types define directed or undirected connections between entity domains and declare semantic reasoning rules.

```yaml
relationships:
  REPORTS_TO:
    source: Employee
    target: Employee
    directed: true
    cardinality:
      outgoing:
        min: 0
        max: 1  # Functional relationship: at most 1 manager
    inverse: MANAGES
    transitive: false
    irreflexive: true
    reasoning_mode: CWA

  TEAMMATES_WITH:
    source: Player
    target: Player
    symmetric: true
    irreflexive: true
    reasoning_mode: CWA

  LOCATED_IN:
    source: Node
    target: Node
    transitive: true
    irreflexive: true
    reasoning_mode: CWA
```

### 3.1 Relationship Properties

| Attribute | Type | Description |
| :--- | :--- | :--- |
| `name` | `str` | Edge label. |
| `source_type` | `str` | Domain entity type. Validates that source node satisfies this type or its subtypes. |
| `target_type` | `str` | Range entity type. Validates that target node satisfies this type or its subtypes. |
| `directed` | `bool` | True for directed edges; False for undirected. |
| `cardinality` | `CardinalityConstraint` | Min/max bounds for incoming and outgoing edges per node. |
| `inverse` | `str | None` | Declares inverse relationship name (e.g. `REPORTS_TO` inverse `MANAGES`). |
| `is_symmetric` | `bool` | If true, `(A)-[R]->(B)` implies `(B)-[R]->(A)`. |
| `is_transitive` | `bool` | If true, `(A)-[R]->(B)` and `(B)-[R]->(C)` implies `(A)-[R]->(C)`. |
| `is_irreflexive` | `bool` | If true, self-loops `(A)-[R]->(A)` are prohibited. |
| `reasoning_mode` | `ReasoningMode` | Declares `CWA` (Closed-World) or `OWA` (Open-World). |

---

## 4. Reasoning-World Assumptions

GQL-Core provides explicit control over reasoning-world assumptions per relationship or data domain:

### 4.1 Closed-World Assumption (CWA)
- The graph is assumed to be complete for the declared predicate.
- Absence of an edge implies that the relationship does **not** hold (`False`).
- `NOT EXISTS` proves absence within the bounded dataset.

### 4.2 Open-World Assumption (OWA)
- Absence of an edge does not establish falsehood; it implies **Unknown** (`None`).
- Used in incomplete knowledge bases or web-scale data where facts may exist outside the local partition.

---

## 5. Constraint Validation

[`OntologySchema.validate_graph(graph)`](gql_core/ontology/schema.py) performs full structural verification:
- **`REQUIRED_PROP_MISSING`**: Required properties are non-null and non-empty.
- **`ENUM_VIOLATION`**: Values match declared enumeration sets.
- **`PATTERN_VIOLATION`**: String values match declared regex patterns.
- **`IRREFLEXIVE_VIOLATION`**: Prohibits self-loops on irreflexive relationships.
- **`INVALID_SOURCE_TYPE` / `INVALID_TARGET_TYPE`**: Endpoint nodes conform to domain and range types (including subtype hierarchies).
- **`MAX_OUTGOING_EXCEEDED` / `MAX_INCOMING_EXCEEDED`**: Edge counts comply with declared cardinality constraints.
