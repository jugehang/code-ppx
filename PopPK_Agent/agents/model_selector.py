"""
模型结构选择智能体

AI根据数据特征自动选择最合适的模型结构。
决策依据: 规则库 + 数据特征 + 单抗PK先验知识
"""

import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ModelStructureDecision:
    """模型结构决策"""
    n_compartments: int  # 1 或 2
    advan: str           # ADVAN1, ADVAN3, ADVAN4 等
    trans: str           # TRANS1, TRANS2, TRANS4 等
    has_tmdd: bool       # 是否需要TMDD
    error_model: str     # proportional, additive, combined
    initial_cavariates: List[str]
    reasoning: str        # 选择理由


class ModelSelector:
    """AI模型结构选择器"""

    def __init__(self, llm_backend, rule_engine):
        self.llm = llm_backend
        self.rules = rule_engine

    def select(self, data_summary: Dict, data_columns: List[str]) -> ModelStructureDecision:
        """
        根据数据特征选择模型结构

        Args:
            data_summary: 数据摘要 (受试者数, 剂量范围, 采样点等)
            data_columns: 数据列名

        Returns:
            ModelStructureDecision
        """
        bio_rules = self.rules.format_namespace("@BioPhys")
        mab_rules = self.rules.format_namespace("@mAb_EarlyClinical")

        prompt = f"""
你是定量药理学建模专家。请根据以下数据特征，为单克隆抗体(mAb)人体研究选择最简单的合理模型结构。

### 数据特征
{json.dumps(data_summary, indent=2, ensure_ascii=False, default=str)}

### 数据列名
{', '.join(data_columns)}

### 单抗药代动力学规则参考
{bio_rules}

{mab_rules}

### 决策要求
1. 选择室数 (1室 or 2室) - 单抗通常为二室模型
2. 选择ADVAN和TRANS (如 ADVAN3 TRANS4)
3. 判断是否需要TMDD模型 (检查是否有非线性PK迹象)
4. 选择残差模型 (比例/加合/混合)
5. 建议初始纳入的协变量

### 输出格式 (严格JSON)
{{
  "n_compartments": 2,
  "advan": "ADVAN3",
  "trans": "TRANS4",
  "has_tmdd": false,
  "error_model": "combined",
  "initial_cavariates": ["WT"],
  "reasoning": "选择理由..."
}}
"""

        try:
            result = self.llm.chat_json(prompt)
            return ModelStructureDecision(
                n_compartments=result.get("n_compartments", 2),
                advan=result.get("advan", "ADVAN3"),
                trans=result.get("trans", "TRANS4"),
                has_tmdd=result.get("has_tmdd", False),
                error_model=result.get("error_model", "combined"),
                initial_cavariates=result.get("initial_cavariates", []),
                reasoning=result.get("reasoning", ""),
            )
        except Exception as e:
            logger.error(f"模型结构选择失败: {e}, 使用默认单抗二室模型")
            return ModelStructureDecision(
                n_compartments=2,
                advan="ADVAN3",
                trans="TRANS4",
                has_tmdd=False,
                error_model="combined",
                initial_cavariates=["WT"],
                reasoning="默认单抗二室模型 (AI选择失败降级)"
            )

    def check_tmdd_signals(self, data_summary: Dict) -> bool:
        """检查是否存在TMDD信号"""
        dose_range = data_summary.get("dose_range")
        if not dose_range:
            return False

        # 如果剂量范围跨度大（>10倍），检查非线性PK
        dose_min, dose_max = dose_range
        if dose_max / dose_min > 10:
            logger.info("剂量跨度>10倍，建议检查TMDD")
            return True

        return False
