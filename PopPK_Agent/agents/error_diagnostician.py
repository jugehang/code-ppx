"""
错误诊断智能体

当NONMEM运行失败时，AI分析LST文件确定错误原因并给出修复建议。
"""

import json
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticResult:
    """诊断结果"""
    error_type: str           # 错误类型分类
    error_description: str     # 错误描述
    root_cause: str            # 根本原因
    fix_suggestion: str        # 修复建议
    severity: str              # critical | warning | info
    needs_model_change: bool   # 是否需要修改模型结构
    needs_param_adjust: bool   # 是否需要调整参数初始值


class ErrorDiagnostician:
    """AI错误诊断器"""

    def __init__(self, llm_backend, rule_engine):
        self.llm = llm_backend
        self.rules = rule_engine

    def diagnose(self, lst_content: str, mod_content: str, error_messages: List[str], warnings: List[str]) -> DiagnosticResult:
        """
        诊断NONMEM运行错误

        Args:
            lst_content: LST文件内容
            mod_content: MOD文件内容
            error_messages: 提取的错误消息
            warnings: 警告消息

        Returns:
            DiagnosticResult
        """
        modeling_rules = self.rules.format_for_prompt(namespaces=["@ModelingTechniques"])

        # 截取LST关键部分避免过长
        lst_excerpt = lst_content[:8000] if len(lst_content) > 8000 else lst_content

        prompt = f"""
你是NONMEM建模专家。以下模型运行出现了问题，请诊断错误原因并给出修复建议。

### 控制流 (.mod)
{mod_content}

### LST输出 (节选)
{lst_excerpt}

### 错误消息
{chr(10).join(error_messages) if error_messages else '无显式错误'}

### 警告消息
{chr(10).join(warnings) if warnings else '无'}

### NONMEM语法规则参考
{modeling_rules}

### 诊断要求
1. 识别错误类型 (语法错误/参数边界/收敛失败/矩阵奇异等)
2. 分析根本原因
3. 给出具体修复建议
4. 判断是否需要修改模型结构或调整初始值

### 输出格式 (严格JSON)
{{
  "error_type": "收敛失败/参数边界/语法错误/...",
  "error_description": "具体描述",
  "root_cause": "根本原因分析",
  "fix_suggestion": "具体修复步骤",
  "severity": "critical/warning/info",
  "needs_model_change": true/false,
  "needs_param_adjust": true/false
}}
"""

        try:
            result = self.llm.chat_json(prompt)
            return DiagnosticResult(
                error_type=result.get("error_type", "未知"),
                error_description=result.get("error_description", ""),
                root_cause=result.get("root_cause", ""),
                fix_suggestion=result.get("fix_suggestion", ""),
                severity=result.get("severity", "warning"),
                needs_model_change=result.get("needs_model_change", False),
                needs_param_adjust=result.get("needs_param_adjust", False),
            )
        except Exception as e:
            logger.error(f"AI错误诊断失败: {e}")
            return DiagnosticResult(
                error_type="诊断失败",
                error_description=str(e),
                root_cause="AI诊断过程出错",
                fix_suggestion="请手动检查LST文件",
                severity="critical",
                needs_model_change=False,
                needs_param_adjust=False,
            )
