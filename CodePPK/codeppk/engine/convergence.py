"""Convergence criteria for the automated modeling loop.

Determines when the modeling process has converged or should stop.
"""
from dataclasses import dataclass
from typing import Optional

from ..nonmem.lst_parser import LSTResults


@dataclass
class ConvergenceStatus:
    """Status of the modeling convergence check."""
    converged: bool
    reason: str
    should_stop: bool = False
    details: str = ""


def check_convergence(lst_results: LSTResults, iteration: int,
                      max_iterations: int = 10,
                      prev_ofv: Optional[float] = None,
                      min_delta_ofv: float = 3.84,
                      max_rse: float = 30.0,
                      max_shrinkage: float = 30.0) -> ConvergenceStatus:
    """Check if the modeling process has converged.

    Convergence criteria:
    1. Estimation successful with covariance step
    2. No error messages
    3. All parameter RSE < max_rse (default 30%)
    4. All shrinkage < max_shrinkage (default 30%)
    5. Delta OFV from previous iteration < min_delta_ofv (diminishing returns)
    6. Not exceeded max_iterations

    Args:
        lst_results: Current LST results.
        iteration: Current iteration number.
        max_iterations: Maximum allowed iterations.
        prev_ofv: OFV from the previous iteration.
        min_delta_ofv: Minimum meaningful OFV change.
        max_rse: Maximum acceptable RSE (%).
        max_shrinkage: Maximum acceptable shrinkage (%).

    Returns:
        ConvergenceStatus with convergence information.
    """
    # Check iteration limit
    if iteration >= max_iterations:
        return ConvergenceStatus(
            converged=False,
            reason=f"Reached max iterations ({max_iterations})",
            should_stop=True,
        )

    # Check for estimation failure
    if not lst_results.successful:
        return ConvergenceStatus(
            converged=False,
            reason="Estimation not successful",
            should_stop=False,
        )

    # Check for errors
    if lst_results.has_errors:
        return ConvergenceStatus(
            converged=False,
            reason=f"Model has {len(lst_results.error_messages)} error(s)",
            should_stop=False,
        )

    # Check RSE
    high_rse_params = []
    for p in lst_results.parameters:
        if p.theta_rse > max_rse:
            high_rse_params.append(f"{p.name} (RSE={p.theta_rse:.1f}%)")

    # Check shrinkage
    high_shrink_params = []
    for p in lst_results.parameters:
        if p.eta_shrink > max_shrinkage:
            high_shrink_params.append(f"{p.name} (shrink={p.eta_shrink:.1f}%)")

    # Check OFV improvement
    ofv_stable = False
    if prev_ofv is not None and lst_results.ofv is not None:
        delta = abs(lst_results.ofv - prev_ofv)
        ofv_stable = delta < min_delta_ofv

    # Build convergence assessment
    issues = []
    if high_rse_params:
        issues.append(f"High RSE: {', '.join(high_rse_params[:3])}")
    if high_shrink_params:
        issues.append(f"High shrinkage: {', '.join(high_shrink_params[:3])}")

    if not issues and lst_results.has_covariance:
        if ofv_stable:
            return ConvergenceStatus(
                converged=True,
                reason="All criteria met and OFV is stable",
                should_stop=True,
                details="Model has converged. Consider running VPC and bootstrap for final validation.",
            )
        return ConvergenceStatus(
            converged=True,
            reason="All criteria met (OFV still improving)",
            should_stop=False,
            details="Model looks good but may improve further with additional iterations.",
        )

    return ConvergenceStatus(
        converged=False,
        reason="; ".join(issues) if issues else "Model needs further optimization",
        should_stop=False,
        details=f"OFV: {lst_results.ofv}, Covariance: {lst_results.has_covariance}",
    )
