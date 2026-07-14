"""Data analysis and feature extraction.

Profiles CSV datasets to determine modeling-relevant characteristics:
- Route of administration (IV bolus, IV infusion, extravascular)
- Dosing structure (RATE/DUR/CMT presence)
- Available covariates
- Sampling characteristics
- BQL (Below Quantitation Limit) presence
"""
import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


@dataclass
class DataFeatures:
    """Extracted features from a PopPK dataset."""
    # Column names found in the CSV header
    columns: List[str] = field(default_factory=list)
    # Route of administration
    route: str = "unknown"  # iv_bolus | iv_infusion | extravascular | mixed
    has_rate: bool = False
    has_dur: bool = False
    has_amt: bool = False
    # Compartment structure
    cmt_values: Set[int] = field(default_factory=set)
    # Covariates available
    continuous_covariates: List[str] = field(default_factory=list)
    categorical_covariates: List[str] = field(default_factory=list)
    # Sampling
    n_subjects: int = 0
    n_records: int = 0
    n_obs: int = 0  # observation records (EVID=0 or DV>0 without AMT)
    has_bql: bool = False
    has_evid: bool = False
    # Grouping
    grouping_factors: List[str] = field(default_factory=list)
    # mAb-specific
    drug_type_hint: str = "mAb"  # default assumption for this platform
    # Nonlinear PK detection
    has_nonlinear_pk: bool = False  # TMDD or Michaelis-Menten suspected
    dose_range: tuple = (0.0, 0.0)  # (min_dose, max_dose)

    @property
    def recommended_template(self) -> str:
        """Recommend the initial NONMEM template ID based on features.

        Always starts with the simplest linear model. Nonlinear PK (TMDD)
        is flagged separately — the AI engine can escalate to MM/TMDD
        if GOF diagnostics show nonlinear patterns.
        """
        if self.route == "iv_infusion":
            return "iv_infusion_1c_advan1_trans2"
        if self.route == "iv_bolus":
            return "iv_bolus_1c_advan1_trans2"
        if self.route == "extravascular":
            return "extravascular_1c_advan2_trans2"
        # Fallback: IV infusion (most common for mAb)
        return "iv_infusion_1c_advan1_trans2"

    @property
    def recommended_route_label(self) -> str:
        """Human-readable route label for prompts."""
        return {
            "iv_bolus": "IV bolus",
            "iv_infusion": "IV infusion",
            "extravascular": "extravascular (oral/subcutaneous)",
            "mixed": "mixed route",
            "unknown": "unknown route",
        }.get(self.route, self.route)


