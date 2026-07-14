"""
NONMEM控制流(.mod)生成器

AI根据数据特征和规则库自动选择模型结构，生成NONMEM控制流。
支持:
- 单抗二室模型 (基础/带协变量)
- 单抗一室模型 (简化)
- TMDD模型 (当检测到非线性PK)
- 自动初始值估计
- 自动协变量纳入
"""

import logging
from typing import Dict, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)


class ModelGenerator:
    """NONMEM控制流生成器"""

    # 单抗典型PK参数范围 (参考 BIO-MAB-001)
    MAB_TYPICAL_PARAMS = {
        "CL_range": (0.005, 0.020),      # L/h (90-560 mL/day)
        "V1_range": (3.0, 5.5),           # L (中央室)
        "Q_range": (0.010, 0.050),       # L/h
        "V2_range": (1.5, 4.0),           # L (外周室)
        "half_life_days": (11, 30),       # 天
    }

    def __init__(self, config, llm_backend, rule_engine):
        self.config = config
        self.llm = llm_backend
        self.rules = rule_engine

    def generate_model(
        self,
        run_id: int,
        data_columns: List[str],
        data_summary: Dict,
        prev_result: Optional[Dict] = None,
        optimization_hint: Optional[str] = None,
    ) -> str:
        """
        生成NONMEM控制流

        Args:
            run_id: 模型编号
            data_columns: 数据列名列表
            data_summary: 数据摘要统计 (剂量范围, 采样点, 受试者数等)
            prev_result: 前序模型结果 (用于迭代优化)
            optimization_hint: AI给出的优化建议

        Returns:
            .mod文件内容
        """
        if prev_result and optimization_hint:
            # 迭代优化: 基于前序模型和建议生成改进版
            return self._generate_optimized_model(
                run_id, data_columns, data_summary, prev_result, optimization_hint
            )
        else:
            # 首次建模: AI选择最简模型结构
            return self._generate_initial_model(run_id, data_columns, data_summary)

    def _generate_initial_model(
        self,
        run_id: int,
        data_columns: List[str],
        data_summary: Dict
    ) -> str:
        """AI选择初始模型结构并生成控制流"""

        # 获取规则库中的建模相关规则
        modeling_rules = self.rules.format_for_prompt(
            namespaces=["@ModelingTechniques", "@BioPhys", "@mAb_EarlyClinical"]
        )

        prompt = f"""
你是一名顶级的群体药动学(PopPK)建模专家，特别擅长单克隆抗体(mAb)建模。
请根据以下数据特征，选择最简单的合理模型结构，生成NONMEM控制流(.mod文件)。

### 数据特征
- 列名: {', '.join(data_columns)}
- 数据摘要: {data_summary}
- 药物类型: {self.config.project.drug_type}
- 数据文件: {self.config.project.data_file}

### 规则库参考
{modeling_rules}

### 要求
1. 选择最简单但合理的模型结构（单抗通常为二室模型 ADVAN3 TRANS4）
2. 设置合理的初始值（参考单抗典型PK参数范围）
3. 包含 $INPUT, $DATA, $SUBROUTINES, $PK, $ERROR, $THETA, $OMEGA, $SIGMA, $EST, $COV, $TABLE
4. 残差模型使用比例+加合误差 (combined error model)
5. 输出 SDTAB{run_id} 用于GOF绘图
6. $TABLE 包含 PRED, IPRED, CWRES, CIWRES 等

### 输出格式
直接输出完整的NONMEM控制流，不要包含任何解释文字。
$PROBLEM 行使用注释说明模型选择理由。
"""

        system = "你是定量药理学专家，输出必须是有效的NONMEM控制流。"
        mod_content = self.llm.chat(prompt, system=system)

        # 清理可能的多余标记
        mod_content = mod_content.strip()
        if mod_content.startswith("```"):
            lines = mod_content.split("\n")
            mod_content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        return mod_content.strip()

    def _generate_optimized_model(
        self,
        run_id: int,
        data_columns: List[str],
        data_summary: Dict,
        prev_result: Dict,
        optimization_hint: str
    ) -> str:
        """基于前序模型结果和AI优化建议生成改进版控制流"""

        modeling_rules = self.rules.format_for_prompt(
            namespaces=["@ModelingTechniques", "@ModelEvaluation", "@CovariateAnalysis"]
        )

        prompt = f"""
你是一名顶级的群体药动学(PopPK)建模专家。
请基于前序模型的分析结果和优化建议，生成改进的NONMEM控制流。

### 前序模型控制流
{prev_result.get('control_stream', 'N/A')}

### 前序模型结果
- OFV: {prev_result.get('ofv', 'N/A')}
- 参数估计: {prev_result.get('final_estimates', 'N/A')}
- 收缩率: {prev_result.get('shrinkage_summary', 'N/A')}
- 警告: {prev_result.get('warnings', '无')}

### AI优化建议
{optimization_hint}

### 规则库参考
{modeling_rules}

### 数据信息
- 列名: {', '.join(data_columns)}
- 数据文件: {self.config.project.data_file}

### 要求
1. 基于优化建议对模型进行针对性改进
2. 保留前序模型中表现良好的部分
3. 合理设置初始值（参考前序模型的估计值）
4. 在 $PROBLEM 注释中说明本次修改内容
5. 输出完整NONMEM控制流，不包含解释文字
"""

        system = "你是定量药理学专家，输出必须是有效的NONMEM控制流。"
        mod_content = self.llm.chat(prompt, system=system)

        mod_content = mod_content.strip()
        if mod_content.startswith("```"):
            lines = mod_content.split("\n")
            mod_content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        return mod_content.strip()

    def save_mod_file(self, run_id: int, content: str) -> Path:
        """保存.mod文件"""
        mod_path = self.config.get_model_path(run_id)
        with open(mod_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"控制流已保存: {mod_path}")
        return mod_path

    @staticmethod
    def extract_data_columns(data_path: str) -> List[str]:
        """从数据文件提取列名"""
        import csv
        try:
            with open(data_path, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f)
                header = next(reader)
                return [col.strip() for col in header]
        except Exception as e:
            logger.error(f"读取数据列名失败: {e}")
            return []

    @staticmethod
    def summarize_data(data_path: str) -> Dict:
        """生成数据摘要"""
        try:
            import pandas as pd
            df = pd.read_csv(data_path)
            summary = {
                "n_subjects": df["ID"].nunique() if "ID" in df.columns else "N/A",
                "n_records": len(df),
                "n_observations": len(df[df.get("DV", pd.Series([0])).notna() & (df.get("DV", pd.Series([0])) != 0)]) if "DV" in df.columns else "N/A",
                "columns": list(df.columns),
            }

            if "DV" in df.columns:
                dv = df["DV"].dropna()
                dv = dv[dv > 0]
                if len(dv) > 0:
                    summary["dv_range"] = (float(dv.min()), float(dv.max()))
                    summary["dv_median"] = float(dv.median())

            if "TIME" in df.columns:
                summary["time_range"] = (float(df["TIME"].min()), float(df["TIME"].max()))

            if "AMT" in df.columns:
                amt = df[df["AMT"] > 0]["AMT"]
                if len(amt) > 0:
                    summary["dose_range"] = (float(amt.min()), float(amt.max()))
                    summary["n_dose_levels"] = amt.nunique()

            # 检查协变量
            covariates = ["WT", "AGE", "SEX", "STUDY", "CREAT", "ADA"]
            available_covs = [c for c in covariates if c in df.columns]
            summary["available_covariates"] = available_covs

            return summary
        except Exception as e:
            logger.error(f"数据摘要生成失败: {e}")
            return {"error": str(e)}
