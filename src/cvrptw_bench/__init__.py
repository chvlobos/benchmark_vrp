"""CVRPTW with heterogeneous fleet benchmark: Clarke-Wright vs OR-Tools vs Hexaly.

Package layout
--------------
core       shared data model (instance, solution), integer matrices, validator
generator  synthetic instance generator for Greater Santiago (Phase 1)
solvers    solver adapters behind one common interface (Phases 3-5)
viz        maps and x-t (Gantt) plots (Phase 2)
report     aggregation and HTML report (Phase 6)
"""

__version__ = "0.1.0"
