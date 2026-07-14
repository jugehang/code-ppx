"""
确定性模型修改引擎

对NONMEM控制流进行确定性修改:
- add_covariate: 添加协变量 (如 WT 对 V1 的影响)
- add_iiv: 添加个体间变异
- fix_residual_error: 修改残差模型
- swap_template: 切换模型模板
- bump_run: 更新运行编号
- fix_input: 修复 $INPUT 列名
- fix_data: 修复 $DATA 路径
- fix_table_ids: 修复 $TABLE 文件名中的编号
- fix_theta_boundaries: 修复 THETA 边界

所有修改都是确定性的文本变换, 不依赖AI。
"""

import re
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Modification:
    """模型修改指令"""
    action: str          # 修改类型
    params: Dict[str, Any]  # 修改参数


# =====================================================================
# 控制流解析工具
# =====================================================================

def parse_sections(mod_text: str) -> Dict[str, str]:
    """
    解析NONMEM控制流为各个$块

    Returns:
        {block_name: block_content} 如 {"$PK": "...", "$THETA": "..."}
    """
    sections = {}
    # 匹配以$开头的块
    pattern = r'(\$\w+)'
    matches = list(re.finditer(pattern, mod_text))

    for i, match in enumerate(matches):
        start = match.start()
        block_name = match.group(1).upper()
        # 块结束位置: 下一个$块开始 或 文件末尾
        end = matches[i + 1].start() if i + 1 < len(matches) else len(mod_text)
        block_content = mod_text[start:end]
        sections[block_name] = block_content

    return sections


def rebuild_mod(sections: Dict[str, str], order: List[str] = None) -> str:
    """
    从解析的块重建NONMEM控制流

    Args:
        sections: {block_name: block_content}
        order: 块的排列顺序
    """
    default_order = [
        "$PROBLEM", "$INPUT", "$DATA", "$SUBROUTINES", "$PK",
        "$ERROR", "$THETA", "$OMEGA", "$SIGMA",
        "$EST", "$ESTIMATION", "$COV", "$TABLE"
    ]
    use_order = order or default_order

    parts = []
    used = set()

    for block_name in use_order:
        # 尝试精确匹配和前缀匹配
        for key in sections:
            if key.upper() == block_name.upper() or key.upper().startswith(block_name.upper()):
                if key not in used:
                    parts.append(sections[key].rstrip())
                    used.add(key)
                    break

    # 添加未在order中的块
    for key, content in sections.items():
        if key not in used:
            parts.append(content.rstrip())

    return "\n\n".join(parts) + "\n"


# =====================================================================
# 修改操作实现
# =====================================================================

def _add_covariate(mod_text: str, parameter: str, covariate: str) -> str:
    """
    添加协变量到$PK块

    例如: 对V1添加体重协变量
    V1WT = ((WT/62.14)**THETA(N))
    TVV1 = V1WT * TVV1
    """
    sections = parse_sections(mod_text)
    pk_block = sections.get("$PK", "")

    # 找到当前的THETA数量
    theta_block = sections.get("$THETA", "")
    n_thetas = len(re.findall(r'\([^)]*\)', theta_block.split('\n', 1)[-1] if '\n' in theta_block else theta_block))
    new_theta_num = n_thetas + 1

    # 添加协变量定义
    cov_var = f"{parameter}{covariate.upper()}"
    cov_def = f"\n;;; {cov_var}-DEFINITION\n   {cov_var} = (({covariate}/62.14)**THETA({new_theta_num}))\n;;; {cov_var}-RELATION\n{parameter}COV={cov_var}\n"

    # 在$PK块中查找 TVXX = THETA(X) 行，在其后添加协变量
    tv_pattern = rf'(TV{parameter}\s*=\s*THETA\(\d+\))'
    if re.search(tv_pattern, pk_block):
        pk_block = re.sub(
            tv_pattern,
            rf'\1\n{parameter}COV={cov_var}\nTV{parameter} = {parameter}COV*TV{parameter}',
            pk_block,
            count=1
        )
    else:
        pk_block += cov_def

    sections["$PK"] = pk_block

    # 添加新的THETA
    theta_block = sections.get("$THETA", "")
    theta_addition = f"\n(0,0.73) ; {cov_var}1"
    theta_block = theta_block.rstrip() + theta_addition
    sections["$THETA"] = theta_block

    return rebuild_mod(sections)


