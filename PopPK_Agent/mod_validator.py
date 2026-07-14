"""
NONMEM 控制流验证器

在运行NONMEM之前对.mod文件进行静态验证:
- 检查必需的块 ($PROBLEM, $INPUT, $DATA, $SUBROUTINES, $PK, $ERROR, $THETA, $OMEGA, $SIGMA, $EST)
- 检查THETA/OMEGA/SIGMA的编号一致性
- 检查$INPUT列名与数据文件列名是否匹配
- 检查$DATA路径是否存在
- 检查$TABLE文件名编号是否一致
- 检查ETA/EPS引用是否与OMEGA/SIGMA维度匹配
- 检查初始值是否合理 (正值、非零)
"""

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    """验证问题"""
    severity: str    # error | warning | info
    block: str       # 相关的$块
    message: str     # 问题描述
    suggestion: str = ""  # 修复建议

    def __str__(self):
        return f"[{self.severity.upper()}] {self.block}: {self.message}"


@dataclass
class ValidationResult:
    """验证结果"""
    passed: bool = True
    issues: List[ValidationIssue] = field(default_factory=list)
    auto_fixed: bool = False

    def add_error(self, block: str, message: str, suggestion: str = ""):
        self.issues.append(ValidationIssue("error", block, message, suggestion))
        self.passed = False

    def add_warning(self, block: str, message: str, suggestion: str = ""):
        self.issues.append(ValidationIssue("warning", block, message, suggestion))

    def summary(self) -> str:
        errors = [i for i in self.issues if i.severity == "error"]
        warnings = [i for i in self.issues if i.severity == "warning"]
        return f"{'PASS' if self.passed else 'FAIL'} - {len(errors)} errors, {len(warnings)} warnings"


# 必需的NONMEM块
REQUIRED_BLOCKS = [
    "$PROBLEM", "$INPUT", "$DATA", "$SUBROUTINES",
    "$PK", "$ERROR", "$THETA", "$OMEGA", "$SIGMA", "$EST"
]


def validate_mod(
    mod_path: Path,
    project_dir: Optional[Path] = None,
    csv_path: Optional[Path] = None,
    run_id: str = "",
) -> ValidationResult:
    """
    验证NONMEM控制流文件

    Args:
        mod_path: .mod文件路径
        project_dir: 项目目录
        csv_path: 数据文件路径 (可选, 用于检查列名匹配)
        run_id: 运行编号

    Returns:
        ValidationResult
    """
    result = ValidationResult()

    if not mod_path.exists():
        result.add_error("", f"文件不存在: {mod_path}")
        return result

    mod_text = mod_path.read_text(encoding='utf-8', errors='ignore')

    # 1. 检查必需的块
    _check_required_blocks(mod_text, result)

    # 2. 检查块内内容
    sections = _parse_sections(mod_text)

    # 3. 检查$INPUT与数据文件列名
    if csv_path and csv_path.exists():
        _check_input_columns(sections, csv_path, result)

    # 4. 检查$DATA路径
    _check_data_path(sections, project_dir or mod_path.parent, result)

    # 5. 检查THETA编号一致性
    _check_theta_consistency(sections, result)

    # 6. 检查ETA/EPS引用
    _check_eta_eps_references(sections, result)

    # 7. 检查初始值合理性
    _check_initial_values(sections, result)

    # 8. 检查$TABLE文件名编号
    if run_id:
        _check_table_ids(sections, run_id, result)

    # 9. 检查$EST方法
    _check_estimation(sections, result)

    return result


def _parse_sections(mod_text: str) -> dict:
    """解析控制流为块"""
    sections = {}
    pattern = r'(\$\w+)'
    matches = list(re.finditer(pattern, mod_text))

    for i, match in enumerate(matches):
        start = match.start()
        block_name = match.group(1).upper()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(mod_text)
        sections[block_name] = mod_text[start:end]

    return sections


def _check_required_blocks(mod_text: str, result: ValidationResult):
    """检查必需的块是否存在"""
    for block in REQUIRED_BLOCKS:
        if block not in mod_text.upper():
            # 尝试前缀匹配 ($EST vs $ESTIMATION)
            found = any(line.strip().upper().startswith(block) for line in mod_text.split('\n'))
            if not found:
                result.add_error(block, f"缺少必需的块: {block}")


