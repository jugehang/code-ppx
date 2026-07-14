"""CodePPK command-line interface.

Provides commands for:
- run: Full automated modeling loop
- audit: Run LST/GOF/VPC audit on existing models
- generate: Generate a model from template
- validate: Validate a .mod file
- features: Analyze dataset features
- config: Show current configuration
"""
import argparse
import sys
from pathlib import Path

from .config import LLMConfig, ProjectConfig, load_config_from_env


def cmd_run(args) -> int:
    """Run the full automated modeling loop."""
    project = ProjectConfig(
        project_dir=Path(args.project or Path.cwd()),
        data_file=args.data,
        rules_file=args.rules,
        prev_run=args.prev,
        curr_run=str(args.start_run),
    )

    llm = LLMConfig(
        provider=args.llm_provider,
        model_id=args.llm_model,
        base_url=args.llm_url,
        api_key=args.api_key,
        plugin_command=args.plugin_cmd or "",
    )

    from .engine.loop import ModelingLoop
    loop = ModelingLoop(
        project_config=project,
        llm_config=llm,
        log=print,
        max_iterations=args.max_iterations,
        start_run_id=args.start_run,
    )
    result = loop.run()

    print(f"\n{'='*60}")
    print(f"Final: Run {result.final_run_id}, OFV={result.final_ofv}")
    print(f"Converged: {result.converged} ({result.reason})")
    return 0


def cmd_audit(args) -> int:
    """Run audit on existing model outputs."""
    project = ProjectConfig(
        project_dir=Path(args.project or Path.cwd()),
        data_file=args.data,
        rules_file=args.rules,
        prev_run=args.prev,
        curr_run=args.curr,
    )

    llm = LLMConfig(
        provider=args.llm_provider,
        model_id=args.llm_model,
        base_url=args.llm_url,
        api_key=args.api_key,
    )

    from .llm.factory import create_provider
    from .rules.loader import RuleLibrary
    from .diagnostics.gof import audit_gof
    from .diagnostics.vpc import audit_vpc
    from .nonmem.lst_parser import parse_lst

    provider = create_provider(llm)
    vision_provider = create_provider(llm.resolve_vision())
    rules = RuleLibrary(
        rules_file=project.rules_file,
        base_dir=project.rules_base_dir,
    ).load()

    run_id = args.curr

    # LST audit
    lst_path = project.project_path / f"run{run_id}.lst"
    if lst_path.exists():
        print(f"\n--- LST Audit (Run {run_id}) ---")
        results = parse_lst(lst_path, run_id)
        print(results.summary())
    else:
        print(f"LST file not found: {lst_path}")

    # GOF audit
    if args.type in ("all", "gof"):
        print(f"\n--- GOF Audit ---")
        report = audit_gof(
            llm=vision_provider,
            rules=rules,
            project_dir=project.project_path,
            run_id=run_id,
            prev_run_id=args.prev,
            log=print,
        )
        print(report[:2000])

    # VPC audit
    if args.type in ("all", "vpc"):
        print(f"\n--- VPC Audit ---")
        report = audit_vpc(
            llm=vision_provider,
            rules=rules,
            project_dir=project.project_path,
            run_id=run_id,
            prev_run_id=args.prev,
            log=print,
        )
        print(report[:2000])

    return 0


def cmd_generate(args) -> int:
    """Generate a model from a template."""
    from .models.generator import generate_initial_model

    if not args.template:
        print("Error: --template is required for generate")
        return 1

    mod_content = generate_initial_model(
        template_id=args.template,
        run_id=args.run,
        data_file=args.data or "NM_dat_new.csv",
    )

    output = Path(args.output) if args.output else Path.cwd() / f"run{args.run}.mod"
    output.write_text(mod_content, encoding="utf-8")
    print(f"Generated: {output}")
    return 0


def cmd_validate(args) -> int:
    """Validate a .mod file."""
    from .models.generator import validate_and_autofix

    mod_path = Path(args.mod)
    project_dir = Path(args.project_dir) if args.project_dir else mod_path.parent
    csv_path = Path(args.csv) if args.csv else None

    result = validate_and_autofix(
        mod_path=mod_path,
        project_dir=project_dir,
        csv_path=csv_path,
        run_id=args.run_id or "",
    )

    print(f"Passed: {result['passed']}")
    print(f"Message: {result['message']}")
    for issue in result.get("issues", []):
        print(f"  - {issue}")
    return 0 if result["passed"] else 1


