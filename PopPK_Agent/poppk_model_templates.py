"""
NONMEM 模型模板库

为单抗(mAb)人体研究提供确定性的模型模板:
- 一室模型 (ADVAN1/TRANS2)
- 二室模型 (ADVAN3/TRANS4) - 单抗标准模型
- Michaelis-Menten非线性模型 (ADVAN10/TRANS1)
- TMDD简化模型

每个模板包含: 结构参数、初始值、IIV设置、残差模型、TABLE输出。
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class TemplateSpec:
    """模型模板规格定义"""
    template_id: str
    description: str
    advan: str
    trans: str
    n_compartments: int
    parameters: List[Dict]  # [{name, initial, lower, upper, unit, comment}]
    omega: List[Dict]       # [{name, initial, fixed, comment}]
    sigma: List[Dict]       # [{name, initial, fixed, comment}]
    error_model: str        # proportional | additive | combined
    has_tmdd: bool = False
    is_linear: bool = True


# =====================================================================
# 模型模板定义
# =====================================================================

TEMPLATES: Dict[str, TemplateSpec] = {

    # ---- 一室模型 (简化版, 适用于初步探索) ----
    "iv_infusion_1c_advan1_trans2": TemplateSpec(
        template_id="iv_infusion_1c_advan1_trans2",
        description="IV infusion 一室模型 (ADVAN1 TRANS2) - 最简结构",
        advan="ADVAN1",
        trans="TRANS2",
        n_compartments=1,
        parameters=[
            {"name": "CL", "initial": 0.012, "lower": 0, "upper": None, "unit": "L/h", "comment": "CL_L/h"},
            {"name": "V", "initial": 4.0, "lower": 0, "upper": None, "unit": "L", "comment": "V_L"},
            {"name": "Prop_RE", "initial": 0.15, "lower": 0, "upper": None, "unit": "sd", "comment": "Prop.RE(sd)"},
            {"name": "Add_RE", "initial": 0.0, "lower": 0, "upper": None, "unit": "sd", "comment": "Add.RE(sd)"},
        ],
        omega=[
            {"name": "IIV_CL", "initial": 0.222, "fixed": False, "comment": "IIV CL"},
            {"name": "IIV_V", "initial": 0.052, "fixed": False, "comment": "IIV V"},
        ],
        sigma=[
            {"name": "Prop_error", "initial": 1.0, "fixed": True, "comment": "Proportional error PK"},
        ],
        error_model="combined",
        is_linear=True,
    ),

    # ---- 二室模型 (单抗标准模型) ----
    "iv_infusion_2c_advan3_trans4": TemplateSpec(
        template_id="iv_infusion_2c_advan3_trans4",
        description="IV infusion 二室模型 (ADVAN3 TRANS4) - 单抗标准模型",
        advan="ADVAN3",
        trans="TRANS4",
        n_compartments=2,
        parameters=[
            {"name": "CL", "initial": 0.012, "lower": 0, "upper": None, "unit": "L/h", "comment": "CL_L/h"},
            {"name": "V1", "initial": 4.36, "lower": 0, "upper": None, "unit": "L", "comment": "V1_L"},
            {"name": "Q", "initial": 0.021, "lower": 0, "upper": None, "unit": "L/h", "comment": "Q_L/h"},
            {"name": "V2", "initial": 2.0, "lower": 0, "upper": None, "unit": "L", "comment": "V2_L"},
            {"name": "Prop_RE", "initial": 0.141, "lower": 0, "upper": None, "unit": "sd", "comment": "Prop.RE(sd)"},
            {"name": "Add_RE", "initial": 0.0, "lower": 0, "upper": None, "unit": "sd", "comment": "Add.RE(sd)"},
        ],
        omega=[
            {"name": "IIV_CL", "initial": 0.222, "fixed": False, "comment": "IIV CL"},
            {"name": "IIV_V1", "initial": 0.052, "fixed": False, "comment": "IIV V1"},
            {"name": "IIV_Q", "initial": 0.0, "fixed": True, "comment": "IIV Q"},
            {"name": "IIV_V2", "initial": 0.0, "fixed": True, "comment": "IIV V2"},
        ],
        sigma=[
            {"name": "Prop_error", "initial": 1.0, "fixed": True, "comment": "Proportional error PK"},
        ],
        error_model="combined",
        is_linear=True,
    ),

    # ---- 二室模型 + 体重协变量 (单抗标准 + WT) ----
    "iv_infusion_2c_wt_advan3_trans4": TemplateSpec(
        template_id="iv_infusion_2c_wt_advan3_trans4",
        description="IV infusion 二室模型 + 体重协变量 (ADVAN3 TRANS4)",
        advan="ADVAN3",
        trans="TRANS4",
        n_compartments=2,
        parameters=[
            {"name": "CL", "initial": 0.012, "lower": 0, "upper": None, "unit": "L/h", "comment": "CL_L/h"},
            {"name": "V1", "initial": 4.36, "lower": 0, "upper": None, "unit": "L", "comment": "V1_L"},
            {"name": "Q", "initial": 0.021, "lower": 0, "upper": None, "unit": "L/h", "comment": "Q_L/h"},
            {"name": "V2", "initial": 2.0, "lower": 0, "upper": None, "unit": "L", "comment": "V2_L"},
            {"name": "Prop_RE", "initial": 0.141, "lower": 0, "upper": None, "unit": "sd", "comment": "Prop.RE(sd)"},
            {"name": "Add_RE", "initial": 0.0, "lower": 0, "upper": None, "unit": "sd", "comment": "Add.RE(sd)"},
            {"name": "V1WT", "initial": 0.73, "lower": 0, "upper": None, "unit": "", "comment": "V1WT1"},
        ],
        omega=[
            {"name": "IIV_CL", "initial": 0.222, "fixed": False, "comment": "IIV CL"},
            {"name": "IIV_V1", "initial": 0.052, "fixed": False, "comment": "IIV V1"},
            {"name": "IIV_Q", "initial": 0.0, "fixed": True, "comment": "IIV Q"},
            {"name": "IIV_V2", "initial": 0.0, "fixed": True, "comment": "IIV V2"},
        ],
        sigma=[
            {"name": "Prop_error", "initial": 1.0, "fixed": True, "comment": "Proportional error PK"},
        ],
        error_model="combined",
        is_linear=True,
    ),

    # ---- Michaelis-Menten 非线性模型 ----
    "iv_infusion_mm_advan10_trans1": TemplateSpec(
        template_id="iv_infusion_mm_advan10_trans1",
        description="IV infusion Michaelis-Menten非线性模型 (ADVAN10 TRANS1) - TMDD近似",
        advan="ADVAN10",
        trans="TRANS1",
        n_compartments=1,
        parameters=[
            {"name": "VM", "initial": 0.050, "lower": 0, "upper": None, "unit": "mg/L/h", "comment": "VM"},
            {"name": "KM", "initial": 10.0, "lower": 0, "upper": None, "unit": "mg/L", "comment": "KM"},
            {"name": "V", "initial": 4.0, "lower": 0, "upper": None, "unit": "L", "comment": "V_L"},
            {"name": "Prop_RE", "initial": 0.15, "lower": 0, "upper": None, "unit": "sd", "comment": "Prop.RE(sd)"},
            {"name": "Add_RE", "initial": 0.0, "lower": 0, "upper": None, "unit": "sd", "comment": "Add.RE(sd)"},
        ],
        omega=[
            {"name": "IIV_VM", "initial": 0.222, "fixed": False, "comment": "IIV VM"},
            {"name": "IIV_V", "initial": 0.052, "fixed": False, "comment": "IIV V"},
        ],
        sigma=[
            {"name": "Prop_error", "initial": 1.0, "fixed": True, "comment": "Proportional error PK"},
        ],
        error_model="combined",
        has_tmdd=True,
        is_linear=False,
    ),
}


# =====================================================================
# 模板推荐逻辑
# =====================================================================

def recommended_template_id(
    n_subjects: int = 0,
    dose_range: Optional[Tuple] = None,
    has_weight: bool = False,
    is_mab: bool = True,
    nonlinear_detected: bool = False,
) -> str:
    """
    根据数据特征推荐最简单的合理模板

    Args:
        n_subjects: 受试者数量
        dose_range: (最小剂量, 最大剂量)
        has_weight: 是否有体重数据
        is_mab: 是否为单抗
        nonlinear_detected: 是否检测到非线性PK

    Returns:
        模板ID
    """
    # 检测非线性PK (TMDD信号)
    if nonlinear_detected:
        if dose_range and dose_range[1] / max(dose_range[0], 1e-10) > 10:
            logger.info("检测到非线性PK信号 + 大剂量跨度, 推荐 Michaelis-Menten 模型")
            return "iv_infusion_mm_advan10_trans1"

    # 单抗默认使用二室模型
    if is_mab:
        if has_weight:
            logger.info("单抗 + 有体重数据, 推荐二室+体重协变量模型")
            return "iv_infusion_2c_wt_advan3_trans4"
        else:
            logger.info("单抗, 推荐标准二室模型")
            return "iv_infusion_2c_advan3_trans4"

    # 非单抗: 尝试最简一室模型
    logger.info("推荐一室模型")
    return "iv_infusion_1c_advan1_trans2"


def normalize_input_columns(columns: List[str]) -> List[str]:
    """
    标准化输入列名

    确保列名符合NONMEM命名规范。
    """
    # 标准列名映射
    standard_mapping = {
        "id": "ID",
        "time": "TIME",
        "dv": "DV",
        "amt": "AMT",
        "rate": "RATE",
        "dur": "DUR",
        "cmt": "CMT",
        "dose": "DOSE",
        "mdv": "MDV",
        "evid": "EVID",
        "wt": "WT",
        "age": "AGE",
        "sex": "SEX",
        "study": "STUDY",
        "cycle": "CYCLE",
        "day": "DAY",
        "ntime": "NTIME",
        "type": "TYPE",
        "bql": "BQL",
        "c": "C",
    }

    normalized = []
    for col in columns:
        col_clean = col.strip().strip('"').upper()
        normalized.append(standard_mapping.get(col_clean.lower(), col_clean))

    return normalized


# =====================================================================
# 模板渲染引擎
# =====================================================================

def render_model(
    template_id: str,
    run_id: str,
    data_file: str = "NM_dat_new.csv",
    input_columns: Optional[List[str]] = None,
) -> str:
    """
    从模板渲染NONMEM控制流(.mod文件)

    Args:
        template_id: 模板ID
        run_id: 运行编号
        data_file: 数据文件名
        input_columns: 输入列名列表

    Returns:
        .mod文件内容
    """
    template = TEMPLATES.get(template_id)
    if not template:
        raise ValueError(f"未知模板ID: {template_id}")

    # 默认列名 (单抗标准)
    if not input_columns:
        input_columns = [
            "C", "ID", "CYCLE", "DAY=DROP", "TIME", "NTIME=DROP",
            "DV", "AMT", "RATE", "DUR", "CMT", "DOSE", "MDV", "EVID",
            "BQL", "TYPE", "STUDY", "SEX", "WT", "AGE"
        ]

    lines = []

    # $PROBLEM
    lines.append(f"$PROBLEM")
    lines.append(f";;; Template: {template_id}")
    lines.append(f";;; Description: {template.description}")
    lines.append(f";;; Run ID: {run_id}")
    lines.append(f";;; Author: PopPK_Agent Template Engine")

    # $INPUT
    input_str = " ".join(input_columns)
    lines.append(f"$INPUT {input_str}")

    # $DATA
    lines.append(f"$DATA {data_file} IGNORE=C")

    # $SUBROUTINES
    lines.append(f"$SUBROUTINES {template.advan} {template.trans}")

    # $PK
    lines.append("$PK")

    # 处理体重协变量
    if template_id == "iv_infusion_2c_wt_advan3_trans4":
        lines.append(";;; V1WT-DEFINITION")
        lines.append("   V1WT = ((WT/62.14)**THETA(7))")
        lines.append(";;; V1-RELATION")
        lines.append("V1COV=V1WT")
        lines.append("")

    # 参数定义
    if template.n_compartments == 1:
        if template.advan == "ADVAN10":
            # Michaelis-Menten
            lines.append("D1=DUR")
            lines.append("TVVM = THETA(1)")
            lines.append("VM = TVVM * EXP(ETA(1))")
            lines.append("TVKM = THETA(2)")
            lines.append("KM = TVKM * EXP(ETA(2))")
            lines.append("TVV = THETA(3)")
            lines.append("V = TVV * EXP(ETA(2))")
            lines.append("S1 = V/1000")
        else:
            # 一室线性
            lines.append("D1=DUR")
            lines.append("TVCL = THETA(1)")
            lines.append("CL = TVCL * EXP(ETA(1))")
            lines.append("TVV = THETA(2)")
            lines.append("V = TVV * EXP(ETA(2))")
            lines.append("S1 = V/1000")
    elif template.n_compartments == 2:
        # 二室
        lines.append("D1=DUR")
        lines.append("TVCL = THETA(1)")
        lines.append("CL = TVCL * EXP(ETA(1))")
        lines.append("TVV1 = THETA(2)")

        if template_id == "iv_infusion_2c_wt_advan3_trans4":
            lines.append("TVV1 = V1COV*TVV1")

        lines.append("V1 = TVV1 * EXP(ETA(2))")
        lines.append("TVQ = THETA(3)")
        lines.append("Q  = TVQ * EXP(ETA(3))")
        lines.append("TVV2 = THETA(4)")
        lines.append("V2 = TVV2 * EXP(ETA(4))")
        lines.append("S1 = V1/1000")

    # $ERROR
    lines.append("")
    lines.append("$ERROR")
    lines.append("IPRED = F")

    # 残差模型
    if template.error_model == "combined":
        # 找到Prop和Add的THETA编号
        prop_theta = len([p for p in template.parameters if p["name"] not in ["Prop_RE", "Add_RE"]]) + 1
        add_theta = prop_theta + 1
        lines.append(f"    W = SQRT(THETA({prop_theta})**2*IPRED**2 + THETA({add_theta})**2)")
        lines.append("    Y = IPRED + W*EPS(1)")
    elif template.error_model == "proportional":
        prop_theta = len([p for p in template.parameters if p["name"] not in ["Prop_RE", "Add_RE"]]) + 1
        lines.append(f"    W = THETA({prop_theta})")
        lines.append("    Y = IPRED + W*EPS(1)")
    else:  # additive
        add_theta = len([p for p in template.parameters if p["name"] not in ["Prop_RE", "Add_RE"]]) + 1
        lines.append(f"    W = THETA({add_theta})")
        lines.append("    Y = IPRED + W*EPS(1)")

    lines.append(" IRES = DV-IPRED")
    lines.append("IWRES = IRES/W")

    # $THETA
    lines.append("")
    lines.append("$THETA")
    for i, param in enumerate(template.parameters):
        lower = param.get("lower", "")
        initial = param.get("initial", 0)
        upper = param.get("upper")
        comment = param.get("comment", "")
        if upper is not None:
            lines.append(f"({lower}, {initial}, {upper}) ; {comment}")
        else:
            lines.append(f"({lower}, {initial}) ; {comment}")

    # $OMEGA
    lines.append("")
    lines.append("$OMEGA")
    for om in template.omega:
        init = om["initial"]
        comment = om.get("comment", "")
        if om.get("fixed", False):
            lines.append(f" {init} FIX  ; {comment}")
        else:
            lines.append(f" {init} ; {comment}")

    # $SIGMA
    lines.append("")
    lines.append("$SIGMA")
    for sig in template.sigma:
        init = sig["initial"]
        comment = sig.get("comment", "")
        if sig.get("fixed", False):
            lines.append(f" {init} FIX  ; {comment}")
        else:
            lines.append(f" {init} ; {comment}")

    # $ESTIMATION
    lines.append("")
    lines.append("$EST METHOD=1 INTER MAXEVAL=9999 NOABORT SIG=3 PRINT=10")

    # $COV
    lines.append("$COV")

    # $TABLE
    lines.append("")
    lines.append(f"; Xpose")
    lines.append(
        f"$TABLE ID TIME DV MDV PRED IPRED CWRES CIWRES STUDY "
        f"ONEHEADER NOPRINT NOAPPEND FILE=SDTAB{run_id} FORMAT=s1PE14.7"
    )
    lines.append(
        f"$TABLE ID CL V1 Q V2 ETA1 ETA2 ETA3 ETA4 "
        f"NOPRINT NOAPPEND ONEHEADER FILE=PATAB{run_id}"
    )
    lines.append(
        f"$TABLE ID ETA1 ETA2 ETA3 ETA4 "
        f"FIRSTONLY NOAPPEND NOPRINT FILE=000{run_id}.ETA"
    )
    lines.append(
        f"$TABLE ID WT SEX STUDY "
        f"NOPRINT NOAPPEND ONEHEADER FILE=CATAB{run_id}"
    )
    lines.append(
        f"$TABLE ID AGE "
        f"NOPRINT NOAPPEND ONEHEADER FILE=COTAB{run_id}"
    )

    return "\n".join(lines)
