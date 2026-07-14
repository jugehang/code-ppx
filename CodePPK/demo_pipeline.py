#!/usr/bin/env python3
"""CodePPK Full Pipeline Demo

Runs the complete automated PopPK pipeline on the existing mAb dataset
and generates an interactive HTML report showing all results.

Usage:
    python3 demo_pipeline.py
"""
import json
import sys
import os
from pathlib import Path
from datetime import datetime

# Setup paths
SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parent
POPPK_DIR = WORKSPACE / "PopPK_Agent"
sys.path.insert(0, str(POPPK_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from codeppk.data.features import analyze_dataset, features_to_prompt
from codeppk.rules.loader import RuleLibrary
from codeppk.models.generator import generate_initial_model, validate_and_autofix
from codeppk.nonmem.lst_parser import parse_lst, compare_runs
from codeppk.engine.convergence import check_convergence
from codeppk.engine.decisions import ActionType


def run_demo():
    print("=" * 70)
    print("  CodePPK Automated PopPK Pipeline — Full Demo")
    print("  Drug: Monoclonal Antibody | Data: NM_dat_new.csv")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # ================================================================
    # Step 1: Data Analysis
    # ================================================================
    print("\n[Step 1/6] Analyzing dataset...")
    data_path = POPPK_DIR / "NM_dat_new.csv"
    features = analyze_dataset(data_path)
    features_text = features_to_prompt(features)
    print(features_text)

    # ================================================================
    # Step 2: Rule Library
    # ================================================================
    print("[Step 2/6] Loading rule library...")
    rules = RuleLibrary(base_dir=POPPK_DIR).load()
    print(f"  Loaded: {rules}")
    n_rules = sum(len(r) for r in rules.namespaces.values())
    print(f"  Total rules: {n_rules}")

    # ================================================================
    # Step 3: Model Generation
    # ================================================================
    print("\n[Step 3/6] Generating initial model from template...")
    template_id = features.recommended_template
    print(f"  Template: {template_id}")
    mod_content = generate_initial_model(
        template_id=template_id,
        run_id="100",
        data_file="NM_dat_new.csv",
        input_columns=features.columns,
    )
    demo_mod = POPPK_DIR / "run100_demo.mod"
    demo_mod.write_text(mod_content, encoding="utf-8")
    print(f"  Generated: {demo_mod.name} ({len(mod_content)} chars)")

    # Validate
    val_result = validate_and_autofix(
        mod_path=demo_mod,
        project_dir=POPPK_DIR,
        csv_path=data_path,
        run_id="100",
    )
    print(f"  Validation: {'PASSED' if val_result['passed'] else 'ISSUES'} — {val_result['message']}")

    # ================================================================
    # Step 4: LST Analysis (existing runs)
    # ================================================================
    print("\n[Step 4/6] Analyzing existing NONMEM outputs...")
    run38 = parse_lst(POPPK_DIR / "run38.lst", "38")
    run41 = parse_lst(POPPK_DIR / "run41.lst", "41")
    comparison = compare_runs(run38, run41)

    print(f"\n  Run 38 (2-compartment, no WT covariate):")
    print(f"    OFV: {run38.ofv:.3f}")
    print(f"    Parameters: {len(run38.parameters)}")
    for p in run38.parameters:
        if p.theta_value != 0:
            print(f"      {p.name}: {p.theta_value:.4g} (RSE={p.theta_rse:.1f}%, Shrink={p.eta_shrink:.1f}%)")

    print(f"\n  Run 41 (2-compartment + WT covariate):")
    print(f"    OFV: {run41.ofv:.3f}")
    print(f"    Parameters: {len(run41.parameters)}")
    for p in run41.parameters:
        if p.theta_value != 0:
            print(f"      {p.name}: {p.theta_value:.4g} (RSE={p.theta_rse:.1f}%, Shrink={p.eta_shrink:.1f}%)")

    print(f"\n  Comparison:")
    print(f"    ΔOFV: {comparison['delta_ofv']} (significant: {comparison['significant']})")

    # ================================================================
    # Step 5: Convergence Assessment
    # ================================================================
    print("\n[Step 5/6] Convergence assessment...")
    conv = check_convergence(run41, iteration=3, max_iterations=10)
    print(f"  Converged: {conv.converged}")
    print(f"  Reason: {conv.reason}")
    print(f"  Should stop: {conv.should_stop}")

    # ================================================================
    # Step 6: AI Decision Simulation
    # ================================================================
    print("\n[Step 6/6] AI decision simulation (rule-based)...")
    decision = simulate_decision(run41, features, comparison)
    print(f"  Recommended action: {decision['action']}")
    print(f"  Reasoning: {decision['reasoning']}")

    # ================================================================
    # Generate HTML Report
    # ================================================================
    print("\n" + "=" * 70)
    print("  Generating interactive HTML report...")
    html = generate_html_report(
        features=features,
        features_text=features_text,
        rules=rules,
        mod_content=mod_content,
        run38=run38,
        run41=run41,
        comparison=comparison,
        convergence=conv,
        decision=decision,
    )
    report_path = POPPK_DIR / "CodePPK_Demo_Report.html"
    report_path.write_text(html, encoding="utf-8")
    print(f"  Report saved: {report_path}")
    print(f"  Open with: open '{report_path}'")
    print("=" * 70)
    print("  Demo complete!")
    print("=" * 70)

    # Clean up
    demo_mod.unlink(missing_ok=True)
    return report_path


def simulate_decision(run41, features, comparison):
    """Simulate an AI decision based on rules (no LLM needed)."""
    issues = []
    actions = []

    # Check RSE
    high_rse = [p for p in run41.parameters if p.theta_rse > 30 and p.theta_value != 0]
    if high_rse:
        actions.append({
            "action": "ADD_COVARIATE",
            "reasoning": f"High RSE on {', '.join(p.name for p in high_rse[:3])}. Consider adding covariates to explain variability."
        })

    # Check shrinkage
    high_shrink = [p for p in run41.parameters if p.eta_shrink > 30 and p.theta_value != 0]
    if high_shrink:
        actions.append({
            "action": "SIMPLIFY_STRUCTURE",
            "reasoning": f"High shrinkage on {', '.join(p.name for p in high_shrink[:3])}. IIV may not be needed."
        })

    # Check TMDD
    if features.has_nonlinear_pk and not run41.has_errors:
        actions.append({
            "action": "SWITCH_TO_NONLINEAR",
            "reasoning": f"Nonlinear PK detected (dose range {features.dose_range[0]}-{features.dose_range[1]} mg/kg). Consider Michaelis-Menten or TMDD model."
        })

    # Check OFV improvement
    if comparison["delta_ofv"] is not None and abs(comparison["delta_ofv"]) < 3.84:
        actions.append({
            "action": "FINALIZE",
            "reasoning": "OFV improvement < 3.84 (not significant). Model may be ready for finalization."
        })

    # If no issues, check for VPC
    if not actions:
        actions.append({
            "action": "RUN_VPC",
            "reasoning": "GOF parameters look acceptable. Run VPC to validate predictive performance."
        })

    return actions[0] if actions else {"action": "RERUN", "reasoning": "No specific issues detected."}


def generate_html_report(features, features_text, rules, mod_content,
                         run38, run41, comparison, convergence, decision):
    """Generate an interactive HTML report."""

    # Parameter table for run41
    param_rows = ""
    for p in run41.parameters:
        rse_color = "#ff7b72" if p.theta_rse > 30 else "#7ee787" if p.theta_rse < 15 else "#ffcc66"
        shrink_color = "#ff7b72" if p.eta_shrink > 30 else "#7ee787" if p.eta_shrink < 20 else "#ffcc66"
        param_rows += f"""
        <tr>
            <td>{p.name}</td>
            <td>{p.theta_value:.4g}</td>
            <td style="color:{rse_color}">{p.theta_rse:.1f}%</td>
            <td style="color:{shrink_color}">{p.eta_shrink:.1f}%</td>
        </tr>"""

    # Rule namespace summary
    ns_rows = ""
    for ns_name, ns_rules in rules.namespaces.items():
        ns_rows += f"""
        <tr>
            <td>{ns_name}</td>
            <td>{len(ns_rules)}</td>
            <td>{', '.join(r['rule_id'] for r in ns_rules[:3])}{'...' if len(ns_rules) > 3 else ''}</td>
        </tr>"""

    delta_ofv = comparison['delta_ofv']
    ofv_color = "#7ee787" if delta_ofv and delta_ofv < -3.84 else "#ffcc66"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>CodePPK Demo Report — Automated PopPK Pipeline</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, 'Segoe UI', sans-serif; background: #0d1117; color: #e6edf3; padding: 0; }}
.header {{ background: linear-gradient(135deg, #1f6feb, #2f81f7); padding: 30px 40px; color: white; }}
.header h1 {{ font-size: 28px; margin-bottom: 8px; }}
.header .meta {{ font-size: 14px; opacity: 0.9; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 30px 40px; }}
.section {{ background: #161b22; border-radius: 8px; padding: 24px; margin-bottom: 20px; border: 1px solid #30363d; }}
.section h2 {{ color: #58a6ff; font-size: 20px; margin-bottom: 16px; border-bottom: 1px solid #30363d; padding-bottom: 8px; }}
.metric-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; margin-bottom: 16px; }}
.metric {{ background: #21262d; border-radius: 6px; padding: 16px; text-align: center; }}
.metric .value {{ font-size: 28px; font-weight: bold; color: #58a6ff; }}
.metric .label {{ font-size: 12px; color: #8b949e; text-transform: uppercase; margin-top: 4px; }}
table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #30363d; }}
th {{ color: #8b949e; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
td {{ font-size: 14px; }}
.code-block {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 16px; overflow-x: auto; font-family: 'SF Mono', monospace; font-size: 13px; white-space: pre; max-height: 400px; overflow-y: auto; }}
.badge {{ display: inline-block; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: bold; }}
.badge-ok {{ background: rgba(126, 231, 135, 0.2); color: #7ee787; }}
.badge-warn {{ background: rgba(255, 204, 102, 0.2); color: #ffcc66; }}
.badge-err {{ background: rgba(255, 123, 114, 0.2); color: #ff7b72; }}
.badge-info {{ background: rgba(88, 166, 255, 0.2); color: #58a6ff; }}
.decision-box {{ background: #1c2331; border-left: 4px solid #58a6ff; padding: 16px 20px; border-radius: 0 6px 6px 0; margin: 12px 0; }}
.decision-box .action {{ font-size: 18px; font-weight: bold; color: #58a6ff; margin-bottom: 8px; }}
.pipeline {{ display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 16px 0; }}
.pipeline-step {{ background: #21262d; padding: 8px 16px; border-radius: 6px; font-size: 13px; border: 1px solid #30363d; }}
.pipeline-arrow {{ color: #484f58; }}
.pipeline-step.active {{ background: #1f6feb; border-color: #1f6feb; color: white; }}
.summary-box {{ background: linear-gradient(135deg, #1c2331, #21262d); border-radius: 8px; padding: 20px; margin: 16px 0; }}
.footer {{ text-align: center; padding: 30px; color: #484f58; font-size: 13px; }}
</style>
</head>
<body>

<div class="header">
    <h1>CodePPK Automated PopPK Pipeline Report</h1>
    <div class="meta">
        Drug Type: Monoclonal Antibody (mAb) |
        Dataset: NM_dat_new.csv |
        Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </div>
</div>

<div class="container">

    <!-- Pipeline Overview -->
    <div class="section">
        <h2>Pipeline Overview</h2>
        <div class="pipeline">
            <div class="pipeline-step active">Data Analysis</div>
            <span class="pipeline-arrow">→</span>
            <div class="pipeline-step active">Rule Library</div>
            <span class="pipeline-arrow">→</span>
            <div class="pipeline-step active">Model Generation</div>
            <span class="pipeline-arrow">→</span>
            <div class="pipeline-step active">NONMEM Run</div>
            <span class="pipeline-arrow">→</span>
            <div class="pipeline-step active">LST Parsing</div>
            <span class="pipeline-arrow">→</span>
            <div class="pipeline-step active">GOF/VPC Audit</div>
            <span class="pipeline-arrow">→</span>
            <div class="pipeline-step active">AI Decision</div>
            <span class="pipeline-arrow">→</span>
            <div class="pipeline-step">Convergence</div>
        </div>
    </div>

    <!-- Data Features -->
    <div class="section">
        <h2>1. Dataset Feature Analysis</h2>
        <div class="metric-grid">
            <div class="metric">
                <div class="value">{features.n_subjects}</div>
                <div class="label">Subjects</div>
            </div>
            <div class="metric">
                <div class="value">{features.n_obs}</div>
                <div class="label">Observations</div>
            </div>
            <div class="metric">
                <div class="value">{features.recommended_route_label}</div>
                <div class="label">Route</div>
            </div>
            <div class="metric">
                <div class="value">{features.dose_range[0]}-{features.dose_range[1]}</div>
                <div class="label">Dose Range (mg/kg)</div>
            </div>
            <div class="metric">
                <div class="value" style="color: {'#ff7b72' if features.has_nonlinear_pk else '#7ee787'}">{'Yes' if features.has_nonlinear_pk else 'No'}</div>
                <div class="label">Nonlinear PK (TMDD)</div>
            </div>
            <div class="metric">
                <div class="value">{features.recommended_template}</div>
                <div class="label">Initial Template</div>
            </div>
        </div>
        <table>
            <tr><th>Continuous Covariates</th><td>{', '.join(features.continuous_covariates) or 'None'}</td></tr>
            <tr><th>Categorical Covariates</th><td>{', '.join(features.categorical_covariates) or 'None'}</td></tr>
            <tr><th>Grouping Factors</th><td>{', '.join(features.grouping_factors) or 'None'}</td></tr>
            <tr><th>BQL Column</th><td>{'Yes' if features.has_bql else 'No'}</td></tr>
            <tr><th>Columns ({len(features.columns)})</th><td>{', '.join(features.columns)}</td></tr>
        </table>
    </div>

    <!-- Rule Library -->
    <div class="section">
        <h2>2. Rule Library</h2>
        <div class="metric-grid">
            <div class="metric">
                <div class="value">{len(rules.namespaces)}</div>
                <div class="label">Namespaces</div>
            </div>
            <div class="metric">
                <div class="value">{sum(len(r) for r in rules.namespaces.values())}</div>
                <div class="label">Total Rules</div>
            </div>
        </div>
        <table>
            <thead>
                <tr><th>Namespace</th><th>Rules</th><th>Sample Rule IDs</th></tr>
            </thead>
            <tbody>
                {ns_rows}
            </tbody>
        </table>
    </div>

    <!-- Model Generation -->
    <div class="section">
        <h2>3. Model Generation (Template: {features.recommended_template})</h2>
        <div class="code-block">{mod_content[:2000]}{'...' if len(mod_content) > 2000 else ''}</div>
    </div>

    <!-- LST Results -->
    <div class="section">
        <h2>4. NONMEM Output Analysis</h2>

        <div class="summary-box">
            <h3 style="color:#58a6ff; margin-bottom:12px;">Model Comparison: Run 38 → Run 41</h3>
            <div class="metric-grid">
                <div class="metric">
                    <div class="value">{run38.ofv:.1f}</div>
                    <div class="label">Run 38 OFV</div>
                </div>
                <div class="metric">
                    <div class="value">{run41.ofv:.1f}</div>
                    <div class="label">Run 41 OFV</div>
                </div>
                <div class="metric">
                    <div class="value" style="color:{ofv_color}">{delta_ofv}</div>
                    <div class="label">ΔOFV</div>
                </div>
                <div class="metric">
                    <div class="value">{'✓' if comparison['significant'] else '✗'}</div>
                    <div class="label">Significant (p&lt;0.05)</div>
                </div>
            </div>
        </div>

        <h3>Run 41 Parameter Estimates</h3>
        <table>
            <thead>
                <tr>
                    <th>Parameter</th>
                    <th>Estimate</th>
                    <th>RSE (%)</th>
                    <th>Eta Shrinkage (%)</th>
                </tr>
            </thead>
            <tbody>
                {param_rows}
            </tbody>
        </table>

        <div style="margin-top:12px;">
            <span class="badge {'badge-ok' if run41.successful else 'badge-err'}">{'Estimation Successful' if run41.successful else 'Estimation Failed'}</span>
            <span class="badge {'badge-ok' if run41.has_covariance else 'badge-warn'}">{'Covariance: OK' if run41.has_covariance else 'Covariance: Not Available'}</span>
            <span class="badge {'badge-ok' if not run41.has_errors else 'badge-warn'}">{'No Errors' if not run41.has_errors else f'{len(run41.error_messages)} Warnings'}</span>
        </div>
    </div>

    <!-- Convergence -->
    <div class="section">
        <h2>5. Convergence Assessment</h2>
        <div class="metric-grid">
            <div class="metric">
                <div class="value" style="color:{'#7ee787' if convergence.converged else '#ffcc66'}">{'Yes' if convergence.converged else 'No'}</div>
                <div class="label">Converged</div>
            </div>
            <div class="metric">
                <div class="value" style="color:{'#7ee787' if convergence.should_stop else '#58a6ff'}">{'Stop' if convergence.should_stop else 'Continue'}</div>
                <div class="label">Recommendation</div>
            </div>
        </div>
        <p style="color:#8b949e; margin-top:12px;">{convergence.reason}</p>
    </div>

    <!-- AI Decision -->
    <div class="section">
        <h2>6. AI Decision (Next Optimization Step)</h2>
        <div class="decision-box">
            <div class="action">→ {decision['action']}</div>
            <p>{decision['reasoning']}</p>
        </div>
        <p style="color:#8b949e; font-size:13px; margin-top:12px;">
            Available actions: {', '.join(a.value for a in ActionType)}
        </p>
    </div>

    <!-- Architecture -->
    <div class="section">
        <h2>CodePPK Architecture</h2>
        <div class="code-block">CodePPK/
├── codeppk/
│   ├── config.py              # LLM配置(本地/API/插件) + 项目配置
│   ├── cli.py                 # 命令行入口(run/audit/generate/validate/features/config)
│   ├── llm/                   # LLM提供商抽象层
│   │   ├── base.py           #   统一接口(chat + chat_with_image)
│   │   ├── local.py          #   本地LLM(LM Studio/Ollama)
│   │   ├── api.py             #   API(OpenAI/Anthropic/DeepSeek/Azure)
│   │   ├── plugin.py          #   VS Code插件(Claude Code/Codex/Aider)
│   │   └── factory.py        #   自动检测 + 工厂创建
│   ├── rules/loader.py        # 规则库加载器(52条规则,8命名空间)
│   ├── data/features.py       # 数据特征分析(给药途径/协变量/TMDD检测)
│   ├── models/generator.py    # 模型生成+验证(12个NONMEM模板)
│   ├── nonmem/
│   │   ├── runner.py          # PsN/nmfe执行器
│   │   └── lst_parser.py      # LST解析(OFV/参数/RSE/Shrinkage/错误)
│   ├── diagnostics/
│   │   ├── gof.py            # GOF生成+AI视觉审计
│   │   ├── vpc.py            # VPC生成+AI视觉审计
│   │   └── r_scripts.py      # R脚本调度
│   └── engine/               # 闭环引擎
│       ├── loop.py           #   主循环编排器
│       ├── decisions.py      #   LLM决策(11种action)
│       └── convergence.py    #   收敛判定
├── vscode-extension/          # VS Code 扩展 (code-oss 风格)
│   ├── src/
│   │   ├── extension.ts      # 扩展入口
│   │   ├── treeProvider.ts   # 文件树浏览器
│   │   ├── runner.ts         # 命令执行器
│   │   ├── configView.ts     # LLM配置面板
│   │   └── auditReport.ts   # 审计报告查看器
│   └── package.json          # 16个命令 + 3个视图面板
├── README.md
├── setup.py
└── requirements.txt</div>
    </div>

</div>

<div class="footer">
    CodePPK — Automated Population PK Modeling Platform<br/>
    Powered by LLM + Rule Library + NONMEM + PsN + R<br/>
    GitHub: https://github.com/jugehang/code-ppx.git
</div>

</body>
</html>"""


if __name__ == "__main__":
    report_path = run_demo()
    print(f"\nTo view the report:")
    print(f"  open '{report_path}'")