def cmd_features(args) -> int:
    """Analyze dataset features."""
    from .data.features import analyze_dataset, features_to_prompt

    csv_path = Path(args.data)
    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        return 1

    features = analyze_dataset(csv_path)
    print(features_to_prompt(features))
    return 0


def cmd_config(args) -> int:
    """Show current configuration."""
    llm = load_config_from_env()
    print("=== LLM Configuration ===")
    print(f"Provider: {llm.provider}")
    print(f"Model: {llm.model_id}")
    print(f"Base URL: {llm.base_url}")
    print(f"API Key: {'***' + llm.api_key[-4:] if llm.api_key else 'none'}")
    print(f"Plugin Command: {llm.plugin_command or 'N/A'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="codeppk",
        description="CodePPK — Automated Population PK Modeling Platform",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Common LLM arguments
    def add_llm_args(p):
        p.add_argument("--llm-provider", default="local",
                       choices=["local", "api", "plugin"],
                       help="LLM provider type")
        p.add_argument("--llm-model", default="google/gemma-4-26b-a4b",
                       help="LLM model ID")
        p.add_argument("--llm-url", default="http://localhost:1234/v1",
                       help="LLM API base URL")
        p.add_argument("--api-key", default="lm-studio",
                       help="API key for LLM")
        p.add_argument("--plugin-cmd", default="",
                       help="VS Code plugin command (e.g. claude-code)")

    def add_project_args(p):
        p.add_argument("--project", default=".",
                      help="Project directory (default: current directory)")
        p.add_argument("--data", default="NM_dat_new.csv",
                      help="Data file name")
        p.add_argument("--rules", default="poppk_rules.json",
                      help="Rules file name (comma-separated for multiple)")

    # run
    p_run = subparsers.add_parser("run", help="Run full automated modeling loop")
    add_project_args(p_run)
    add_llm_args(p_run)
    p_run.add_argument("--prev", default="", help="Previous run ID")
    p_run.add_argument("--start-run", type=int, default=1, help="Starting run number")
    p_run.add_argument("--max-iterations", type=int, default=10,
                       help="Maximum modeling iterations")
    p_run.set_defaults(func=cmd_run)

    # audit
    p_audit = subparsers.add_parser("audit", help="Run audit on existing models")
    add_project_args(p_audit)
    add_llm_args(p_audit)
    p_audit.add_argument("--prev", default="", help="Previous run ID for comparison")
    p_audit.add_argument("--curr", default="41", help="Current run ID")
    p_audit.add_argument("--type", default="all", choices=["all", "lst", "gof", "vpc"],
                         help="Audit type")
    p_audit.set_defaults(func=cmd_audit)

    # generate
    p_gen = subparsers.add_parser("generate", help="Generate a model from template")
    p_gen.add_argument("--template", help="Template ID")
    p_gen.add_argument("--run", default="1", help="Run number")
    p_gen.add_argument("--data", default="NM_dat_new.csv", help="Data file name")
    p_gen.add_argument("--output", help="Output file path")
    p_gen.set_defaults(func=cmd_generate)

    # validate
    p_val = subparsers.add_parser("validate", help="Validate a .mod file")
    p_val.add_argument("--mod", required=True, help="Path to .mod file")
    p_val.add_argument("--project-dir", help="Project directory")
    p_val.add_argument("--csv", help="CSV dataset path")
    p_val.add_argument("--run-id", help="Expected run ID")
    p_val.set_defaults(func=cmd_validate)

    # features
    p_feat = subparsers.add_parser("features", help="Analyze dataset features")
    p_feat.add_argument("--data", required=True, help="CSV data file path")
    p_feat.set_defaults(func=cmd_features)

    # config
    p_conf = subparsers.add_parser("config", help="Show current configuration")
    p_conf.set_defaults(func=cmd_config)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
