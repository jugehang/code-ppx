"""
NONMEM LST文件解析器

从NONMEM .lst输出文件中提取:
- 控制流 ($PK, $ERROR, $THETA, $OMEGA, $SIGMA)
- 目标函数值 (OFV)
- 最终参数估计 (Final Parameter Estimates)
- 标准误 (Standard Error of Estimate)
- 收缩率 (Shrinkage / ETABAR)
- 协方差矩阵
- 运行状态 (成功/失败/错误信息)
"""

import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ParameterEstimate:
    """单个参数估计"""
    name: str
    estimate: float
    se: Optional[float] = None
    rse: Optional[float] = None
    iiv_cv: Optional[float] = None
    iiv_shrink: Optional[float] = None
    is_fixed: bool = False


@dataclass
class ShrinkageInfo:
    """收缩率信息"""
    etabar: Dict[str, float] = field(default_factory=dict)
    eta_shrink_sd: Dict[str, float] = field(default_factory=dict)
    eta_shrink_vr: Dict[str, float] = field(default_factory=dict)
    eps_shrink_sd: Dict[str, float] = field(default_factory=dict)
    eps_shrink_vr: Dict[str, float] = field(default_factory=dict)


@dataclass
class ModelRunResult:
    """模型运行结果"""
    run_id: int
    success: bool = False
    ofv: Optional[float] = None
    aic: Optional[float] = None
    n_params: Optional[int] = None
    control_stream: str = ""
    pk_block: str = ""
    error_block: str = ""
    theta_block: str = ""
    omega_block: str = ""
    sigma_block: str = ""
    estimation_block: str = ""
    final_estimates: str = ""
    se_matrix: str = ""
    shrinkage: Optional[ShrinkageInfo] = None
    parameters: List[ParameterEstimate] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    raw_text: str = ""

    @property
    def d_ofv(self) -> Optional[float]:
        """如果有前序模型，计算ΔOFV"""
        return None  # 由外部设置


