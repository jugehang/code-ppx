"""LST file parser.

Extracts key results from NONMEM .lst output files:
- Objective Function Value (OFV)
- AIC
- Final parameter estimates with RSE
- Shrinkage statistics
- Control stream ($PK, $ERROR, $THETA, $OMEGA, $SIGMA)
- Error messages (NMTRAN errors, FMSG)
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class ParameterEstimate:
    """A single parameter estimate from the LST."""
    name: str = ""
    theta_value: float = 0.0
    theta_rse: float = 0.0  # Relative standard error (%)
    iiv_cv: float = 0.0  # IIV coefficient of variation (%)
    eta_shrink: float = 0.0  # Eta shrinkage (%)


@dataclass
class ResidualEstimate:
    """A residual (SIGMA) estimate."""
    name: str = ""
    estimate: float = 0.0
    rse: float = 0.0
    eps_shrink: float = 0.0


@dataclass
class LSTResults:
    """Parsed results from a NONMEM .lst file."""
    run_id: str = ""
    ofv: Optional[float] = None
    aic: Optional[float] = None
    bic: Optional[float] = None
    parameters: List[ParameterEstimate] = field(default_factory=list)
    residuals: List[ResidualEstimate] = field(default_factory=list)
    control_stream_pk: str = ""
    control_stream_error: str = ""
    error_messages: List[str] = field(default_factory=list)
    successful: bool = False  # True if estimation completed
    has_covariance: bool = False
    raw_text: str = ""

    @property
    def has_errors(self) -> bool:
        """True if the LST contains NMTRAN or estimation errors."""
        return len(self.error_messages) > 0

    def summary(self) -> str:
        """Human-readable summary of the results."""
        lines = [
            f"Run {self.run_id}: OFV={self.ofv}, AIC={self.aic}",
            f"Successful: {self.successful}, Covariance: {self.has_covariance}",
            f"Parameters: {len(self.parameters)}, Residuals: {len(self.residuals)}",
        ]
        if self.has_errors:
            lines.append(f"Errors: {len(self.error_messages)}")
            for err in self.error_messages[:5]:
                lines.append(f"  - {err}")
        return "\n".join(lines)


def parse_lst(lst_path: Path, run_id: str = "") -> LSTResults:
    """Parse a NONMEM .lst file and extract key results.

    Args:
        lst_path: Path to the .lst file.
        run_id: Optional run ID for labeling.

    Returns:
        LSTResults with extracted information.
    """
    results = LSTResults(run_id=run_id)

    if not lst_path.exists():
        results.error_messages.append(f"LST file not found: {lst_path}")
        return results

    content = lst_path.read_text(encoding="utf-8", errors="ignore")
    results.raw_text = content

    # Check for successful estimation
    if re.search(r"#OBJV:|MINIMUM VALUE OF OBJECTIVE FUNCTION", content):
        results.successful = True

    # Check for covariance step success
    if re.search(r"COVARIANCE STEP.*SUCCESSFUL", content, re.I):
        results.has_covariance = True

    # Extract OFV
    ofv_match = re.search(r"#OBJV:\s*([\d\.\-]+)", content)
    if ofv_match:
        try:
            results.ofv = float(ofv_match.group(1))
        except ValueError:
            pass
    else:
        ofv_match = re.search(
            r"MINIMUM VALUE OF OBJECTIVE FUNCTION.*?([\d\.\-]+)", content, re.S
        )
        if ofv_match:
            try:
                results.ofv = float(ofv_match.group(1))
            except ValueError:
                pass

    # Extract AIC
    aic_match = re.search(r"AIC\s*[:=]?\s*([\d\.\-]+)", content)
    if aic_match:
        try:
            results.aic = float(aic_match.group(1))
        except ValueError:
            pass

    # Extract BIC
    bic_match = re.search(r"BIC\s*[:=]?\s*([\d\.\-]+)", content)
    if bic_match:
        try:
            results.bic = float(bic_match.group(1))
        except ValueError:
            pass

    # Extract control stream blocks
    pk_match = re.search(r"(\$PK[\s\S]*?)(?=\$ERROR|\$EST|$)", content)
    if pk_match:
        results.control_stream_pk = pk_match.group(0).strip()

    error_match = re.search(r"(\$ERROR[\s\S]*?)(?=\$THETA|\$OMEGA|\$SIGMA|\$EST|$)", content)
    if error_match:
        results.control_stream_error = error_match.group(0).strip()

    # Extract error messages
    error_patterns = [
        r"AN ERROR WAS FOUND[\s\S]*?(?=\n\n|\$)",
        r"NMtran failed[\s\S]*?(?=\n\n|\$)",
        r"There is no output[\s\S]*?(?=\n\n|\$)",
        r"Could not parse the output file[\s\S]*?(?=\n\n|\$)",
        r"FMSG[\s\S]*?(?=\n\n|\$)",
        r"WARNING[\s\S]*?(?=\n\n|\$)",
        r"0ESTIMATION OF PARAMETER STEP WAS NOT SUCCESSFUL",
        r"R MATRIX ALGORITHMICALLY SINGULAR",
        r"COVARIANCE STEP ABORTED",
    ]
    for pattern in error_patterns:
        for match in re.finditer(pattern, content, re.I):
            msg = match.group(0).strip()[:500]
            if msg and msg not in results.error_messages:
                results.error_messages.append(msg)

    # Extract final parameter estimates
    _extract_parameter_estimates(content, results)

    # Extract shrinkage
    _extract_shrinkage(content, results)

    return results


def _extract_parameter_estimates(content: str, results: LSTResults) -> None:
    """Extract final parameter estimates from the LST."""
    # Find the FINAL PARAMETER ESTIMATE block
    est_match = re.search(
        r"FINAL PARAMETER ESTIMATE[\s\S]*?(?=\s*\d+\s+TOTAL)",
        content
    )
    se_match = re.search(
        r"STANDARD ERROR OF ESTIMATE[\s\S]*?(?=\s*\d+\s+TOTAL)",
        content
    )

    if not est_match:
        return

    est_text = est_match.group(0)
    se_text = se_match.group(0) if se_match else ""

    # Parse THETA estimates
    theta_section = re.search(
        r"THETA -([\s\S]*?)(?=OMEGA|SIGMA|TOTAL|$)",
        est_text
    )
    if theta_section:
        theta_lines = theta_section.group(1).strip().split("\n")
        se_theta_lines = []
        if se_match:
            se_theta = re.search(r"THETA -([\s\S]*?)(?=OMEGA|SIGMA|TOTAL|$)", se_text)
            if se_theta:
                se_theta_lines = se_theta.group(1).strip().split("\n")

        for i, line in enumerate(theta_lines):
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    value = float(parts[-1])
                    name = parts[0] if not parts[0].replace(".", "").replace("-", "").isdigit() else f"THETA{i+1}"
                    rse = 0.0
                    if i < len(se_theta_lines):
                        se_parts = se_theta_lines[i].strip().split()
                        if se_parts:
                            try:
                                se_value = float(se_parts[-1])
                                if value != 0:
                                    rse = abs(se_value / value) * 100
                            except ValueError:
                                pass
                    results.parameters.append(ParameterEstimate(
                        name=name,
                        theta_value=value,
                        theta_rse=rse,
                    ))
                except ValueError:
                    pass


def _extract_shrinkage(content: str, results: LSTResults) -> None:
    """Extract shrinkage statistics from the LST."""
    shrink_match = re.search(r"ETABAR:[\s\S]*?EPSSHRINKVR.*", content)
    if not shrink_match:
        return

    shrink_text = shrink_match.group(0)

    # Parse eta shrinkage values
    eta_lines = re.findall(r"ETA\s*\d+\s+([\d\.\-]+)\s+([\d\.\-]+)", shrink_text)
    for eta_val, shrink_val in eta_lines:
        try:
            shrink_pct = float(shrink_val) * 100 if float(shrink_val) < 1 else float(shrink_val)
            if results.parameters:
                # Attach to the corresponding parameter
                idx = len(results.parameters) - len(eta_lines) + len(results.parameters) % len(eta_lines)
                if 0 <= idx < len(results.parameters):
                    results.parameters[idx].eta_shrink = shrink_pct
        except (ValueError, IndexError):
            pass

    # Parse eps shrinkage
    eps_lines = re.findall(r"EPS\s*\d+\s+([\d\.\-]+)\s+([\d\.\-]+)", shrink_text)
    for eps_val, shrink_val in eps_lines:
        try:
            shrink_pct = float(shrink_val) * 100 if float(shrink_val) < 1 else float(shrink_val)
            results.residuals.append(ResidualEstimate(
                name=f"EPS{len(results.residuals)+1}",
                eps_shrink=shrink_pct,
            ))
        except ValueError:
            pass


def compare_runs(prev: LSTResults, curr: LSTResults) -> Dict:
    """Compare two LST results and compute deltas.

    Args:
        prev: Previous run results.
        curr: Current run results.

    Returns:
        Dictionary with delta OFV, parameter changes, and status.
    """
    delta_ofv = None
    if prev.ofv is not None and curr.ofv is not None:
        delta_ofv = round(curr.ofv - prev.ofv, 3)

    return {
        "delta_ofv": delta_ofv,
        "prev_ofv": prev.ofv,
        "curr_ofv": curr.ofv,
        "significant": abs(delta_ofv) > 3.84 if delta_ofv is not None else False,
        "curr_successful": curr.successful,
        "curr_has_errors": curr.has_errors,
        "n_parameters": len(curr.parameters),
        "n_errors": len(curr.error_messages),
    }