def _add_iiv(mod_text: str, parameter: str) -> str:
    """
    添加个体间变异(IIV)到指定参数

    例如: 对Q添加IIV
    Q = TVQ * EXP(ETA(N))
    """
    sections = parse_sections(mod_text)

    # 找到当前的OMEGA数量
    omega_block = sections.get("$OMEGA", "")
    n_omegas = len([l for l in omega_block.split('\n')[1:] if l.strip() and not l.strip().startswith(';')])

    pk_block = sections.get("$PK", "")

    # 查找参数定义中的 TVXX = THETA(X) 后跟 XX = TVXX
    # 将 fixed ETA 改为 estimated
    pattern = rf'(TV{parameter}\s*=\s*THETA\(\d+\))\s*\n\s*{parameter}\s*=\s*TV{parameter}\s*$'
    replacement = rf'\1\n{parameter} = TV{parameter} * EXP(ETA({n_omegas + 1}))'

    new_pk = re.sub(pattern, replacement, pk_block, flags=re.MULTILINE)

    if new_pk != pk_block:
        sections["$PK"] = new_pk

        # 在$OMEGA中添加新的ETA
        omega_lines = omega_block.rstrip().split('\n')
        # 找到最后一个非FIX的omega行
        new_omega_line = f" 0.1 ; IIV {parameter}"
        omega_lines.append(new_omega_line)
        sections["$OMEGA"] = '\n'.join(omega_lines)

        # 同时修改$TABLE添加新的ETA列
        for key in list(sections.keys()):
            if key.startswith("$TABLE"):
                table_content = sections[key]
                if "ETA" in table_content and f"ETA{n_omegas}" in table_content:
                    table_content = table_content.replace(
                        f"ETA{n_omegas}",
                        f"ETA{n_omegas} ETA{n_omegas + 1}"
                    )
                    sections[key] = table_content

    return rebuild_mod(sections)


def _fix_residual_error(mod_text: str, error_type: str = "combined") -> str:
    """
    修改残差模型
    """
    sections = parse_sections(mod_text)
    error_block = sections.get("$ERROR", "")

    lines = error_block.split('\n')
    new_lines = [lines[0]]  # $ERROR 行

    new_lines.append("IPRED = F")

    if error_type == "proportional":
        new_lines.append("    W = THETA(5)")  # 假设THETA(5)是比例误差
        new_lines.append("    Y = IPRED + W*EPS(1)")
    elif error_type == "additive":
        new_lines.append("    W = THETA(6)")  # 假设THETA(6)是加合误差
        new_lines.append("    Y = IPRED + W*EPS(1)")
    else:  # combined
        new_lines.append("    W = SQRT(THETA(5)**2*IPRED**2 + THETA(6)**2)")
        new_lines.append("    Y = IPRED + W*EPS(1)")

    new_lines.append(" IRES = DV-IPRED")
    new_lines.append("IWRES = IRES/W")

    sections["$ERROR"] = '\n'.join(new_lines)

    return rebuild_mod(sections)


def _swap_template(mod_text: str, template_id: str) -> str:
    """
    切换模型模板 (完全重新生成)
    """
    from poppk_model_templates import TEMPLATES, render_model

    template = TEMPLATES.get(template_id)
    if not template:
        logger.error(f"未知模板: {template_id}")
        return mod_text

    # 提取当前run_id
    m = re.search(r'run(\d+)', mod_text[:200])
    run_id = m.group(1) if m else "1"

    # 提取当前数据文件
    data_match = re.search(r'\$DATA\s+(\S+)', mod_text)
    data_file = data_match.group(1).split()[0] if data_match else "NM_dat_new.csv"

    # 提取INPUT列
    input_match = re.search(r'\$INPUT\s+(.+)', mod_text)
    input_columns = input_match.group(1).split() if input_match else None

    return render_model(
        template_id=template_id,
        run_id=run_id,
        data_file=data_file,
        input_columns=input_columns,
    )


def _bump_run(mod_text: str, old_run: str, new_run: str) -> str:
    """
    更新控制流中的运行编号
    替换所有 SDTAB{old}, PATAB{old}, 000{old}.ETA 等
    """
    # 替换 TABLE 文件名中的编号
    mod_text = re.sub(rf'FILE=SDTAB{old_run}', f'FILE=SDTAB{new_run}', mod_text)
    mod_text = re.sub(rf'FILE=PATAB{old_run}', f'FILE=PATAB{new_run}', mod_text)
    mod_text = re.sub(rf'FILE=000{old_run}\.ETA', f'FILE=000{new_run}.ETA', mod_text)
    mod_text = re.sub(rf'FILE=CATAB{old_run}', f'FILE=CATAB{new_run}', mod_text)
    mod_text = re.sub(rf'FILE=COTAB{old_run}', f'FILE=COTAB{new_run}', mod_text)

    # 更新PROBLEM注释中的编号
    mod_text = re.sub(rf'run{old_run}', f'run{new_run}', mod_text, flags=re.IGNORECASE)

    return mod_text


