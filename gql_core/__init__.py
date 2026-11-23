"""GQL-Core: A generic property-graph query engine with formal grammar and typed logical reasoning.

GQL-Core implements:
1. ISO/IEC 39075:2024 (GQL) read-only query execution (MATCH ... WHERE ... RETURN with RPQ and full aggregation)
2. Canonical typed logical intermediate representation (IR) with relational and graph algebra
3. Full Boolean predicate composition (3VL Kleene logic, correlated EXISTS/NOT_EXISTS)
4. Quantified relationship reasoning (ANY, ALL, NONE, SINGLE, AT_LEAST, AT_MOST, EXACTLY)
5. Set algebra (UNION, UNION ALL, INTERSECT, EXCEPT)
6. Typed temporal domain (Date, Time, DateTime, Duration, Interval)
7. Declarative ontology schemas with subtype hierarchies and cardinality constraints
8. Deterministic Datalog-like ontology inference engine with provenance and CWA/OWA support
9. Fluent programmatic query builder API and LLM-facing operator registry.
"""

__version__ = "0.2.0a4"

# Graph store and legacy components
from gql_core.ai import ask, translate_to_gql
from gql_core.builder import (
    PlanBuilder,
    all_rel,
    and_,
    any_rel,
    at_least_rel,
    avg,
    between,
    case_when,
    coalesce,
    col,
    collect,
    contains,
    count,
    ends_with,
    eq,
    exists,
    gt,
    gte,
    in_,
    is_missing,
    is_not_null,
    is_null,
    is_present,
    lit,
    lt,
    lte,
    max_,
    min_,
    neq,
    none_rel,
    not_,
    not_between,
    not_exists,
    not_in,
    or_,
    pattern,
    prop,
    quantified_rel,
    regex,
    single_rel,
    starts_with,
    sum_,
    var,
)
from gql_core.graph import Edge, Node, Path, PropertyGraph
from gql_core.inference import (
    Atom,
    Fact,
    InferenceEngine,
    InferenceRule,
    make_composition_rule,
    make_inverse_rule,
    make_subtype_rule,
    make_symmetric_rule,
    make_transitive_rule,
)
from gql_core.ingester import GraphIngester, IngestReport
from gql_core.ontology import (
    CardinalityConstraint,
    EntityType,
    OntologySchema,
    OntologyViolationError,
    PropertyDef,
    ReasoningMode,
    RelationshipType,
)
from gql_core.query.directions import DirectionCorrection, correct_relationship_directions, schema_triples
from gql_core.query.executor import run as run_query
from gql_core.query.parser import parse
from gql_core.query.planner import plan
from gql_core.query.values import ValueGrounding, ground_values
from gql_core.registry import OperatorMetadata, OperatorRegistry, execute_plan
from gql_core.temporal import Date, DateTime, Duration, Interval, TemporalTypeError, Time
from gql_core.types import DataType, TypeErrorDiagnostic
from gql_core.validator import ShapeValidator, ShapeViolationError
from gql_core.validator_ir import PlanValidationError, ValidationReport, validate_logical_plan

run = run_query

__all__ = [
    "__version__",
    "all_rel",
    "and_",
    "any_rel",
    "ask",
    "at_least_rel",
    "Atom",
    "avg",
    "between",
    "CardinalityConstraint",
    "case_when",
    "coalesce",
    "col",
    "collect",
    "contains",
    "correct_relationship_directions",
    "count",
    "DataType",
    "DirectionCorrection",
    "Date",
    "DateTime",
    "Duration",
    "Edge",
    "ends_with",
    "EntityType",
    "eq",
    "execute_plan",
    "exists",
    "ground_values",
    "Fact",
    "GraphIngester",
    "gt",
    "gte",
    "in_",
    "InferenceEngine",
    "InferenceRule",
    "IngestReport",
    "Interval",
    "is_missing",
    "is_not_null",
    "is_null",
    "is_present",
    "lit",
    "lt",
    "lte",
    "make_composition_rule",
    "make_inverse_rule",
    "make_subtype_rule",
    "make_symmetric_rule",
    "make_transitive_rule",
    "max_",
    "min_",
    "neq",
    "Node",
    "none_rel",
    "not_",
    "not_between",
    "not_exists",
    "not_in",
    "OntologySchema",
    "OntologyViolationError",
    "OperatorMetadata",
    "OperatorRegistry",
    "or_",
    "parse",
    "pattern",
    "plan",
    "PlanBuilder",
    "PlanValidationError",
    "prop",
    "PropertyDef",
    "PropertyGraph",
    "quantified_rel",
    "ReasoningMode",
    "regex",
    "RelationshipType",
    "run",
    "run_query",
    "schema_triples",
    "ShapeValidator",
    "ShapeViolationError",
    "single_rel",
    "starts_with",
    "sum_",
    "TemporalTypeError",
    "Time",
    "translate_to_gql",
    "TypeErrorDiagnostic",
    "validate_logical_plan",
    "ValidationReport",
    "ValueGrounding",
    "var",
]
