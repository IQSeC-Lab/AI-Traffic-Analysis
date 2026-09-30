"""
The capture experiments (2, 3, 5 and 6 of the repo), exposed under /api/<slug>.

They share one engine (engine.py), GPU scheduler and queue (scheduler.py), analytics
(analysis.py) and Docker build context (toolbox/); each experiment module defines
its settings and the variants a run compares.
"""