class LSTParser:
    """NONMEM LST文件解析器"""

    def parse(self, lst_path: str, run_id: Optional[int] = None) -> ModelRunResult:
        """解析LST文件"""
        path = Path(lst_path)
        if not path.exists():
            logger.error(f"LST文件不存在: {lst_path}")
            return ModelRunResult(run_id=run_id or 0, success=False, error_messages=[f"文件不存在: {lst_path}"])

        if run_id is None:
            m = re.search(r'run(\d+)', path.stem)
            run_id = int(m.group(1)) if m else 0

        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        result = ModelRunResult(run_id=run_id, raw_text=content)

        # 解析各部分
        self._parse_status(content, result)
        self._parse_control_stream(content, result)
        self._parse_ofv(content, result)
        self._parse_estimates(content, result)
        self._parse_shrinkage(content, result)
        self._parse_errors(content, result)

        return result

    def _parse_status(self, content: str, result: ModelRunResult):
        """判断运行状态"""
        # 检查是否有错误
        if "MINIMIZATION TERMINATED" in content or "MINIMIZATION SUCCESSFUL" in content:
            result.success = "MINIMIZATION SUCCESSFUL" in content
        elif "STATUS:" in content:
            status_match = re.search(r"STATUS:\s*(.+)", content)
            if status_match:
                status = status_match.group(1).strip()
                result.success = "SUCCESSFUL" in status.upper()
                if not result.success:
                    result.error_messages.append(f"NONMEM状态: {status}")

        # 检查常见错误模式
        if "PARAMETER ESTIMATE IS NEAR ITS BOUNDARY" in content:
            result.warnings.append("参数估计接近边界 (Parameter near boundary)")
        if "ROUNDING ERRORS" in content:
            result.warnings.append("存在舍入误差 (Rounding errors)")
        if "COVARIANCE STEP ABORTED" in content:
            result.warnings.append("协方差步骤被中止 (Covariance step aborted)")

    def _parse_control_stream(self, content: str, result: ModelRunResult):
        """解析控制流"""
        # 完整控制流
        ctrl_match = re.search(r"(\$PROBLEM[\s\S]*?)(?=\$EST|\$TABLE|$)", content)
        result.control_stream = ctrl_match.group(0) if ctrl_match else ""

        # $PK block
        pk_match = re.search(r"(\$PK[\s\S]*?)(?=\$ERROR|\$EST|\$THETA|\$OMEGA|\$SIGMA|\$TABLE)", content)
        result.pk_block = pk_match.group(0) if pk_match else ""

        # $ERROR block
        err_match = re.search(r"(\$ERROR[\s\S]*?)(?=\$THETA|\$OMEGA|\$SIGMA|\$EST|\$TABLE)", content)
        result.error_block = err_match.group(0) if err_match else ""

        # $THETA block
        theta_match = re.search(r"(\$THETA[\s\S]*?)(?=\$OMEGA|\$SIGMA|\$EST|\$TABLE|\$COV)", content)
        result.theta_block = theta_match.group(0) if theta_match else ""

        # $OMEGA block
        omega_match = re.search(r"(\$OMEGA[\s\S]*?)(?=\$SIGMA|\$EST|\$TABLE|\$COV)", content)
        result.omega_block = omega_match.group(0) if omega_match else ""

        # $SIGMA block
        sigma_match = re.search(r"(\$SIGMA[\s\S]*?)(?=\$EST|\$TABLE|\$COV)", content)
        result.sigma_block = sigma_match.group(0) if sigma_match else ""

        # $ESTIMATION block
        est_match = re.search(r"(\$EST[\s\S]*?)(?=\$TABLE|\$COV|\$PROBLEM|\Z)", content)
        result.estimation_block = est_match.group(0) if est_match else ""

    def _parse_ofv(self, content: str, result: ModelRunResult):
        """解析OFV"""
        # 尝试多种格式
        patterns = [
            r"#OBJV:\s*([\d\.\-]+)",
            r"OBJECTIVE FUNCTION VALUE WITHOUT CONSTANT:\s*([\d\.\-]+)",
            r"MINIMUM VALUE OF OBJECTIVE FUNCTION:\s*([\d\.\-]+)",
            r"OFV:\s*([\d\.\-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                try:
                    result.ofv = float(match.group(1))
                    break
                except ValueError:
                    continue

    def _parse_estimates(self, content: str, result: ModelRunResult):
        """解析最终参数估计"""
        # Final Parameter Estimate
        est_match = re.search(r"FINAL PARAMETER ESTIMATE[\s\S]*?(?=\s*\d+\s+TOTAL|\s*STANDARD ERROR|MINIMIZATION)", content)
        result.final_estimates = est_match.group(0) if est_match else ""

        # Standard Error
        se_match = re.search(r"STANDARD ERROR OF ESTIMATE[\s\S]*?(?=\s*\d+\s+TOTAL|\s*COVARIANCE|MINIMIZATION|ETABAR)", content)
        result.se_matrix = se_match.group(0) if se_match else ""

        # 提取Theta/Omega/Sigma数值
        self._extract_theta_values(content, result)

    def _extract_theta_values(self, content: str, result: ModelRunResult):
        """从最终估计中提取THETA值"""
        # 匹配 THETA 行格式: THETA(1) = value (典型格式)
        theta_matches = re.findall(r"THETA\((\d+)\)\s*=\s*([\d\.\-E+]+)", content)
        se_matches = re.findall(r"THETA\((\d+)\)\s*=\s*([\d\.\-E+]+)", content[result.se_matrix and len(result.se_matrix) or len(content):] if result.se_matrix else "")

        for i, (idx, val) in enumerate(theta_matches):
            try:
                estimate = float(val)
                se = None
                if i < len(se_matches):
                    se = float(se_matches[i][1])
                rse = (se / estimate * 100) if (se and estimate) else None
                result.parameters.append(ParameterEstimate(
                    name=f"THETA({idx})",
                    estimate=estimate,
                    se=se,
                    rse=rse,
                ))
            except ValueError:
                continue

    def _parse_shrinkage(self, content: str, result: ModelRunResult):
        """解析收缩率"""
        shrink_match = re.search(r"(ETABAR:[\s\S]*?EPSSHRINKVR.*)", content)
        if not shrink_match:
            return

        shrink_text = shrink_match.group(0)
        shrink = ShrinkageInfo()

        # ETABAR
        etabar_matches = re.findall(r"ETABAR\s*(?:\(\d+\))?\s*:\s*([\d\.\-E+]+)", shrink_text)
        for i, val in enumerate(etabar_matches):
            try:
                shrink.etabar[f"ETA{i+1}"] = float(val)
            except ValueError:
                continue

        # ETA shrinkage SD
        eta_sd_matches = re.findall(r"ETASHRINKSD\s*(?:\(\d+\))?\s*:\s*([\d\.\-E+]+)", shrink_text)
        for i, val in enumerate(eta_sd_matches):
            try:
                shrink.eta_shrink_sd[f"ETA{i+1}"] = float(val)
            except ValueError:
                continue

        # ETA shrinkage VR
        eta_vr_matches = re.findall(r"ETASHRINKVR\s*(?:\(\d+\))?\s*:\s*([\d\.\-E+]+)", shrink_text)
        for i, val in enumerate(eta_vr_matches):
            try:
                shrink.eta_shrink_vr[f"ETA{i+1}"] = float(val)
            except ValueError:
                continue

        # EPS shrinkage SD
        eps_sd_matches = re.findall(r"EPSSHRINKSD\s*(?:\(\d+\))?\s*:\s*([\d\.\-E+]+)", shrink_text)
        for i, val in enumerate(eps_sd_matches):
            try:
                shrink.eps_shrink_sd[f"EPS{i+1}"] = float(val)
            except ValueError:
                continue

        result.shrinkage = shrink

        # 将shrinkage关联到参数
        for param in result.parameters:
            eta_num = None
            m = re.search(r'(\d+)', param.name)
            if m:
                eta_num = int(m.group(1))
            if eta_num and eta_num <= len(shrink.eta_shrink_sd):
                key = f"ETA{eta_num}"
                param.iiv_shrink = shrink.eta_shrink_sd.get(key)

    def _parse_errors(self, content: str, result: ModelRunResult):
        """解析错误信息"""
        error_patterns = [
            (r"ERROR\s*:\s*(.+)", "NONMEM错误"),
            (r"WARNING\s*:\s*(.+)", "NONMEM警告"),
            (r"(MINIMIZATION TERMINATED DUE TO .+)", "终止原因"),
            (r"(PARAMETER ESTIMATE IS NEAR ITS BOUNDARY.+)", "边界警告"),
        ]

        for pattern, label in error_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                msg = match.strip()[:200]
                if label == "NONMEM错误":
                    result.error_messages.append(f"[{label}] {msg}")
                else:
                    result.warnings.append(f"[{label}] {msg}")

    def format_summary(self, result: ModelRunResult) -> str:
        """格式化解析结果摘要"""
        lines = [
            f"=== Run {result.run_id} 解析摘要 ===",
            f"状态: {'成功' if result.success else '失败'}",
            f"OFV: {result.ofv}" if result.ofv is not None else "OFV: N/A",
        ]

        if result.warnings:
            lines.append(f"警告: {len(result.warnings)} 条")
            for w in result.warnings[:3]:
                lines.append(f"  - {w}")

        if result.error_messages:
            lines.append(f"错误: {len(result.error_messages)} 条")
            for e in result.error_messages[:3]:
                lines.append(f"  - {e}")

        if result.parameters:
            lines.append(f"\n参数估计 ({len(result.parameters)} 个):")
            for p in result.parameters[:10]:
                rse_str = f"RSE={p.rse:.1f}%" if p.rse else "RSE=N/A"
                shrink_str = f"Shrink={p.iiv_shrink:.1f}%" if p.iiv_shrink else ""
                lines.append(f"  {p.name}: {p.estimate:.6g} ({rse_str}) {shrink_str}")

        if result.shrinkage and result.shrinkage.eta_shrink_sd:
            lines.append(f"\nIIV收缩率 (SD):")
            for key, val in result.shrinkage.eta_shrink_sd.items():
                lines.append(f"  {key}: {val:.2f}%")

        return "\n".join(lines)
