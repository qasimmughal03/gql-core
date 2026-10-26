"""Smoke tests for public runnable user examples."""

from __future__ import annotations

import importlib


def test_quickstart_example():
    """Verify examples/quickstart.py executes without error."""
    mod = importlib.import_module("examples.quickstart")
    assert callable(mod.main)
    mod.main()


def test_example_a_graph_querying():
    """Verify examples/example_a_graph_query.py executes without error."""
    mod = importlib.import_module("examples.example_a_graph_query")
    assert callable(mod.main)
    mod.main()


def test_example_b_typed_query_plans():
    """Verify examples/example_b_typed_plan.py executes without error."""
    mod = importlib.import_module("examples.example_b_typed_plan")
    assert callable(mod.main)
    mod.main()


def test_example_c_ontology_inference():
    """Verify examples/example_c_ontology_inference.py executes without error."""
    mod = importlib.import_module("examples.example_c_ontology_inference")
    assert callable(mod.main)
    mod.main()