def _check_input_columns(sections: dict, csv_path: Path, result: ValidationResult):
    """检查$INPUT列名与CSV列名是否匹配"""
    input_text = sections.get("$INPUT", "")
    if not input_text:
        return

    # 提取INPUT中的列名 (排除=DROP等)
    input_line = input_text.split('\n')[0]
    cols = input_line.replace("$INPUT", "").strip().split()
    input_cols = []
    for col in cols:
        col = col.split('=')[0].strip()
        if col:
            input_cols.append(col)

    # 读取CSV头
    try:
        with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
            csv_header = f.readline().strip()
        csv_cols = [c.strip().strip('"') for c in csv_header.split(',')]

        # 检查INPUT中的列是否都在CSV中
        for col in input_cols:
            if col not in csv_cols and col not in ["DROP", "C"]:
                result.add_warning("$INPUT", f"列 '{col}' 不在数据文件中 (CSV列: {csv_cols[:10]}...)")
    except Exception as e:
        result.add_warning("$INPUT", f"无法读取数据文件检查列名: {e}")


def _check_data_path(sections: dict, project_dir: Path, result: ValidationResult):
    """检查$DATA路径"""
    data_text = sections.get("$DATA", "")
    if not data_text:
        return

    match = re.search(r'\$DATA\s+(\S+)', data_text)
    if not match:
        result.add_error("$DATA", "无法解析$DATA路径")
        return

    data_file = match.group(1)
    data_path = Path(data_file)

    if not data_path.is_absolute():
        data_path = project_dir / data_file

    if not data_path.exists():
        result.add_error("$DATA", f"数据文件不存在: {data_path}", f"请检查路径: {data_path}")


def _check_theta_consistency(sections: dict, result: ValidationResult):
    """检查THETA编号一致性"""
    theta_text = sections.get("$THETA", "")
    pk_text = sections.get("$PK", "")

    # 计数$THETA中定义的参数数量
    theta_lines = [l for l in theta_text.split('\n')[1:] if l.strip() and not l.strip().startswith(';')]
    n_theta_defined = len(theta_lines)

    # 查找$PK中引用的THETA最大编号
    theta_refs = re.findall(r'THETA\((\d+)\)', pk_text)
    if theta_refs:
        max_ref = max(int(r) for r in theta_refs)
        if max_ref > n_theta_defined:
            result.add_error(
                "$PK/$THETA",
                f"$PK引用了THETA({max_ref})但$THETA只定义了{n_theta_defined}个参数",
                f"请在$THETA中添加THETA({max_ref})的定义"
            )

    # 检查$ERROR中的THETA引用
    error_text = sections.get("$ERROR", "")
    error_theta_refs = re.findall(r'THETA\((\d+)\)', error_text)
    if error_theta_refs:
        max_err_ref = max(int(r) for r in error_theta_refs)
        if max_err_ref > n_theta_defined:
            result.add_error(
                "$ERROR/$THETA",
                f"$ERROR引用了THETA({max_err_ref})但$THETA只定义了{n_theta_defined}个参数"
            )


def _check_eta_eps_references(sections: dict, result: ValidationResult):
    """检查ETA/EPS引用与OMEGA/SIGMA维度匹配"""
    pk_text = sections.get("$PK", "")
    omega_text = sections.get("$OMEGA", "")
    sigma_text = sections.get("$SIGMA", "")
    error_text = sections.get("$ERROR", "")

    # 计数OMEGA中定义的ETA数量 (排除FIX的也计入)
    omega_lines = [l for l in omega_text.split('\n')[1:] if l.strip() and not l.strip().startswith(';')]
    n_omega = len(omega_lines)

    # 查找ETA引用 (排除THETA中的ETA子串)
    eta_refs = re.findall(r'(?<!TH)ETA\((\d+)\)', pk_text)
    if eta_refs:
        max_eta = max(int(r) for r in eta_refs)
        if max_eta > n_omega:
            result.add_error(
                "$PK/$OMEGA",
                f"$PK引用了ETA({max_eta})但$OMEGA只定义了{n_omega}个"
            )

    # 计数SIGMA
    sigma_lines = [l for l in sigma_text.split('\n')[1:] if l.strip() and not l.strip().startswith(';')]
    n_sigma = len(sigma_lines)

    # 查找EPS引用
    eps_refs = re.findall(r'EPS\((\d+)\)', error_text)
    if eps_refs:
        max_eps = max(int(r) for r in eps_refs)
        if max_eps > n_sigma:
            result.add_error(
                "$ERROR/$SIGMA",
                f"$ERROR引用了EPS({max_eps})但$SIGMA只定义了{n_sigma}个"
            )


