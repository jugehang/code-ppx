"""Closed-loop automation engine.

Orchestrates the full modeling cycle:
data profiling -> template selection -> model generation ->
NONMEM execution -> LST diagnosis -> GOF/VPC audit ->
optimization decision -> convergence check -> finalize
"""
