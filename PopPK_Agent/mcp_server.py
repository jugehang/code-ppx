"""
PopPK MCP Server

Model Context Protocol (MCP) 服务器，将PopPK Agent的核心功能暴露给CodeBuddy。

提供以下工具:
- run_nonmem: 运行NONMEM拟合
- parse_lst: 解析LST输出文件
- generate_gof: 生成GOF诊断图
- generate_vpc: 生成VPC图
- audit_gof: AI判读GOF图
- audit_vpc: AI判读VPC图
- generate_model: 从模板生成.mod文件
- validate_mod: 验证.mod文件
- get_rules: 查询规则库
- run_automation: 启动完整自动化建模循环
"""

import sys
import os
import json
import logging
import traceback
from pathlib import Path

# 设置Python路径
WORKSPACE = os.environ.get("POPPK_WORKSPACE", os.path.dirname(os.path.abspath(__file__)))
PYTHONPATH = os.environ.get("PYTHONPATH", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PYTHONPATH not in sys.path:
    sys.path.insert(0, PYTHONPATH)
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

logger = logging.getLogger(__name__)


def list_tools() -> list:
    """列出可用的MCP工具"""
    return [
        {
            "name": "run_nonmem",
            "description": "运行NONMEM拟合。传入模型编号(如41)运行run41.mod。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer", "description": "模型编号 (如41对应run41.mod)"}
                },
                "required": ["run_id"]
            }
        },
        {
            "name": "parse_lst",
            "description": "解析NONMEM LST输出文件，提取OFV、参数估计、RSE、Shrinkage等。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer", "description": "模型编号"}
                },
                "required": ["run_id"]
            }
        },
        {
            "name": "generate_gof",
            "description": "生成GOF诊断图 (6宫格: DV vs IPRED, DV vs PRED, CWRES vs Time/PRED, |IWRES| vs IPRED, QQ图)。需要先运行NONMEM生成SDTAB文件。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer", "description": "模型编号"}
                },
                "required": ["run_id"]
            }
        },
        {
            "name": "generate_vpc",
            "description": "运行PsN VPC仿真并生成VPC图。耗时较长(需运行500次仿真)。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer", "description": "模型编号"},
                    "samples": {"type": "integer", "description": "仿真样本量", "default": 500}
                },
                "required": ["run_id"]
            }
        },
        {
            "name": "audit_gof",
            "description": "AI视觉判读GOF诊断图，引用规则库给出评价。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer", "description": "当前模型编号"},
                    "prev_run_id": {"type": "integer", "description": "前序模型编号(可选,用于对比)"}
                },
                "required": ["run_id"]
            }
        },
        {
            "name": "audit_vpc",
            "description": "AI视觉判读VPC诊断图，评估预测区间覆盖。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer", "description": "当前模型编号"},
                    "prev_run_id": {"type": "integer", "description": "前序模型编号(可选)"}
                },
                "required": ["run_id"]
            }
        },
        {
            "name": "generate_model",
            "description": "从模板生成NONMEM控制流(.mod文件)。可选模板: iv_infusion_1c_advan1_trans2(一室), iv_infusion_2c_advan3_trans4(二室,单抗标准), iv_infusion_2c_wt_advan3_trans4(二室+体重协变量), iv_infusion_mm_advan10_trans1(Michaelis-Menten非线性)。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "template_id": {"type": "string", "description": "模板ID"},
                    "run_id": {"type": "string", "description": "运行编号"},
                    "data_file": {"type": "string", "description": "数据文件名", "default": "NM_dat_new.csv"}
                },
                "required": ["template_id", "run_id"]
            }
        },
        {
            "name": "validate_mod",
            "description": "验证NONMEM控制流(.mod)文件的语法和一致性。检查必需块、THETA编号、ETA/EPS引用、初始值等。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer", "description": "模型编号"}
                },
                "required": ["run_id"]
            }
        },
        {
            "name": "get_rules",
            "description": "查询PopPK规则库。可按命名空间查询(@Regulatory/@BioPhys/@ModelingTechniques/@DataStandards/@ModelEvaluation/@CovariateAnalysis/@mAb_EarlyClinical/@Reporting)。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string", "description": "命名空间(可选,不传则返回全部)"},
                    "keywords": {"type": "array", "items": {"type": "string"}, "description": "搜索关键词(可选)"}
                }
            }
        },
        {
            "name": "compare_models",
            "description": "对比两个模型的参数估计和OFV。计算ΔOFV并引用ME-COMP-001判断显著性。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run_id_1": {"type": "integer", "description": "模型1编号(前序)"},
                    "run_id_2": {"type": "integer", "description": "模型2编号(当前)"}
                },
                "required": ["run_id_1", "run_id_2"]
            }
        }
    ]


