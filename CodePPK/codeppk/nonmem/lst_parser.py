"""LST file parser.

Extracts key results from NONMEM .lst output files:
- Objective Function Value (OFV)
- AIC
- Final parameter estimates with RSE
- Shrinkage statistics (ETASHRINKSD, EPSSHRINKSD)
- Control stream ($PK, $ERROR, $THETA, $OMEGA, $SIGMA)
- Error/warning messages (NMTRAN errors, FMSG)
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
    eta_shrink: float = 0.0  # Eta shrinkage SD (%)


@dataclass
class ResidualEstimate:
    """A residual (SIGMA) estimate."""
    name: str = ""
    estimate: float = 0.0
    rse: float = 0.0
    eps_shrink: float = 0.0  # EPS shrinkage SD (%)


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
    control_stream_theta: str = ""
    control_stream_omega: str = ""
    control_stream_sigma: str = ""
    error_messages: List[str] = field(default_factory=list)
    successful: bool = False  # True if estimation completed
    has_covariance: bool = False
    n_subjects: int = 0
    n_obs: int = 0
    n_theta: int = 0
    n_eta: int = 0
    n_eps: int = 0
    raw_text: str = ""

    @property
    def has_errors(self) -> bool:
        """True if the LST contains blocking errors (not just warnings)."""
        return any("WARNING" not in msg.upper() and "AN ERROR WAS FOUND" in msg.upper() for msg in self.error_messages)

    @property
    def has_warnings(self) -> bool:
        return len(self.error_messages) > 0

    def summary(self) -> str:
        """Human-readable summary of the results."""
        lines = [
            f"Run {self.run_id}: OFV={self.ofv}, AIC={self.aic}",
            f"Successful: {self.successful}, Covariance: {self.has_covariance}",
            f"Subjects: {self.n_subjects}, Obs: {self.n_obs}, THETAs: {self.n_theta}, ETAs: {self.n_eta}",
            f"Parameters: {len(self.parameters)}, Residuals: {len(self.residuals)}",
        ]
        if self.parameters:
            lines.append("Parameter estimates:")
            for p in self.parameters:
                lines.append(f"  {p.name}: {p.theta_value:.4g} (RSE={p.theta_rse:.1f}%, IIV={p.iiv_cv:.1f}%, Shrink={p.eta_shrink:.1f}%)")
        if self.residuals:
            lines.append("Residuals:")
            for r in self.residuals:
                lines.append(f"  {r.name}: {r.estimate:.4g} (RSE={r.rse:.1f}%, EPS Shrink={r.eps_shrink:.1f}%)")
        if self.error_messages:
            lines.append(f"Warnings/Errors: {len(self.error_messages)}")
            for err in self.error_messages[:3]:
                lines.append(f"  - {err[:150]}")
        return "\n".join(lines)


def _parse_scientific_values(text: str) -> List[float]:
    """Parse NONMEM scientific notation values from a line or block.

    Handles formats like:
    1.22E-02  4.30E+00  2.07E-02
    1.22E-02  .........  2.07E-02
    """
    values = []
    # Match scientific notation or decimal numbers, but not "........."
    for match in re.finditer(r"(?<![\.\d])(-?\d+\.\d+E[+-]?\d+|-?\d+\.\d+)(?![\.\d])", text):
        try:
            values.append(float(match.group(1)))
        except ValueError:
            pass
    return values


def _extract_theta_block(text: str) -> Tuple[List[float], List[float]]:
    """Extract THETA values and SEs from a FINAL/SE block.

    Returns (estimates, standard_errors).
    """
    # Find THETA section header
    theta_match = re.search(r"THETA - VECTOR OF FIXED EFFECTS PARAMETERS\s*\*+\s*\n(.*?)(?=OMEGA|SIGMA|COVARIANCE|$)", text, re.S)
    if not theta_match:
        return [], []

    theta_text = theta_match.group(1)
    # Find the header line with TH 1, TH 2, etc.
    header_match = re.search(r"(TH\s*\d+.*)", theta_text)
    n_theta = 0
    if header_match:
        n_theta = len(re.findall(r"TH\s*\d+", header_match.group(1)))

    # Find data lines (lines with scientific notation values)
    data_lines = []
    for line in theta_text.split("\n"):
        values = _parse_scientific_values(line)
        if values:
            data_lines.extend(values)

    return data_lines[:n_theta] if n_theta else data_lines, n_theta


def _extract_omega_diagonal(text: str, n_eta: int) -> List[float]:
    """Extract OMEGA diagonal values (variances) from a block.

    NONMEM format:
        ETA1
    +        2.14E-01

        ETA2
    +        0.00E+00  3.11E-02

    The diagonal value for ETA{n} is the n-th value on the ETA{n} line.
    """
    omega_match = re.search(
        r"OMEGA - COV MATRIX FOR RANDOM EFFECTS - ETAS\s*\*+\s*(.*?)(?=SIGMA - COV|OMEGA - CORR|$)",
        text, re.S
    )
    if not omega_match:
        return []

    omega_text = omega_match.group(1)
    diag_values = []

    # Find each ETA{n} block and extract the n-th value
    for i in range(1, n_eta + 1):
        # Pattern: ETA{i} \n + val1 val2 ... val{i}
        pattern = rf"ETA{i}\s*\n\+\s*((?:[\dE\.\+\-]+\s*){{1,{i}}})"
        match = re.search(pattern, omega_text)
        if match:
            vals = _parse_scientific_values(match.group(1))
            if vals and len(vals) >= i:
                diag_values.append(vals[i - 1])
            else:
                diag_values.append(0.0)
        else:
            diag_values.append(0.0)

    return diag_values


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

    # Extract counts
    n_subjects_match = re.search(r"TOT\. NO\. OF INDIVIDUALS:\s*(\d+)", content)
    if n_subjects_match:
        results.n_subjects = int(n_subjects_match.group(1))

    n_obs_match = re.search(r"TOT\. NO\. OF OBS RECS:\s*(\d+)", content)
    if n_obs_match:
        results.n_obs = int(n_obs_match.group(1))

    n_theta_match = re.search(r"LENGTH OF THETA:\s*(\d+)", content)
    if n_theta_match:
        results.n_theta = int(n_theta_match.group(1))

    # Check for successful estimation
    ofv_match = re.search(r"OBJECTIVE FUNCTION VALUE WITHOUT CONSTANT:\s*([\d\.\-]+)", content)
    if not ofv_match:
        ofv_match = re.search(r"#OBJV:\s*([\d\.\-]+)", content)
    if not ofv_match:
        ofv_match = re.search(r"MINIMUM VALUE OF OBJECTIVE FUNCTION.*?([\d\.\-]+)", content, re.S)

    if ofv_match:
        try:
            results.ofv = float(ofv_match.group(1))
            results.successful = True
        except ValueError:
            pass

    # Check for covariance step
    if re.search(r"COVARIANCE STEP\s*OF", content, re.I):
        results.has_covariance = True
    if re.search(r"R MATRIX ALGORITHMICALLY SINGULAR", content, re.I):
        results.has_covariance = False
    if re.search(r"COVARIANCE STEP ABORTED", content, re.I):
        results.has_covariance = False

    # Extract control stream blocks (from the echoed $PK, $ERROR etc.)
    pk_match = re.search(r"(\$PK[\s\S]*?)(?=\$ERROR|\$EST|$)", content)
    if pk_match:
        results.control_stream_pk = pk_match.group(0).strip()

    error_match = re.search(r"(\$ERROR[\s\S]*?)(?=\$THETA|\$OMEGA|\$SIGMA|\$EST|$)", content)
    if error_match:
        results.control_stream_error = error_match.group(0).strip()

    theta_match = re.search(r"(\$THETA[\s\S]*?)(?=\$OMEGA|\$SIGMA|\$EST|$)", content)
    if theta_match:
        results.control_stream_theta = theta_match.group(0).strip()

    omega_match = re.search(r"(\$OMEGA[\s\S]*?)(?=\$SIGMA|\$EST|$)", content)
    if omega_match:
        results.control_stream_omega = omega_match.group(0).strip()

    sigma_match = re.search(r"(\$SIGMA[\s\S]*?)(?=\$EST|$)", content)
    if sigma_match:
        results.control_stream_sigma = sigma_match.group(0).strip()

    # Extract warning/error messages
    error_patterns = [
        (r"AN ERROR WAS FOUND[\s\S]*?(?=\n\n|\*{10}|$)", "error"),
        (r"NMTRAN ERROR[\s\S]*?(?=\n\n|$)", "error"),
        (r"0ESTIMATION OF PARAMETER STEP WAS NOT SUCCESSFUL", "error"),
        (r"R MATRIX ALGORITHMICALLY SINGULAR", "error"),
        (r"COVARIANCE STEP ABORTED", "error"),
        (r"WARNINGS AND ERRORS[\s\S]*?(?=\n\n\n|1NONLINEAR|$)", "warning"),
        (r"\(WARNING\s+\d+\)[^\n]*", "warning"),
        (r"MINIMIZATION TERMINATED", "error"),
        (r"PARAMETER ESTIMATE IS NEAR ITS BOUNDARY", "warning"),
    ]
    for pattern, _severity in error_patterns:
        for match in re.finditer(pattern, content, re.I):
            msg = match.group(0).strip()[:500]
            if msg and msg not in results.error_messages:
                results.error_messages.append(msg)

    # Extract parameter estimates
    _extract_parameter_estimates(content, results)

    # Extract shrinkage
    _extract_shrinkage(content, results)

    return results


def _extract_parameter_estimates(content: str, results: LSTResults) -> None:
    """Extract final parameter estimates from the LST.

    NONMEM 7.5 format:
    - FINAL PARAMETER ESTIMATE block contains THETA values in a row
    - STANDARD ERROR OF ESTIMATE block contains SE values
    - OMEGA block contains IIV variances (diagonal)
    - SIGMA block contains residual variances
    """
    # Find the FINAL PARAMETER ESTIMATE block
    est_section = re.search(
        r"FINAL PARAMETER ESTIMATE.*?THETA - VECTOR OF FIXED EFFECTS PARAMETERS\s*\*+\s*(.*?)(?=OMEGA - COV|$)",
        content, re.S
    )
    if not est_section:
        return

    est_text = est_section.group(0)

    # Find SE block
    se_section = re.search(
        r"STANDARD ERROR OF ESTIMATE.*?THETA - VECTOR OF FIXED EFFECTS PARAMETERS\s*\*+\s*(.*?)(?=OMEGA - COV|$)",
        content, re.S
    )

    # Extract THETA header to get count and names
    theta_header = re.search(r"(TH\s*\d+.*)", est_text)
    theta_names = []
    n_theta = 0
    if theta_header:
        theta_names = re.findall(r"TH\s*(\d+)", theta_header.group(1))
        n_theta = len(theta_names)

    # Extract THETA estimate values — find the first line with actual numbers after the header
    theta_values = []
    # Skip the header line (TH 1 ...), then find the first data line
    lines = est_text.split("\n")
    for line in lines:
        # Skip header lines and empty lines
        if re.match(r"^\s*(TH\s*\d+|$)", line):
            continue
        vals = _parse_scientific_values(line)
        if vals:
            theta_values = vals
            break

    # Extract SE values
    theta_se_values = []
    if se_section:
        se_text = se_section.group(0)
        se_lines = se_text.split("\n")
        for line in se_lines:
            if re.match(r"^\s*(TH\s*\d+|$)", line):
                continue
            vals = _parse_scientific_values(line)
            if vals:
                theta_se_values = vals
                break
        # If no direct values found, try to parse with dots handling
        if not theta_se_values:
            for line in se_lines:
                if re.match(r"^\s*(TH\s*\d+|$)", line):
                    continue
                # Parse SE values, treating "........." as not estimable
                se_parts = re.findall(r"(-?\d+\.\d+E[+-]?\d+|\.{5,})", line)
                if se_parts:
                    for part in se_parts:
                        if part.startswith("..."):
                            theta_se_values.append(None)
                        else:
                            try:
                                theta_se_values.append(float(part))
                            except ValueError:
                                theta_se_values.append(None)
                    break

    # Extract $PK parameter names from THETA comments
    pk_names = _extract_theta_names_from_pk(results)

    # Extract OMEGA diagonal for IIV
    # First, find number of ETAs from OMEGA header
    eta_header_match = re.search(r"ETA\d+.*?(?:\n|$)", est_text)
    n_eta = len(re.findall(r"ETA\d+", eta_header_match.group(0))) if eta_header_match else 0
    omega_diag = _extract_omega_diagonal(est_text, n_eta)
    results.n_eta = n_eta

    # Build parameter estimates
    for i in range(n_theta):
        name = pk_names[i] if i < len(pk_names) else f"THETA{i+1}"
        value = theta_values[i] if i < len(theta_values) else 0.0

        rse = 0.0
        if i < len(theta_se_values) and theta_se_values[i] is not None and value != 0:
            rse = abs(theta_se_values[i] / value) * 100

        iiv_cv = 0.0
        if i < len(omega_diag) and omega_diag[i] > 0:
            iiv_cv = (omega_diag[i] ** 0.5) * 100

        results.parameters.append(ParameterEstimate(
            name=name,
            theta_value=value,
            theta_rse=rse,
            iiv_cv=iiv_cv,
        ))

    # Extract SIGMA
    sigma_match = re.search(r"SIGMA - COV MATRIX FOR RANDOM EFFECTS - EPSILONS\s*\*+\s*(.*?)(?=1$|\*{10}|OMEGA - CORR|$)", est_text, re.S)
    if sigma_match:
        sigma_text = sigma_match.group(1)
        # Find EPS values
        for match in re.finditer(r"EPS(\d+)\s*\n\+\s*([\dE\.\+\-]+)", sigma_text):
            eps_idx = int(match.group(1))
            eps_val = float(match.group(2))
            results.residuals.append(ResidualEstimate(
                name=f"EPS{eps_idx}",
                estimate=eps_val,
            ))
            results.n_eps = max(results.n_eps, eps_idx)

    results.n_theta = n_theta


def _extract_theta_names_from_pk(results: LSTResults) -> List[str]:
    """Extract parameter names from $PK block comments.

    Looks for patterns like:
    TVCL = THETA(1) ; CL_L/h
    TVV1 = THETA(2) ; V1_L
    """
    names = []
    pk_text = results.control_stream_pk
    if not pk_text:
        return names

    # Find all THETA(n) references with comments
    for match in re.finditer(r"THETA\((\d+)\)[^\n;]*;([^\n]+)", pk_text):
        idx = int(match.group(1))
        name = match.group(2).strip()
        # Pad list
        while len(names) < idx:
            names.append(f"THETA{len(names)+1}")
        names[idx - 1] = name

    return names


def _extract_shrinkage(content: str, results: LSTResults) -> None:
    """Extract shrinkage statistics from the LST.

    NONMEM 7.5 format:
    ETASHRINKSD(%)  2.6973E+00  9.1576E+00  ...
    EPSSHRINKSD(%)  8.6828E+00
    """
    # ETASHRINKSD
    eta_shrink_match = re.search(r"ETASHRINKSD\(%\)\s*((?:[\dE\.\+\-\s]+))", content)
    if eta_shrink_match:
        eta_shrinks = _parse_scientific_values(eta_shrink_match.group(1))
        for i, shrink_val in enumerate(eta_shrinks):
            if i < len(results.parameters):
                results.parameters[i].eta_shrink = shrink_val

    # EPSSHRINKSD
    eps_shrink_match = re.search(r"EPSSHRINKSD\(%\)\s*((?:[\dE\.\+\-\s]+))", content)
    if eps_shrink_match:
        eps_shrinks = _parse_scientific_values(eps_shrink_match.group(1))
        for i, shrink_val in enumerate(eps_shrinks):
            if i < len(results.residuals):
                results.residuals[i].eps_shrink = shrink_val
            else:
                results.residuals.append(ResidualEstimate(
                    name=f"EPS{i+1}",
                    eps_shrink=shrink_val,
                ))


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
