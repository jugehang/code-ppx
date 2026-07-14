"""Closed-loop automated modeling engine.

Orchestrates the full PopPK modeling cycle:
1. Analyze dataset features
2. Select initial template
3. Generate .mod file
4. Validate and auto-fix
5. Run NONMEM
6. Parse LST output
7. Generate GOF/VPC diagnostics
8. AI audits (LST parameters, GOF, VPC)
9. LLM decides next optimization step
10. Apply optimization
11. Repeat until convergence or max iterations
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from ..config import LLMConfig, ProjectConfig
from ..data.features import analyze_dataset, features_to_prompt
from ..diagnostics.gof import audit_gof
from ..diagnostics.vpc import audit_vpc
from ..llm.base import BaseLLMProvider
from ..llm.factory import create_provider
from ..models.generator import (
    generate_initial_model,
    validate_and_autofix,
    HAS_GENERATOR,
    HAS_TEMPLATES,
)
from ..nonmem.lst_parser import parse_lst, compare_runs
from ..nonmem.runner import run_nonmem, run_psn_vpc
from ..rules.loader import RuleLibrary
from .convergence import check_convergence, ConvergenceStatus
from .decisions import make_decision, ActionType, ModelDecision

LogFn = Callable[[str], None]


@dataclass
class IterationResult:
    """Result of a single modeling iteration."""
    iteration: int
    run_id: str
    action_taken: ActionType
    decision: ModelDecision
    ofv: Optional[float] = None
    convergence: Optional[ConvergenceStatus] = None
    gof_report: str = ""
    vpc_report: str = ""
    notes: str = ""


@dataclass
class ModelingResult:
    """Final result of the automated modeling loop."""
    iterations: List[IterationResult] = field(default_factory=list)
    final_run_id: str = ""
    final_ofv: Optional[float] = None
    converged: bool = False
    reason: str = ""
    final_mod_path: Optional[Path] = None
    final_lst_path: Optional[Path] = None


class ModelingLoop:
    """The main automated PopPK modeling loop.

    This is the core orchestrator that ties together all components:
    - Data analysis
    - Model generation
    - NONMEM execution
    - LST parsing
    - Diagnostic generation
    - AI visual audits
    - LLM-driven optimization decisions
    - Convergence checking

    Usage:
        loop = ModelingLoop(config, log_fn)
        result = loop.run()
    """

    def __init__(self, project_config: ProjectConfig, llm_config: LLMConfig,
                 log: LogFn = print, max_iterations: int = 10,
                 start_run_id: int = 1):
        self.project = project_config
        self.llm_config = llm_config
        self.log = log
        self.max_iterations = max_iterations
        self.current_run_id = start_run_id
        self.prev_run_id = ""

        # Initialize components
        self.llm = create_provider(llm_config)
        self.vision_llm = create_provider(llm_config.resolve_vision())
        self.rules = RuleLibrary(
            rules_file=project_config.rules_file,
            base_dir=project_config.rules_base_dir,
        ).load()

    def run(self) -> ModelingResult:
        """Run the full automated modeling loop.

        Returns:
            ModelingResult with the final outcome.
        """
        result = ModelingResult()
        self.log(f"=== Starting automated PopPK modeling loop ===")
        self.log(f"Project: {self.project.project_path}")
        self.log(f"LLM: {self.llm_config.provider} / {self.llm_config.model_id}")
        self.log(f"Max iterations: {self.max_iterations}")

        # Step 1: Analyze dataset
        features = analyze_dataset(self.project.data_path)
        features_summary = features_to_prompt(features)
        self.log(f"\n--- Data Analysis ---")
        self.log(features_summary)

        # Step 2: Generate initial model
        template_id = features.recommended_template
        self.log(f"\n--- Initial Model Generation ---")
        self.log(f"Template: {template_id}")

        if not HAS_TEMPLATES:
            self.log("ERROR: Model templates not available. Cannot proceed.")
            result.reason = "Model templates not available"
            return result

        # Generate the initial .mod
        mod_content = generate_initial_model(
            template_id=template_id,
            run_id=str(self.current_run_id),
            data_file=self.project.data_file,
            input_columns=features.columns,
        )
        mod_path = self.project.project_path / f"run{self.current_run_id}.mod"
        mod_path.write_text(mod_content, encoding="utf-8")
        self.log(f"Generated: {mod_path.name}")

        # Step 3: Validate and auto-fix
        self._validate_and_fix(mod_path)

        # Main loop
        for iteration in range(1, self.max_iterations + 1):
            self.log(f"\n{'='*60}")
            self.log(f"=== Iteration {iteration}/{self.max_iterations} ===")
            self.log(f"{'='*60}")

            iter_result = self._run_iteration(
                iteration=iteration,
                features_summary=features_summary,
            )
            result.iterations.append(iter_result)

            if iter_result.convergence and iter_result.convergence.should_stop:
                result.converged = iter_result.convergence.converged
                result.reason = iter_result.convergence.reason
                break

            # Apply the decision for the next iteration
            if iter_result.action_taken != ActionType.FINALIZE:
                next_run = self._apply_decision(
                    iter_result.decision,
                    features,
                    features_summary,
                )
                if next_run is None:
                    result.reason = "Could not apply optimization decision"
                    break
            else:
                result.converged = True
                result.reason = "AI decided to finalize"
                break

        # Finalize
        result.final_run_id = str(self.current_run_id)
        final_lst = self.project.project_path / f"run{self.current_run_id}.lst"
        if final_lst.exists():
            lst_results = parse_lst(final_lst, str(self.current_run_id))
            result.final_ofv = lst_results.ofv

        result.final_mod_path = self.project.project_path / f"run{self.current_run_id}.mod"
        result.final_lst_path = final_lst if final_lst.exists() else None

        self.log(f"\n=== Modeling loop complete ===")
        self.log(f"Converged: {result.converged}")
        self.log(f"Reason: {result.reason}")
        self.log(f"Final run: {result.final_run_id}")
        self.log(f"Final OFV: {result.final_ofv}")

        return result

    def _validate_and_fix(self, mod_path: Path) -> None:
        """Validate and auto-fix a .mod file."""
        self.log(f"\n--- Validating {mod_path.name} ---")
        result = validate_and_autofix(
            mod_path=mod_path,
            project_dir=self.project.project_path,
            csv_path=self.project.data_path,
            run_id=str(self.current_run_id),
        )

        if result["passed"]:
            self.log(f"Validation passed: {result['message']}")
        else:
            self.log(f"Validation issues: {result['message']}")
            for issue in result.get("issues", [])[:5]:
                self.log(f"  - {issue}")

    def _run_iteration(self, iteration: int,
                       features_summary: str) -> IterationResult:
        """Run a single iteration of the modeling loop.

        Steps:
        1. Run NONMEM
        2. Parse LST
        3. Generate diagnostics
        4. AI audit
        5. Make decision
        6. Check convergence
        """
        run_id = str(self.current_run_id)

        # Step 1: Run NONMEM
        self.log(f"\n--- Running NONMEM (Run {run_id}) ---")
        run_result = run_nonmem(
            project_dir=self.project.project_path,
            run_id=run_id,
            log=self.log,
        )

        if not run_result.success:
            self.log(f"NONMEM run failed: {run_result.error}")

        # Step 2: Parse LST
        lst_path = self.project.project_path / f"run{run_id}.lst"
        if not lst_path.exists():
            self.log("No LST file produced. Skipping diagnostics.")
            decision = ModelDecision(
                action=ActionType.REPAIR_CONTROL_STREAM,
                reasoning="NONMEM did not produce an LST file. Control stream likely has errors.",
                confidence=0.9,
            )
            return IterationResult(
                iteration=iteration,
                run_id=run_id,
                action_taken=ActionType.REPAIR_CONTROL_STREAM,
                decision=decision,
                notes="No LST file produced",
            )

        lst_results = parse_lst(lst_path, run_id)
        self.log(f"\n--- LST Results ---")
        self.log(lst_results.summary())

        # Step 3: Generate diagnostics (only if estimation succeeded)
        gof_report = ""
        vpc_report = ""

        if lst_results.successful and not lst_results.has_errors:
            # GOF
            self.log(f"\n--- GOF Diagnostics ---")
            try:
                gof_report = audit_gof(
                    llm=self.vision_llm,
                    rules=self.rules,
                    project_dir=self.project.project_path,
                    run_id=run_id,
                    prev_run_id=self.prev_run_id,
                    log=self.log,
                )
            except Exception as exc:
                gof_report = f"GOF audit failed: {exc}"
                self.log(gof_report)

            # VPC (only if GOF looks reasonable)
            if "acceptable" in gof_report.lower() or "good" in gof_report.lower():
                self.log(f"\n--- VPC Diagnostics ---")
                try:
                    vpc_report = audit_vpc(
                        llm=self.vision_llm,
                        rules=self.rules,
                        project_dir=self.project.project_path,
                        run_id=run_id,
                        prev_run_id=self.prev_run_id,
                        log=self.log,
                    )
                except Exception as exc:
                    vpc_report = f"VPC audit failed: {exc}"
                    self.log(vpc_report)

        # Step 4: Make decision
        self.log(f"\n--- AI Decision Making ---")
        decision = make_decision(
            llm=self.llm,
            rules=self.rules,
            lst_results=lst_results,
            features_summary=features_summary,
            gof_report=gof_report,
            vpc_report=vpc_report,
            iteration=iteration,
            max_iterations=self.max_iterations,
            log=self.log,
        )
        self.log(f"Decision: {decision.action.value}")
        self.log(f"Reasoning: {decision.reasoning}")
        self.log(f"Confidence: {decision.confidence:.1%}")

        # Step 5: Check convergence
        prev_ofv = None
        if self.prev_run_id:
            prev_lst = self.project.project_path / f"run{self.prev_run_id}.lst"
            if prev_lst.exists():
                prev_results = parse_lst(prev_lst, self.prev_run_id)
                prev_ofv = prev_results.ofv

        convergence = check_convergence(
            lst_results=lst_results,
            iteration=iteration,
            max_iterations=self.max_iterations,
            prev_ofv=prev_ofv,
        )

        return IterationResult(
            iteration=iteration,
            run_id=run_id,
            action_taken=decision.action,
            decision=decision,
            ofv=lst_results.ofv,
            convergence=convergence,
            gof_report=gof_report,
            vpc_report=vpc_report,
        )

    def _apply_decision(self, decision: ModelDecision, features,
                        features_summary: str) -> Optional[int]:
        """Apply the LLM's decision and prepare the next model.

        Returns the next run ID, or None if the decision couldn't be applied.
        """
        self.prev_run_id = str(self.current_run_id)
        self.current_run_id += 1
        new_run_id = str(self.current_run_id)
        source_mod = self.project.project_path / f"run{self.prev_run_id}.mod"
        target_mod = self.project.project_path / f"run{new_run_id}.mod"

        if decision.action == ActionType.FINALIZE:
            # Don't create a new model
            self.current_run_id -= 1
            return int(self.prev_run_id)

        if decision.action == ActionType.REPAIR_CONTROL_STREAM:
            # Keep the same run ID, just fix the control stream
            self.current_run_id -= 1
            new_run_id = str(self.current_run_id)
            target_mod = source_mod
            self.log(f"Repairing control stream for run {new_run_id}")
            self._validate_and_fix(target_mod)
            return int(new_run_id)

        if not HAS_GENERATOR:
            self.log("Model generator not available. Cannot apply decision.")
            return None

        from ..models.generator import apply_modifications, Modification

        # Read source model
        source_text = source_mod.read_text(encoding="utf-8")
        modifications = []

        if decision.action == ActionType.ADD_COVARIATE:
            modifications.append(Modification(
                action="add_covariate",
                params={
                    "parameter": decision.target_parameter,
                    "covariate": decision.covariate,
                },
            ))
            self.log(f"Adding covariate {decision.covariate} on {decision.target_parameter}")

        elif decision.action == ActionType.ADD_IIV:
            modifications.append(Modification(
                action="add_iiv",
                params={"parameter": decision.target_parameter},
            ))
            self.log(f"Adding IIV on {decision.target_parameter}")

        elif decision.action == ActionType.ESCALATE_STRUCTURE:
            if decision.new_template:
                modifications.append(Modification(
                    action="swap_template",
                    params={"template_id": decision.new_template},
                ))
                self.log(f"Escalating to template: {decision.new_template}")
            else:
                self.log("Escalation requested but no template specified")

        elif decision.action == ActionType.SIMPLIFY_STRUCTURE:
            if decision.new_template:
                modifications.append(Modification(
                    action="swap_template",
                    params={"template_id": decision.new_template},
                ))
                self.log(f"Simplifying to template: {decision.new_template}")

        elif decision.action == ActionType.CHANGE_ERROR_MODEL:
            modifications.append(Modification(
                action="fix_residual_error",
                params={"error_type": decision.details or "combined"},
            ))
            self.log(f"Changing error model: {decision.details}")

        elif decision.action == ActionType.SWITCH_TO_NONLINEAR:
            # Switch to Michaelis-Menten or TMDD template
            target_template = decision.new_template or "iv_mm_advan10_trans1"
            # Generate entirely new model from template instead of modifying
            from ..models.generator import generate_initial_model
            try:
                new_content = generate_initial_model(
                    template_id=target_template,
                    run_id=new_run_id,
                    data_file=self.project.data_file,
                )
                target_mod.write_text(new_content, encoding="utf-8")
                self.log(f"Switched to nonlinear model: {target_template}")
                self._validate_and_fix(target_mod)
                return int(new_run_id)
            except Exception as exc:
                self.log(f"Failed to switch to nonlinear model: {exc}")
                return None

        elif decision.action == ActionType.RERUN:
            # Just create a copy with bumped run ID
            modifications.append(Modification(
                action="bump_run",
                params={"old_run": self.prev_run_id, "new_run": new_run_id},
            ))
            self.log(f"Re-running with same structure (Run {new_run_id})")

        elif decision.action == ActionType.RUN_VPC:
            # Run VPC on current model, don't create new model
            self.current_run_id -= 1
            new_run_id = str(self.current_run_id)
            run_psn_vpc(
                project_dir=self.project.project_path,
                run_id=new_run_id,
                log=self.log,
            )
            return int(new_run_id)

        elif decision.action == ActionType.RUN_BOOTSTRAP:
            # Run bootstrap, don't create new model
            self.current_run_id -= 1
            new_run_id = str(self.current_run_id)
            from ..nonmem.runner import run_psn_bootstrap
            run_psn_bootstrap(
                project_dir=self.project.project_path,
                run_id=new_run_id,
                log=self.log,
            )
            return int(new_run_id)

        # Always bump run ID in table filenames
        modifications.append(Modification(
            action="bump_run",
            params={"old_run": self.prev_run_id, "new_run": new_run_id},
        ))

        try:
            new_text = apply_modifications(source_text, modifications)
            target_mod.write_text(new_text, encoding="utf-8")
            self.log(f"Generated: {target_mod.name}")
            self._validate_and_fix(target_mod)
            return int(new_run_id)
        except Exception as exc:
            self.log(f"Failed to apply modifications: {exc}")
            return None