def _fix_input(mod_text: str, columns: List[str]) -> str:
    """修复 $INPUT 列名"""
    sections = parse_sections(mod_text)
    input_str = " ".join(columns)
    sections["$INPUT"] = f"$INPUT {input_str}"
    return rebuild_mod(sections)


def _fix_data(mod_text: str, data_file: str) -> str:
    """修复 $DATA 路径"""
    sections = parse_sections(mod_text)
    sections["$DATA"] = f"$DATA {data_file} IGNORE=C"
    return rebuild_mod(sections)


def _fix_table_ids(mod_text: str, run_id: str) -> str:
    """修复 $TABLE 文件名中的编号"""
    sections = parse_sections(mod_text)

    for key in list(sections.keys()):
        if key.startswith("$TABLE"):
            content = sections[key]
            # 替换 FILE=SDTABxxx, FILE=PATABxxx 等
            content = re.sub(r'FILE=SDTAB\d+', f'FILE=SDTAB{run_id}', content)
            content = re.sub(r'FILE=PATAB\d+', f'FILE=PATAB{run_id}', content)
            content = re.sub(r'FILE=000\d+\.ETA', f'FILE=000{run_id}.ETA', content)
            content = re.sub(r'FILE=CATAB\d+', f'FILE=CATAB{run_id}', content)
            content = re.sub(r'FILE=COTAB\d+', f'FILE=COTAB{run_id}', content)
            sections[key] = content

    return rebuild_mod(sections)


def _fix_theta_boundaries(mod_text: str) -> str:
    """修复 THETA 边界 (确保有下限)"""
    sections = parse_sections(mod_text)
    theta_block = sections.get("$THETA", "")

    lines = theta_block.split('\n')
    new_lines = [lines[0]]  # $THETA 行

    for line in lines[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith(';'):
            new_lines.append(line)
            continue

        # 检查是否有括号格式的边界
        if stripped.startswith('('):
            new_lines.append(line)
            continue

        # 无括号格式: 转为有括号
        parts = stripped.split()
        if parts:
            initial = parts[0]
            comment = ' '.join(parts[1:])
            new_lines.append(f"(0, {initial}) {comment}")

    sections["$THETA"] = '\n'.join(new_lines)
    return rebuild_mod(sections)


# =====================================================================
# 修改操作注册表
# =====================================================================

ACTION_REGISTRY = {
    "add_covariate": lambda mod, params: _add_covariate(mod, params["parameter"], params["covariate"]),
    "add_iiv": lambda mod, params: _add_iiv(mod, params["parameter"]),
    "fix_residual_error": lambda mod, params: _fix_residual_error(mod, params.get("error_type", "combined")),
    "swap_template": lambda mod, params: _swap_template(mod, params["template_id"]),
    "bump_run": lambda mod, params: _bump_run(mod, params["old_run"], params["new_run"]),
    "fix_input": lambda mod, params: _fix_input(mod, params["columns"]),
    "fix_data": lambda mod, params: _fix_data(mod, params["data_file"]),
    "fix_table_ids": lambda mod, params: _fix_table_ids(mod, params["run_id"]),
    "fix_theta_boundaries": lambda mod, params: _fix_theta_boundaries(mod),
}


# =====================================================================
# 主接口
# =====================================================================

def apply_modifications(mod_text: str, modifications: List[Modification]) -> str:
    """
    依次应用所有修改

    Args:
        mod_text: 原始控制流文本
        modifications: 修改指令列表

    Returns:
        修改后的控制流文本
    """
    result = mod_text

    for mod in modifications:
        action_fn = ACTION_REGISTRY.get(mod.action)
        if action_fn is None:
            logger.warning(f"未知修改操作: {mod.action}")
            continue

        try:
            logger.info(f"应用修改: {mod.action} {mod.params}")
            result = action_fn(result, mod.params)
        except Exception as e:
            logger.error(f"修改 {mod.action} 失败: {e}")

    return result


def apply_structured(mod_text: str, modifications: List[Dict]) -> str:
    """
    应用结构化修改 (字典格式)

    Args:
        mod_text: 原始控制流文本
        modifications: [{action: "...", params: {...}}, ...]
    """
    mods = [Modification(action=m["action"], params=m.get("params", {})) for m in modifications]
    return apply_modifications(mod_text, mods)


def generate_from_template(template_id: str, run_id: str,
                           data_file: str = "NM_dat_new.csv",
                           input_columns: List[str] = None) -> str:
    """从模板生成模型"""
    from poppk_model_templates import render_model
    return render_model(template_id, run_id, data_file, input_columns)