def call_tool(name: str, arguments: dict) -> str:
    """执行MCP工具调用"""
    try:
        if name == "run_nonmem":
            return _tool_run_nonmem(arguments)
        elif name == "parse_lst":
            return _tool_parse_lst(arguments)
        elif name == "generate_gof":
            return _tool_generate_gof(arguments)
        elif name == "generate_vpc":
            return _tool_generate_vpc(arguments)
        elif name == "audit_gof":
            return _tool_audit_gof(arguments)
        elif name == "audit_vpc":
            return _tool_audit_vpc(arguments)
        elif name == "generate_model":
            return _tool_generate_model(arguments)
        elif name == "validate_mod":
            return _tool_validate_mod(arguments)
        elif name == "get_rules":
            return _tool_get_rules(arguments)
        elif name == "compare_models":
            return _tool_compare_models(arguments)
        else:
            return json.dumps({"error": f"未知工具: {name}"})
    except Exception as e:
        logger.error(f"工具 {name} 执行失败: {traceback.format_exc()}")
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})


def _tool_run_nonmem(args):
    from core.nonmem_runner import NonmemRunner
    from core.config import PopPKConfig
    config = PopPKConfig.load(WORKSPACE)
    runner = NonmemRunner(config)
    run_id = args["run_id"]
    success, log = runner.run_nonmem(run_id)
    return json.dumps({"success": success, "log": log[:2000]}, ensure_ascii=False)


def _tool_parse_lst(args):
    from core.lst_parser import LSTParser
    parser = LSTParser()
    run_id = args["run_id"]
    lst_path = Path(WORKSPACE) / f"run{run_id}.lst"
    if not lst_path.exists():
        return json.dumps({"error": f"LST文件不存在: {lst_path}"}, ensure_ascii=False)
    result = parser.parse(str(lst_path), run_id)
    return json.dumps({
        "run_id": result.run_id,
        "success": result.success,
        "ofv": result.ofv,
        "errors": result.error_messages,
        "warnings": result.warnings,
        "summary": parser.format_summary(result)
    }, ensure_ascii=False, default=str)


def _tool_generate_gof(args):
    from core.nonmem_runner import NonmemRunner
    from core.config import PopPKConfig
    config = PopPKConfig.load(WORKSPACE)
    runner = NonmemRunner(config)
    run_id = args["run_id"]
    success, log = runner.run_r_script("gof_plot_script.R", str(run_id))
    gof_path = Path(WORKSPACE) / f"GOF_mod{run_id}.jpg"
    return json.dumps({
        "success": success,
        "log": log[:1000],
        "image_path": str(gof_path) if gof_path.exists() else None
    }, ensure_ascii=False)


def _tool_generate_vpc(args):
    from core.nonmem_runner import NonmemRunner
    from core.config import PopPKConfig
    config = PopPKConfig.load(WORKSPACE)
    runner = NonmemRunner(config)
    run_id = args["run_id"]
    samples = args.get("samples", 500)
    success, log = runner.run_vpc(run_id, samples=samples)
    if success:
        plot_ok, plot_log = runner.run_r_script("vpc_plot_script.R", str(run_id))
        return json.dumps({"vpc_success": success, "plot_success": plot_ok, "log": (log + plot_log)[:2000]}, ensure_ascii=False)
    return json.dumps({"vpc_success": False, "log": log[:2000]}, ensure_ascii=False)


def _tool_audit_gof(args):
    from core.diagnostics import DiagnosticsPipeline
    from core.config import PopPKConfig
    from core.llm_backend import create_llm_backend
    from core.rule_engine import RuleEngine
    from core.nonmem_runner import NonmemRunner

    config = PopPKConfig.load(WORKSPACE)
    llm = create_llm_backend(config.llm)
    rules = RuleEngine(str(config.get_rules_path()))
    runner = NonmemRunner(config)
    diag = DiagnosticsPipeline(config, llm, rules, runner)

    run_id = args["run_id"]
    prev_run_id = args.get("prev_run_id")

    gof_path = Path(WORKSPACE) / f"GOF_mod{run_id}.jpg"
    if not gof_path.exists():
        return json.dumps({"error": f"GOF图不存在: {gof_path}"}, ensure_ascii=False)

    prev_gof = None
    if prev_run_id:
        prev_path = Path(WORKSPACE) / f"GOF_mod{prev_run_id}.jpg"
        if prev_path.exists():
            prev_gof = str(prev_path)

    result = diag.audit_gof(run_id, str(gof_path), prev_gof)
    return json.dumps(result, ensure_ascii=False, default=str)