def analyze_dataset(csv_path: Path) -> DataFeatures:
    """Analyze a NONMEM-format CSV dataset and extract features.

    Args:
        csv_path: Path to the CSV data file.

    Returns:
        DataFeatures with detected characteristics.
    """
    features = DataFeatures()

    if not csv_path.exists():
        return features

    with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return features

        # Normalize header
        columns = [c.strip().strip('"').upper() for c in header]
        features.columns = columns
        col_set = set(columns)

        # Detect columns
        features.has_rate = "RATE" in col_set
        features.has_dur = "DUR" in col_set
        features.has_amt = "AMT" in col_set
        features.has_evid = "EVID" in col_set
        features.has_bql = "BQL" in col_set

        # Identify covariates
        covariate_names = {
            "WT", "AGE", "SEX", "RACE", "STUDY", "CRCL", "SCR", "ALB",
            "WT0", "AGE0", "BSA", "BMI", "ALT", "AST", "TBIL",
            "ADA", "IMM", "DISEASE", "DOSE", "REGIMEN",
        }
        for col in columns:
            if col in covariate_names:
                if col in ("SEX", "RACE", "STUDY", "DISEASE", "ADA", "IMM", "REGIMEN"):
                    features.categorical_covariates.append(col)
                else:
                    features.continuous_covariates.append(col)

        # Detect grouping factors
        for col in ("STUDY", "DOSE", "REGIMEN", "ARM", "TRT"):
            if col in col_set:
                features.grouping_factors.append(col)

        # Parse data rows
        cmt_idx = columns.index("CMT") if "CMT" in columns else -1
        evid_idx = columns.index("EVID") if "EVID" in columns else -1
        amt_idx = columns.index("AMT") if "AMT" in columns else -1
        dv_idx = columns.index("DV") if "DV" in columns else -1
        rate_idx = columns.index("RATE") if "RATE" in columns else -1
        dur_idx = columns.index("DUR") if "DUR" in columns else -1
        id_idx = columns.index("ID") if "ID" in columns else -1
        dose_idx = columns.index("DOSE") if "DOSE" in columns else -1

        subject_ids = set()
        has_dosing = False
        has_obs = False
        has_rate_value = False
        has_dur_value = False
        cmt_values = set()
        dose_values = set()
        min_dose = float('inf')
        max_dose = 0.0

        for row in reader:
            features.n_records += 1
            if id_idx >= 0 and id_idx < len(row):
                subject_ids.add(row[id_idx])

            # Parse CMT
            if cmt_idx >= 0 and cmt_idx < len(row):
                try:
                    cmt = int(float(row[cmt_idx]))
                    cmt_values.add(cmt)
                except (ValueError, IndexError):
                    pass

            # Parse EVID for dosing vs observation
            evid = 0
            if evid_idx >= 0 and evid_idx < len(row):
                try:
                    evid = int(float(row[evid_idx]))
                except (ValueError, IndexError):
                    pass

            # Check for dosing
            amt_val = 0
            if amt_idx >= 0 and amt_idx < len(row):
                try:
                    amt_val = float(row[amt_idx])
                except (ValueError, IndexError):
                    pass

            # Collect dose values for nonlinear PK detection
            if dose_idx >= 0 and dose_idx < len(row):
                try:
                    dose_val = float(row[dose_idx])
                    if dose_val > 0:
                        dose_values.add(dose_val)
                        min_dose = min(min_dose, dose_val)
                        max_dose = max(max_dose, dose_val)
                except (ValueError, IndexError):
                    pass

            if amt_val > 0 or evid in (1, 4):
                has_dosing = True
                if rate_idx >= 0 and rate_idx < len(row):
                    try:
                        rate_val = float(row[rate_idx])
                        if rate_val > 0:
                            has_rate_value = True
                    except (ValueError, IndexError):
                        pass
                if dur_idx >= 0 and dur_idx < len(row):
                    try:
                        dur_val = float(row[dur_idx])
                        if dur_val > 0:
                            has_dur_value = True
                    except (ValueError, IndexError):
                        pass

            # Check for observations
            dv_val = 0
            if dv_idx >= 0 and dv_idx < len(row):
                try:
                    dv_val = float(row[dv_idx])
                except (ValueError, IndexError):
                    pass
            if dv_val > 0 and (evid == 0 or amt_val == 0):
                has_obs = True
                features.n_obs += 1

        features.n_subjects = len(subject_ids)
        features.cmt_values = cmt_values
        features.has_rate = features.has_rate and has_rate_value
        features.has_dur = features.has_dur and has_dur_value

        # Store dose range
        if min_dose != float('inf'):
            features.dose_range = (min_dose, max_dose)

        # Detect potential nonlinear PK (TMDD)
        # If there are multiple dose levels spanning a wide range (>10x), 
        # and the drug type is mAb, suspect TMDD
        if len(dose_values) >= 3 and max_dose > 0:
            dose_ratio = max_dose / min_dose if min_dose > 0 else 0
            if dose_ratio >= 10:
                features.has_nonlinear_pk = True

        # Determine route
        features.route = _determine_route(
            has_dosing=has_dosing,
            has_obs=has_obs,
            has_rate=features.has_rate,
            has_dur=features.has_dur,
            cmt_values=cmt_values,
            columns=col_set,
        )

    return features


def _determine_route(has_dosing: bool, has_obs: bool, has_rate: bool,
                     has_dur: bool, cmt_values: Set[int],
                     columns: Set[str]) -> str:
    """Determine the route of administration from data features."""
    if not has_dosing:
        return "unknown"

    # IV infusion: RATE or DUR > 0, dosing into CMT=1
    if has_rate or has_dur:
        if cmt_values and min(cmt_values) >= 1:
            return "iv_infusion"

    # Extravascular: dosing into CMT=1, observations in CMT=2
    if cmt_values:
        if 1 in cmt_values and 2 in cmt_values:
            return "extravascular"

    # IV bolus: no RATE/DUR, dosing into CMT=1
    if cmt_values and 1 in cmt_values:
        return "iv_bolus"

    # If we can't tell, check for RATE/DUR columns existence
    if has_rate or has_dur:
        return "iv_infusion"

    return "iv_bolus"


def features_to_prompt(features: DataFeatures) -> str:
    """Convert data features to a text summary for LLM prompts."""
    nonlinear = "yes (TMDD suspected)" if features.has_nonlinear_pk else "no"
    dose_range = f"{features.dose_range[0]}-{features.dose_range[1]}" if features.dose_range[0] > 0 else "N/A"
    return f"""### Dataset Feature Summary

- **Route**: {features.recommended_route_label}
- **Columns**: {", ".join(features.columns)}
- **Records**: {features.n_records} total, {features.n_obs} observations, {features.n_subjects} subjects
- **Dosing**: RATE={'yes' if features.has_rate else 'no'}, DUR={'yes' if features.has_dur else 'no'}
- **Dose range**: {dose_range}
- **CMT values**: {sorted(features.cmt_values) if features.cmt_values else 'none'}
- **Continuous covariates**: {", ".join(features.continuous_covariates) or 'none'}
- **Categorical covariates**: {", ".join(features.categorical_covariates) or 'none'}
- **Grouping factors**: {", ".join(features.grouping_factors) or 'none'}
- **BQL column**: {'yes' if features.has_bql else 'no'}
- **Nonlinear PK**: {nonlinear}
- **Recommended initial template**: {features.recommended_template}
"""
