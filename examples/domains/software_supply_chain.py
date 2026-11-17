"""
Domain Demonstration 2: Software Supply Chain & Vulnerability Impact Reasoning.

This demonstrates how GQL-Core is used to model software package dependency trees,
microservices, and automatically reason about transitive CVE vulnerabilities.

Use Case:
- Services depend on packages (DEPENDS_ON).
- Packages depend on other packages (transitive dependencies).
- When a transitive package has a critical CVE, GQL-Core infers whether an upstream
  production service is VULNERABLE through multi-tier reachability.
"""

from gql_core import PropertyGraph, Node, Edge, run
from gql_core.inference import (
    InferenceEngine,
    make_transitive_rule,
    make_composition_rule,
)


def run_supply_chain_demonstration():
    print("=" * 70)
    print(" GQL-Core Domain Demo 2: Software Supply Chain & Vulnerability Reasoning")
    print("=" * 70)

    # 1. Initialize property graph
    graph = PropertyGraph()

    # 2. Add Services and Packages
    graph.add_node(Node("svc_billing", "Service", {"name": "BillingService", "tier": "critical"}))
    graph.add_node(Node("pkg_auth", "Package", {"name": "auth-jwt", "version": "2.4.0"}))
    graph.add_node(Node("pkg_crypto", "Package", {"name": "crypto-core", "version": "1.0.1"}))
    graph.add_node(Node("pkg_parser", "Package", {"name": "xml-fast-parse", "version": "0.9.3"}))

    # Dependencies: BillingService -> auth-jwt -> crypto-core -> xml-fast-parse
    graph.add_edge(Edge("e1", "DEPENDS_ON", "svc_billing", "pkg_auth"))
    graph.add_edge(Edge("e2", "DEPENDS_ON", "pkg_auth", "pkg_crypto"))
    graph.add_edge(Edge("e3", "DEPENDS_ON", "pkg_crypto", "pkg_parser"))

    # Vulnerability assertion
    graph.add_node(Node("cve_2026_9999", "Vulnerability", {"cve": "CVE-2026-9999", "severity": "CRITICAL"}))
    graph.add_edge(Edge("v1", "HAS_CVE", "pkg_parser", "cve_2026_9999"))

    print("\n[Step 1] Querying 3-hop dependency chain using Cypher variable-length paths...")
    path_query = """
        MATCH (s:Service)-[:DEPENDS_ON*1..3]->(p:Package)
        RETURN s.name AS service, p.name AS transitive_dep, p.version AS version
        ORDER BY transitive_dep ASC
    """
    for row in run(path_query, graph):
        print(f"  * Service '{row['service']}' transitively depends on: {row['transitive_dep']} (v{row['version']})")

    # 3. Setup Ontological Inference Engine
    # Rule 1: DEPENDS_ON is transitive (Service -> Auth -> Crypto -> Parser implies Service DEPENDS_ON Parser)
    # Rule 2: Composition: If ?x DEPENDS_ON ?y and ?y HAS_CVE ?z -> ?x EXPOSED_TO ?z
    engine = InferenceEngine()
    engine.add_rule(make_transitive_rule("DEPENDS_ON"))
    engine.add_rule(make_composition_rule("EXPOSED_TO", "DEPENDS_ON", "HAS_CVE"))

    print("\n[Step 2] Executing Fixed-Point Vulnerability Inference...")
    facts_by_rel, derived_facts = engine.infer(graph)

    # Inspect derived exposure facts
    exposures = [f for f in derived_facts if f.predicate == "rel" and f.args[1] == "EXPOSED_TO"]
    for f in exposures:
        src, rel, dst = f.args
        print(f"  [SECURITY IMPACT] Entity '{src}' is inferred '{rel}' '{dst}'")
        print(f"  [PROVENANCE]      Inferred via rule: '{f.rule_name}'")

    # 4. Materialize into the graph and query directly
    engine.materialize(graph)

    print("\n[Step 3] Querying materialized security report for production services...")
    vuln_query = """
        MATCH (s:Service)-[:EXPOSED_TO]->(v:Vulnerability)
        RETURN s.name AS service, s.tier AS tier, v.cve AS cve, v.severity AS severity
    """
    for item in run(vuln_query, graph):
        print(f"  * ACTION REQUIRED: {item['tier'].upper()} service '{item['service']}' is exposed to {item['cve']} [{item['severity']}]!")

    print("\nDemonstration 2 (Software Supply Chain) executed successfully.\n")


if __name__ == "__main__":
    run_supply_chain_demonstration()
