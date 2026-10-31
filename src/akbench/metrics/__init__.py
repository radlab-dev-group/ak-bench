"""Metrics: the catalog, per-run collection and aggregation (plan section 18).

Two invariants shape the whole module:

- a metric is a measurement, not a statement: anything that cannot be
  measured is reported as ``unavailable`` with a reason, never as zero
  (zero claims "the effect did not happen");
- a faster or cheaper variant is not a better one: deltas are reported next
  to the quality metrics that decide the outcome, so an efficiency gain can
  never be read as success on its own.
"""

from akbench.metrics.aggregate import AggregatedMetrics, aggregate_runs, baseline_deltas
from akbench.metrics.catalog import MetricCatalog
from akbench.metrics.collect import MetricValue, collect_run_metrics

__all__ = [
    "AggregatedMetrics",
    "MetricCatalog",
    "MetricValue",
    "aggregate_runs",
    "baseline_deltas",
    "collect_run_metrics",
]
