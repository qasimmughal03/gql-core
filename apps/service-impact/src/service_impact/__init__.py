"""Service dependency and impact analysis, built on the published gql-core package."""

from service_impact.analysis import Affected, ImpactAnalyzer, Step, UnknownComponent
from service_impact.catalog import CatalogError, build_graph, load_catalog

__all__ = ["Affected", "CatalogError", "ImpactAnalyzer", "Step", "UnknownComponent", "build_graph", "load_catalog"]
__version__ = "0.1.0"