def _tool_audit_vpc(args):
    from core.diagnostics import DiagnosticsPipeline
    from core.config import PopPKConfig
    from core.llm_backend import create_llm_backend
    from core.rule_engine import RuleEngine
    from core.nonmem_runner import NonmemRunner

    config = PopPKConfig.load(WORKSPACE)
    llm = create_llm_backend(config.llm)
    rules = RuleEngine(str(config.get_rules_path()))
    runner = NonmemRunner(config)
    diag = DiagnosticsPipeline(config, llm, rules, runner)

    run_id = args["run_id"]
    prev_run_id = args.get("prev_run_id")

    vpc_path = Path(WORKSPACE) / f"VPC_Stratified_mod{run_id}.jpg"
    if not vpc_path.exists():
        vpc_path = Path(WORKSPACE) / f"VPC_mod{run_id}.jpg"

    if not vpc_path.exists():
        return json.dumps({"error": f"VPC图不存在"}, ensure_ascii=False)

    prev_vpc = None
    if prev_run_id:
        prev_path = Path(WORKSPACE) / f"VPC_mod{prev_run_id}.jpg"
        if prev_path.exists():
            prev_vpc = str(prev_path)

    result = diag.audit_vpc(run_id, str(vpc_path), prev_vpc)
    return json.dumps(result, ensure_ascii=False, default=str)


def _tool_generate_model(args):
    from poppk_model_templates import render_model, recommended_template_id, TEMPLATES
    template_id = args["template_id"]
    run_id = args["run_id"]
    data_file = args.get("data_file", "NM_dat_new.csv")

    if template_id == "auto":
        template_id = recommended_template_id(is_mab=True, has_weight=True)

    mod_content = render_model(template_id, run_id, data_file)
    mod_path = Path(WORKSPACE) / f"run{run_id}.mod"
    mod_path.write_text(mod_content, encoding="utf-8")

    return json.dumps({
        "template_id": template_id,
        "run_id": run_id,
        "mod_path": str(mod_path),
        "content": mod_content
    }, ensure_ascii=False)


def _tool_validate_mod(args):
    from mod_validator import validate_mod
    run_id = args["run_id"]
    mod_path = Path(WORKSPACE) / f"run{run_id}.mod"
    csv_path = Path(WORKSPACE) / "NM_dat_new.csv"

    result = validate_mod(mod_path, project_dir=Path(WORKSPACE), csv_path=csv_path, run_id=str(run_id))

    return json.dumps({
        "passed": result.passed,
        "summary": result.summary(),
        "issues": [{"severity": i.severity, "block": i.block, "message": i.message, "suggestion": i.suggestion} for i in result.issues]
    }, ensure_ascii=False)


def _tool_get_rules(args):
    from core.rule_engine import RuleEngine
    rules = RuleEngine(str(Path(WORKSPACE) / "poppk_rules.json"))

    namespace = args.get("namespace")
    keywords = args.get("keywords")

    if keywords:
        results = rules.search(keywords)
        return json.dumps({"results": results}, ensure_ascii=False)
    elif namespace:
        rules_text = rules.format_namespace(namespace)
        return json.dumps({"namespace": namespace, "rules": rules_text}, ensure_ascii=False)
    else:
        rules_text = rules.format_for_prompt()
        return json.dumps({"rules": rules_text}, ensure_ascii=False)


def _tool_compare_models(args):
    from core.lst_parser import LSTParser
    parser = LSTParser()

    run1 = args["run_id_1"]
    run2 = args["run_id_2"]

    lst1 = Path(WORKSPACE) / f"run{run1}.lst"
    lst2 = Path(WORKSPACE) / f"run{run2}.lst"

    if not lst1.exists() or not lst2.exists():
        return json.dumps({"error": f"LST文件不存在"}, ensure_ascii=False)

    r1 = parser.parse(str(lst1), run1)
    r2 = parser.parse(str(lst2), run2)

    d_ofv = (r2.ofv - r1.ofv) if (r1.ofv and r2.ofv) else None

    return json.dumps({
        "run_1": {"run_id": r1.run_id, "ofv": r1.ofv, "success": r1.success},
        "run_2": {"run_id": r2.run_id, "ofv": r2.ofv, "success": r2.success},
        "delta_ofv": d_ofv,
        "significance": "p<0.05 (ΔOFV>3.84)" if d_ofv and d_ofv < -3.84 else ("p<0.01 (ΔOFV>6.63)" if d_ofv and d_ofv < -6.63 else "不显著"),
        "summary_1": parser.format_summary(r1),
        "summary_2": parser.format_summary(r2),
    }, ensure_ascii=False, default=str)


# =====================================================================
# MCP JSON-RPC 协议实现 (stdio 传输)
# =====================================================================

def handle_request(request: dict) -> dict:
    """处理JSON-RPC请求"""
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False}
                },
                "serverInfo": {
                    "name": "poppk-mcp-server",
                    "version": "0.1.0"
                }
            }
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": list_tools()}
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})
        result = call_tool(tool_name, tool_args)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": result}]
            }
        }

    elif method == "notifications/initialized":
        return None  # 通知不需要响应

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"未知方法: {method}"}
        }


def main():
    """MCP服务器主循环 (stdio传输)"""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            response = handle_request(request)

            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

        except json.JSONDecodeError:
            logger.error(f"JSON解析失败: {line}")
        except Exception as e:
            logger.error(f"请求处理失败: {e}")
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(e)}
            }
            sys.stdout.write(json.dumps(error_response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
