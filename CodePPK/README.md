# CodePPK — Automated Population PK Modeling Platform

CodePPK is an LLM-powered, rule-driven automated population pharmacokinetic (PopPK) modeling platform built on top of NONMEM, PsN, and R. It targets monoclonal antibody (mAb) early clinical development and provides a closed-loop modeling workflow: **data → model → fit → diagnose → optimize → converge**.

## Architecture

```
CodePPK/
├── codeppk/                      # Core Python package
│   ├── __init__.py
│   ├── config.py                 # Global configuration & LLM provider settings
│   ├── llm/                      # LLM provider abstraction layer
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract LLM provider interface
│   │   ├── local.py             # Local LLM (LM Studio, Ollama)
│   │   ├── api.py               # Remote API (OpenAI, Anthropic, DeepSeek, etc.)
│   │   ├── plugin.py            # VS Code plugin bridge (Claude Code, Codex)
│   │   └── factory.py           # Provider factory & auto-detection
│   ├── rules/                    # Rule library loader
│   │   ├── __init__.py
│   │   └── loader.py            # Load poppk_rules.json + knowledge bases
│   ├── models/                   # NONMEM model generation & templates
│   │   ├── __init__.py
│   │   ├── templates.py         # Re-export of PopPK_Agent templates
│   │   ├── generator.py         # Deterministic model transformer
│   │   └── validator.py         # Static .mod preflight validator
│   ├── data/                     # Data analysis & feature extraction
│   │   ├── __init__.py
│   │   └── features.py          # CSV data profiling (route, dosing, covariates)
│   ├── nonmem/                  # NONMEM execution & output parsing
│   │   ├── __init__.py
│   │   ├── runner.py            # PsN/NONMEM execution
│   │   └── lst_parser.py        # LST file parser (OFV, params, shrinkage)
│   ├── diagnostics/             # Diagnostic plot generation & AI audit
│   │   ├── __init__.py
│   │   ├── gof.py               # GOF plot generation + AI audit
│   │   ├── vpc.py               # VPC plot generation + AI audit
│   │   └── r_scripts.py         # R script dispatcher
│   ├── engine/                   # Closed-loop automation engine
│   │   ├── __init__.py
│   │   ├── loop.py              # Main modeling loop orchestrator
│   │   ├── decisions.py         # LLM-driven decision (next step)
│   │   └── convergence.py       # Convergence criteria & finalization
│   └── cli.py                    # Command-line interface
├── README.md
├── setup.py
└── requirements.txt
```

## Quick Start

```bash
# Install
pip install -e .

# Run automated modeling
codeppk run --data NM_dat_new.csv --rules poppk_rules.json

# Use API instead of local LLM
codeppk run --data NM_dat_new.csv --llm-provider openai --llm-model gpt-4o

# Use VS Code Claude Code plugin
codeppk run --data NM_dat_new.csv --llm-provider plugin --llm-model claude-code
```