def _check_initial_values(sections: dict, result: ValidationResult):
    """检查初始值合理性"""
    theta_text = sections.get("$THETA", "")

    # 检查THETA初始值
    theta_lines = [l for l in theta_text.split('\n')[1:] if l.strip() and not l.strip().startswith(';')]

    for i, line in enumerate(theta_lines):
        # 提取括号内的值
        bracket_match = re.search(r'\(([^)]*)\)', line)
        if bracket_match:
            values = [v.strip() for v in bracket_match.group(1).split(',')]
            initial = values[1] if len(values) >= 2 else values[0]

            try:
                init_val = float(initial)
                if init_val == 0:
                    result.add_warning("$THETA", f"THETA({i+1})初始值为0, 可能导致梯度问题")
                if init_val < 0:
                    result.add_warning("$THETA", f"THETA({i+1})初始值为负: {init_val}")
            except ValueError:
                pass  # 可能是FIX

    # 检查OMEGA初始值
    omega_text = sections.get("$OMEGA", "")
    omega_lines = [l for l in omega_text.split('\n')[1:] if l.strip() and not l.strip().startswith(';')]

    for i, line in enumerate(omega_lines):
        if 'FIX' in line.upper():
            continue
        # 提取第一个数字
        num_match = re.search(r'[\d.]+', line)
        if num_match:
            try:
                val = float(num_match.group())
                if val > 1.0:
                    result.add_warning("$OMEGA", f"OMEGA({i+1})值较大({val}), CV%={100*(val**0.5):.1f}%, 可能过度参数化")
            except ValueError:
                pass


def _check_table_ids(sections: dict, run_id: str, result: ValidationResult):
    """检查$TABLE文件名编号一致性"""
    expected_files = [f"SDTAB{run_id}", f"PATAB{run_id}", f"000{run_id}.ETA", f"CATAB{run_id}", f"COTAB{run_id}"]

    for key, content in sections.items():
        if not key.startswith("$TABLE"):
            continue

        for expected in expected_files:
            if expected not in content:
                # 检查是否有错误编号的文件名
                base = expected.rstrip('0123456789').rstrip('.')
                pattern = rf'{re.escape(base)}\d+'
                wrong_match = re.search(pattern, content)
                if wrong_match and wrong_match.group() != expected:
                    result.add_warning(
                        "$TABLE",
                        f"文件名编号不匹配: 期望 {expected}, 实际 {wrong_match.group()}",
                        f"请更新为 run{run_id} 对应的编号"
                    )


def _check_estimation(sections: dict, result: ValidationResult):
    """检查$EST方法"""
    est_text = sections.get("$EST", "")

    if not est_text and not sections.get("$ESTIMATION"):
        result.add_warning("$EST", "未找到$ESTIMATION块")
        return

    est_block = est_text or sections.get("$ESTIMATION", "")

    # 检查是否有METHOD
    if "METHOD" not in est_block.upper():
        result.add_warning("$EST", "未指定METHOD, 默认可能不是FOCE-I")

    # 检查MAXEVAL
    if "MAXEVAL" not in est_block.upper() and "MAX=" not in est_block.upper():
        result.add_warning("$EST", "未指定MAXEVAL, 建议设置 MAXEVAL=9999")

    # 检查INTER
    if "INTER" not in est_block.upper():
        result.add_warning("$EST", "未指定INTER, 建议添加 INTER 选项")
