#!/usr/bin/env python3
"""
PopPK Agent - 通用自动化群体药动学建模工具

设计理念 (对标pyDarwin):
  pyDarwin: Template + Tokens + 搜索算法 → 穷举候选空间 → fitness排序
  本工具:   数据画像 + NCA初始值 + AI诊断迭代 → 智能优化路径

核心流程:
  1. 任意NONMEM CSV → 自动数据画像 (列名/途径/协变量/非线性信号)
  2. NCA法估算初始值 (CL/V/Q/V2/残差) — 不需要手动设
  3. 生成最简模型 → 运行NONMEM → 解析LST
  4. AI诊断: LST参数 + GOF图 + VPC图 → 综合信号
  5. AI决策: 定稿/加协变量/改误差/升级结构/调初始值
  6. 确定性执行决策 → 生成新模型 → 回到步骤3
  7. 直到定稿或达到最大迭代

用法:
  poppk run --data your_data.csv                  # 自动建模(默认10轮迭代)
  poppk run --data your_data.csv --max-iter 20    # 指定最大迭代
  poppk run --data your_data.csv --no-vpc          # 跳过VPC加速
  poppk features --data your_data.csv              # 只看数据画像
  poppk nca --data your_data.csv                   # 只看NCA初始值
  poppk generate --data your_data.csv --run 1      # 只生成模型
  poppk audit --workspace ./work --curr 1          # 审计已有模型
"""

import sys
import os
import csv
import json
import re
import argparse
import logging
import shutil
import subprocess
import statistics
import traceback
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set

SCRIPT_DIR = Path(__file__).resolve().parent
POPPK_AGENT = SCRIPT_DIR / "PopPK_Agent"
for p in [str(POPPK_AGENT), str(SCRIPT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("poppk")

SDK_PATH = "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk"
NMFE_PATH = os.getenv("POPPK_NONMEM_PATH", "/opt/nm760/util/nmfe76")


# =====================================================================
# 1. 数据画像 - 适配任何NONMEM CSV
# =====================================================================

@dataclass
class DataProfile:
    csv_path: str = ""
    csv_name: str = ""
    columns: List[str] = field(default_factory=list)
    input_columns: List[str] = field(default_factory=list)

    has_id: bool = False
    has_time: bool = False
    has_dv: bool = False
    has_amt: bool = False
    has_rate: bool = False
    has_dur: bool = False
    has_cmt: bool = False
    has_evid: bool = False
    has_mdv: bool = False
    has_bql: bool = False

    n_subjects: int = 0
    n_records: int = 0
    n_observations: int = 0
    dose_range: Tuple[float, float] = (0, 0)
    n_dose_levels: int = 0
    dv_range: Tuple[float, float] = (0, 0)
    time_range: Tuple[float, float] = (0, 0)
    wt_median: float = 70.0

    route: str = "iv_infusion"
    continuous_covariates: List[str] = field(default_factory=list)
    categorical_covariates: List[str] = field(default_factory=list)
    grouping: Optional[str] = None
    grouping_labels: Dict[str, str] = field(default_factory=dict)
    has_nonlinear_pk: bool = False
    cmt_values: Set[int] = field(default_factory=set)

    def is_valid(self) -> bool:
        return self.has_id and self.has_time and self.has_dv and self.has_amt

    def summary(self) -> str:
        return (
            f"受试者={self.n_subjects} 记录={self.n_records} 观测={self.n_observations}\n"
            f"  途径={self.route} 剂量={self.dose_range[0]:.1f}~{self.dose_range[1]:.1f} ({self.n_dose_levels}级)\n"
            f"  浓度={self.dv_range[0]:.2f}~{self.dv_range[1]:.2f} 时间=0~{self.time_range[1]:.0f}h\n"
            f"  连续协变量={self.continuous_covariates}\n"
            f"  分类协变量={self.categorical_covariates}\n"
            f"  分组={self.grouping} BQL={'是' if self.has_bql else '否'}\n"
            f"  非线性PK={'疑似TMDD' if self.has_nonlinear_pk else '否'}"
        )


COL_ALIASES = {
    "ID": ["ID", "SUBJECT", "USUBJID", "SUBJID", "PATIENT"],
    "TIME": ["TIME", "TAD", "TAFD", "TIMEPOINT"],
    "DV": ["DV", "CONC", "PCSTRESN", "AVAL", "CONCENTRATION"],
    "AMT": ["AMT", "DOSE", "AMOUNT"],
    "RATE": ["RATE", "INFRATE"],
    "DUR": ["DUR", "DURATION", "INFUSION", "INFTIME"],
    "CMT": ["CMT", "COMPARTMENT", "COMP"],
    "EVID": ["EVID", "EVENT"],
    "MDV": ["MDV"],
    "BQL": ["BQL", "BLQ", "LLOQ", "LOQ"],
    "WT": ["WT", "WEIGHT", "BW"],
    "AGE": ["AGE", "AGEYRS"],
    "SEX": ["SEX", "GENDER"],
    "RACE": ["RACE", "ETHNIC"],
    "STUDY": ["STUDY", "TRIAL", "STUDYID"],
    "CRCL": ["CRCL", "CRCLCR"],
    "SCR": ["SCR", "CREAT"],
    "ALB": ["ALB", "ALBUMIN"],
    "BSA": ["BSA"],
    "BMI": ["BMI"],
    "ADA": ["ADA", "ADAFLAG"],
    "ARM": ["ARM", "TRT", "TREATMENT", "REGIMEN"],
}


def profile_dataset(csv_path: str) -> DataProfile:
    """自动分析任何NONMEM格式CSV"""
    path = Path(csv_path)
    if not path.exists():
        return DataProfile()

    profile = DataProfile(csv_path=str(path), csv_name=path.name)

    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return profile

            raw_cols = [c.strip().strip('"') for c in header]
            upper_cols = [c.upper() for c in raw_cols]
            profile.columns = upper_cols

            # 模糊匹配标准列名
            col_mapping = {}
            for std_name, aliases in COL_ALIASES.items():
                for col in upper_cols:
                    if col in aliases or any(a in col for a in aliases if len(a) >= 3):
                        col_mapping[col] = std_name
                        break

            profile.input_columns = [col_mapping.get(c, c) for c in upper_cols]

            for name in ["ID", "TIME", "DV", "AMT", "RATE", "DUR", "CMT", "EVID", "MDV", "BQL"]:
                setattr(profile, f"has_{name.lower()}", name in col_mapping.values())

            CONTINUOUS = {"WT", "AGE", "BSA", "BMI", "CRCL", "SCR", "ALB"}
            CATEGORICAL = {"SEX", "RACE", "STUDY", "ADA", "ARM"}
            for std in col_mapping.values():
                if std in CONTINUOUS and std not in profile.continuous_covariates:
                    profile.continuous_covariates.append(std)
                elif std in CATEGORICAL and std not in profile.categorical_covariates:
                    profile.categorical_covariates.append(std)

            for g in ["STUDY", "ARM", "TRT", "REGIMEN"]:
                if g in col_mapping.values():
                    profile.grouping = g
                    break

            # 解析数据行
            def col_idx(name):
                for orig, std in col_mapping.items():
                    if std == name:
                        return upper_cols.index(orig)
                return -1

            indices = {n: col_idx(n) for n in
                       ["ID", "TIME", "DV", "AMT", "RATE", "DUR", "CMT", "EVID", "WT"]}
            indices["group"] = col_idx(profile.grouping) if profile.grouping else -1

            def sf(row, idx):
                if 0 <= idx < len(row):
                    try: return float(row[idx])
                    except: return None
                return None

            subjects = set()
            doses = set()
            cmts = set()
            dvs = []
            times = []
            wts = []
            groups = {}
            has_rate = has_dur = False

            for row in reader:
                if not row: continue
                profile.n_records += 1

                sid = sf(row, indices["ID"])
                if sid is not None: subjects.add(sid)

                amt = sf(row, indices["AMT"])
                dv = sf(row, indices["DV"])
                rate = sf(row, indices["RATE"])
                dur = sf(row, indices["DUR"])
                cmt = sf(row, indices["CMT"])
                evid = sf(row, indices["EVID"])
                t = sf(row, indices["TIME"])
                wt = sf(row, indices["WT"])
                g = sf(row, indices["group"])

                if cmt is not None: cmts.add(int(cmt))
                if amt and amt > 0:
                    doses.add(amt)
                    if rate and rate > 0: has_rate = True
                    if dur and dur > 0: has_dur = True
                if dv and dv > 0 and (evid is None or evid == 0) and (amt is None or amt == 0):
                    profile.n_observations += 1
                    dvs.append(dv)
                if t is not None: times.append(t)
                if wt and wt > 0: wts.append(wt)
                if g is not None and profile.grouping:
                    gv = str(int(g) if g == int(g) else g)
                    groups[gv] = groups.get(gv, 0) + 1

            profile.n_subjects = len(subjects)
            profile.cmt_values = cmts
            profile.has_rate = profile.has_rate and has_rate
            profile.has_dur = profile.has_dur and has_dur

            if doses:
                profile.dose_range = (min(doses), max(doses))
                profile.n_dose_levels = len(doses)
            if dvs: profile.dv_range = (min(dvs), max(dvs))
            if times: profile.time_range = (min(times), max(times))
            if wts: profile.wt_median = statistics.median(wts)

            if groups:
                for gv in sorted(groups.keys()):
                    try:
                        g = float(gv)
                        label = f"{g} mg/kg" if g < 1 else f"{g:.0f} mg"
                    except: label = f"Group {gv}"
                    profile.grouping_labels[gv] = label

            # 给药途径
            if has_rate or has_dur:
                profile.route = "iv_infusion"
            elif cmts:
                profile.route = "extravascular" if (1 in cmts and 2 in cmts) else "iv_bolus"
            else:
                profile.route = "iv_bolus"

            # 非线性PK信号
            ratio = profile.dose_range[1] / profile.dose_range[0] if profile.dose_range[0] > 0 else 0
            profile.has_nonlinear_pk = len(doses) >= 3 and ratio >= 10

    except Exception as e:
        logger.error(f"数据解析失败: {e}")

    return profile


# =====================================================================
# 2. NCA初始值估计器
# =====================================================================

def estimate_nca(csv_path: str, profile: DataProfile) -> dict:
    """从数据估算NONMEM参数初始值 (NCA法)"""
    try:
        from core.nca_estimator import estimate_from_csv
        params = estimate_from_csv(csv_path, profile)
        return params.to_dict()
    except Exception as e:
        logger.error(f"NCA估算失败: {e}, 使用默认值")
        return {"CL": 0.012, "V1": 4.0, "Q": 0.02, "V2": 2.0, "prop_error": 0.15, "estimated": False}


# =====================================================================
# 3. 自适应模型生成 (使用NCA初始值)
# =====================================================================

def generate_model(profile: DataProfile, run_id: str, nca: dict = None) -> str:
    """根据数据画像+NCA初始值生成NONMEM控制流"""
    cols = profile.input_columns
    csv_name = profile.csv_name
    route = profile.route
    has_wt = "WT" in profile.continuous_covariates
    wt_center = profile.wt_median

    # 使用NCA估算的初始值
    cl = nca.get("CL", 0.012) if nca else 0.012
    v1 = nca.get("V1", 4.0) if nca else 4.0
    q = nca.get("Q", 0.02) if nca else 0.02
    v2 = nca.get("V2", 2.0) if nca else 2.0
    prop = nca.get("prop_error", 0.15) if nca else 0.15

    use_wt = has_wt
    n_pk = 4
    n_extra = 1 if use_wt else 0
    prop_theta = n_pk + n_extra + 1
    add_theta = n_pk + n_extra + 2
    wt_theta = n_pk + 1 if use_wt else None

    lines = [
        f"$PROBLEM",
        f";;; Auto-generated by PopPK Agent",
        f";;; Data: {csv_name} | Route: {route}",
        f";;; NCA-init: CL={cl:.4f} V1={v1:.2f} Q={q:.4f} V2={v2:.2f}",
        f"$INPUT {' '.join(cols)}",
        f"$DATA {csv_name} IGNORE=C",
        f"$SUBROUTINES ADVAN3 TRANS4",
        f"$PK",
    ]

    if use_wt:
        lines.append(f"   V1WT = ((WT/{wt_center:.1f})**THETA({wt_theta}))")
        lines.append(f"V1COV=V1WT")

    if route == "iv_infusion":
        if "DUR" in cols: lines.append("D1=DUR")
        elif "RATE" in cols: lines.append("D1=AMT/RATE")

    lines.extend([
        f"TVCL = THETA(1)", f"CL = TVCL * EXP(ETA(1))",
        f"TVV1 = THETA(2)",
    ])
    if use_wt: lines.append(f"TVV1 = V1COV*TVV1")
    lines.extend([
        f"V1 = TVV1 * EXP(ETA(2))",
        f"TVQ = THETA(3)", f"Q  = TVQ * EXP(ETA(3))",
        f"TVV2 = THETA(4)", f"V2 = TVV2 * EXP(ETA(4))",
        f"S1 = V1/1000",
        f"", f"$ERROR", f"IPRED = F",
        f"    W = SQRT(THETA({prop_theta})**2*IPRED**2 + THETA({add_theta})**2)",
        f"    Y = IPRED + W*EPS(1)",
        f" IRES = DV-IPRED", f"IWRES = IRES/W",
        f"", f"$THETA",
        f"(0, {cl:.6f}) ; CL_L/h",
        f"(0, {v1:.2f}) ; V1_L",
        f"(0, {q:.6f}) ; Q_L/h",
        f"(0, {v2:.2f}) ; V2_L",
    ])
    if use_wt: lines.append(f"(0, 0.75) ; V1WT_power")
    lines.append(f"(0, {prop:.3f}) ; Prop.RE(sd)")
    lines.append(f"(0) FIX ; Add.RE(sd)")
    lines.extend([
        f"", f"$OMEGA", f" 0.2 ; IIV CL", f" 0.05 ; IIV V1",
        f" 0 FIX ; IIV Q", f" 0 FIX ; IIV V2",
        f"", f"$SIGMA", f" 1 FIX ; Prop error",
        f"", f"$EST METHOD=1 INTER MAXEVAL=9999 NOABORT SIG=3 PRINT=10",
        f"$COV",
        f"", f"; Xpose",
    ])
    gof_cols = ["ID", "TIME", "DV", "MDV", "PRED", "IPRED", "CWRES", "CIWRES"]
    if profile.grouping: gof_cols.append(profile.grouping)
    lines.append(f"$TABLE {' '.join(gof_cols)} ONEHEADER NOPRINT NOAPPEND FILE=SDTAB{run_id} FORMAT=s1PE14.7")
    lines.append(f"$TABLE ID CL V1 Q V2 ETA1 ETA2 ETA3 ETA4 NOPRINT NOAPPEND ONEHEADER FILE=PATAB{run_id}")
    lines.append(f"$TABLE ID ETA1 ETA2 ETA3 ETA4 FIRSTONLY NOAPPEND NOPRINT FILE=000{run_id}.ETA")
    cat = [c for c in profile.categorical_covariates if c in cols]
    if cat: lines.append(f"$TABLE ID {' '.join(cat)} NOPRINT NOAPPEND ONEHEADER FILE=CATAB{run_id}")
    cont = [c for c in profile.continuous_covariates if c in cols]
    if cont: lines.append(f"$TABLE ID {' '.join(cont)} NOPRINT NOAPPEND ONEHEADER FILE=COTAB{run_id}")

    return "\n".join(lines) + "\n"


# =====================================================================
# 4. NONMEM执行 + LST解析 + 诊断图
# =====================================================================

def run_nonmem(work_dir: str, run_id: str) -> Tuple[bool, str]:
    mod = f"run{run_id}.mod"
    lst = f"run{run_id}.lst"
    if not os.path.exists(NMFE_PATH):
        return False, f"NONMEM未找到: {NMFE_PATH}"
    env = {**os.environ, "SDKROOT": SDK_PATH,
           "LIBRARY_PATH": f"{SDK_PATH}/usr/lib", "CPATH": f"{SDK_PATH}/usr/include"}
    try:
        r = subprocess.run([NMFE_PATH, mod, lst], cwd=work_dir, env=env,
                           capture_output=True, text=True, timeout=600)
        return (Path(work_dir) / lst).exists(), r.stdout + r.stderr
    except subprocess.TimeoutExpired: return False, "超时"
    except Exception as e: return False, str(e)


def parse_lst(work_dir: str, run_id: str) -> dict:
    try:
        from core.lst_parser import LSTParser
        p = LSTParser()
        r = p.parse(str(Path(work_dir) / f"run{run_id}.lst"), int(run_id))
        return {"success": r.success, "ofv": r.ofv, "warnings": r.warnings,
                "errors": r.error_messages, "summary": p.format_summary(r),
                "final_estimates": r.final_estimates, "control_stream": r.control_stream,
                "shrinkage": r.shrinkage}
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_r(work_dir: str, script: str, *args) -> Tuple[bool, str]:
    if not (Path(work_dir) / script).exists(): return False, "脚本不存在"
    try:
        r = subprocess.run(["Rscript", script] + list(args), cwd=work_dir,
                           capture_output=True, text=True, timeout=120)
        return r.returncode == 0, r.stdout + r.stderr
    except Exception as e: return False, str(e)


def fix_sdtab(work_dir: str, run_id: str):
    lo = Path(work_dir) / f"sdtab{run_id}"
    up = Path(work_dir) / f"SDTAB{run_id}"
    if lo.exists() and not up.exists(): lo.rename(up)


def audit_gof_ai(work_dir: str, run_id: str, prev_id: str = None) -> str:
    """AI视觉审计GOF图"""
    gof = Path(work_dir) / f"GOF_mod{run_id}.jpg"
    if not gof.exists(): return ""
    try:
        from core.config import LLMConfig, PopPKConfig
        from core.llm_backend import create_llm_backend
        from core.rule_engine import RuleEngine
        from core.diagnostics import DiagnosticsPipeline
        from core.nonmem_runner import NonmemRunner
        llm = create_llm_backend(LLMConfig.from_env())
        rules = RuleEngine(str(Path(work_dir) / "poppk_rules.json"))
        cfg = PopPKConfig()
        cfg.workspace_dir = work_dir
        diag = DiagnosticsPipeline(cfg, llm, rules, NonmemRunner(cfg))
        prev = str(Path(work_dir) / f"GOF_mod{prev_id}.jpg") if prev_id and (Path(work_dir) / f"GOF_mod{prev_id}.jpg").exists() else None
        return diag.audit_gof(int(run_id), str(gof), prev).get("report", "")
    except Exception as e:
        return f"审计失败: {e}"


# =====================================================================
# 5. 工作目录初始化
# =====================================================================

def init_workspace(work_dir: str, csv_path: str) -> str:
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    src = Path(csv_path)
    dst = work / src.name
    if src.resolve() != dst.resolve() and src.exists():
        shutil.copy2(src, dst)
    for s in ["gof_plot_script.R", "vpc_plot_script.R", "individual_plot_script.R", "pk parameters script.R"]:
        src = POPPK_AGENT / s
        dst = work / s
        if src.exists() and not dst.exists(): shutil.copy2(src, dst)
    rules_src = POPPK_AGENT / "poppk_rules.json"
    rules_dst = work / "poppk_rules.json"
    if rules_src.exists() and not rules_dst.exists(): shutil.copy2(rules_src, rules_dst)
    return str(work)


# =====================================================================
# 6. 自动化迭代主循环 (对标pyDarwin的迭代搜索)
# =====================================================================

def run_automation(csv_path: str, work_dir: str, max_iter: int = 10, run_vpc: bool = True):
    """完整自动化建模循环"""
    work_dir = init_workspace(work_dir, csv_path)
    csv_name = Path(csv_path).name

    print(f"\n{'#' * 70}")
    print(f"#  PopPK Agent 自动化建模")
    print(f"#  数据: {csv_name}")
    print(f"#  工作目录: {work_dir}")
    print(f"#  NONMEM: {NMFE_PATH}")
    print(f"#  最大迭代: {max_iter}")
    print(f"{'#' * 70}\n")

    # 1. 数据画像
    print("=== Step 1: 数据画像 ===")
    profile = profile_dataset(str(Path(work_dir) / csv_name))
    if not profile.is_valid():
        print(f"  错误: 缺少必需列 (ID/TIME/DV/AMT)")
        return 1
    print(f"  {profile.summary()}")
    print()

    # 2. NCA初始值
    print("=== Step 2: NCA初始值估算 ===")
    nca = estimate_nca(str(Path(work_dir) / csv_name), profile)
    print(f"  CL={nca['CL']} V1={nca['V1']} Q={nca['Q']} V2={nca['V2']}")
    print(f"  PropRE={nca['prop_error']} t1/2={nca.get('t_half', 'N/A')}h")
    print(f"  NCA成功: {nca.get('estimated', False)}")
    print()

    # 3. 生成project_config
    config = {
        "project_name": f"PopPK_{Path(csv_name).stem}",
        "drug_type": "Monoclonal Antibody (mAb)",
        "data_file": csv_name,
        "units": {"time": "Time (h)", "conc": "Concentration (ng/mL)"},
        "grouping": {"factor": profile.grouping or "STUDY", "labels": profile.grouping_labels},
        "psn_settings": {"vpc_samples": 500, "stratify_var": profile.grouping or "STUDY"},
    }
    (Path(work_dir) / "project_config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False))

    # 迭代循环
    prev_ofv = None
    prev_run_id = None
    history = []

    for iteration in range(1, max_iter + 1):
        run_id = str(iteration)

        print(f"\n{'=' * 60}")
        print(f"  迭代 #{iteration} | Run {run_id}")
        print(f"{'=' * 60}")

        # 生成/修改模型
        if iteration == 1:
            print(f"[{iteration}.1] 生成初始模型...")
            mod_content = generate_model(profile, run_id, nca)
        else:
            print(f"[{iteration}.1] AI诊断决策...")
            # AI诊断上一次的结果
            try:
                from core.diagnostic_engine import DiagnosticEngine, apply_decision
                from core.config import LLMConfig
                from core.llm_backend import create_llm_backend
                from core.rule_engine import RuleEngine

                llm = create_llm_backend(LLMConfig.from_env())
                rules = RuleEngine(str(Path(work_dir) / "poppk_rules.json"))
                engine = DiagnosticEngine(llm, rules)

                decision = engine.diagnose_and_decide(
                    run_id=prev_run_id,
                    lst_result=prev_lst,
                    gof_report=prev_gof,
                    vpc_report="",
                    prev_ofv=prev_ofv,
                    iteration=iteration,
                    data_profile={"continuous_covariates": profile.continuous_covariates,
                                  "categorical_covariates": profile.categorical_covariates},
                )

                print(f"  决策: {decision.action.value}")
                print(f"  原因: {decision.reason}")
                print(f"  置信度: {decision.confidence:.0%}")

                if decision.action.value == "finalize":
                    print("\n  *** AI判定模型已达标, 建议定稿! ***")
                    break
                if decision.action.value == "stop":
                    print("\n  *** AI建议停止迭代 ***")
                    break

                # 应用决策到前序模型
                prev_mod = (Path(work_dir) / f"run{prev_run_id}.mod").read_text()
                mod_content = apply_decision(prev_mod, decision, nca)
                mod_content = _bump_run_id(mod_content, prev_run_id, run_id)

            except Exception as e:
                print(f"  AI诊断失败: {e}, 用前序模型重跑")
                mod_content = (Path(work_dir) / f"run{prev_run_id}.mod").read_text()
                mod_content = _bump_run_id(mod_content, prev_run_id, run_id)

        # 保存模型
        (Path(work_dir) / f"run{run_id}.mod").write_text(mod_content, encoding="utf-8")

        # 验证
        print(f"[{iteration}.2] 验证模型...")
        try:
            from mod_validator import validate_mod
            vr = validate_mod(Path(work_dir) / f"run{run_id}.mod", Path(work_dir),
                               Path(work_dir) / csv_name, run_id)
            print(f"  {vr.summary()}")
        except: pass

        # 运行NONMEM
        print(f"[{iteration}.3] 运行 NONMEM...")
        ok, log = run_nonmem(work_dir, run_id)
        print(f"  {'成功' if ok else '失败'}")
        if not ok:
            print(f"  日志: {log[-300:]}")
            prev_lst = {"success": False, "errors": [log[-500:]], "ofv": None}
            prev_gof = ""
            prev_run_id = run_id
            continue

        # 解析LST
        print(f"[{iteration}.4] 解析 LST...")
        lst = parse_lst(work_dir, run_id)
        print(f"  OFV: {lst.get('ofv', 'N/A')}")
        if lst.get("warnings"): print(f"  警告: {lst['warnings'][:2]}")

        # GOF图
        print(f"[{iteration}.5] 生成 GOF 图...")
        fix_sdtab(work_dir, run_id)
        run_r(work_dir, "gof_plot_script.R", run_id)
        gof_path = Path(work_dir) / f"GOF_mod{run_id}.jpg"
        print(f"  {'成功' if gof_path.exists() else '失败'}")

        # AI审计GOF
        print(f"[{iteration}.6] AI 审计 GOF...")
        gof_report = audit_gof_ai(work_dir, run_id, prev_run_id)
        if gof_report:
            print(f"  审计完成 ({len(gof_report)} chars)")
            (Path(work_dir) / f"GOF_Audit_Run{run_id}.md").write_text(gof_report, encoding="utf-8")

        # 记录历史
        d_ofv = (lst.get("ofv", 0) or 0) - (prev_ofv or 0) if prev_ofv else None
        history.append({
            "run_id": run_id, "iteration": iteration,
            "ofv": lst.get("ofv"), "d_ofv": d_ofv,
            "success": lst.get("success", False),
        })

        prev_ofv = lst.get("ofv")
        prev_run_id = run_id
        prev_lst = lst
        prev_gof = gof_report

    # 保存历史
    (Path(work_dir) / "automation_history.json").write_text(
        json.dumps(history, indent=2, default=str), encoding="utf-8")

    print(f"\n{'#' * 70}")
    print(f"  自动化建模完成!")
    print(f"  总迭代: {len(history)}")
    print(f"  最终OFV: {prev_ofv}")
    print(f"  工作目录: {work_dir}")
    print(f"{'#' * 70}\n")

    return 0


def _bump_run_id(mod_content: str, old_id: str, new_id: str) -> str:
    """更新控制流中的运行编号"""
    for pattern in [f"SDTAB{old_id}", f"PATAB{old_id}", f"000{old_id}.ETA",
                    f"CATAB{old_id}", f"COTAB{old_id}"]:
        new_pattern = pattern.replace(old_id, new_id)
        mod_content = mod_content.replace(pattern, new_pattern)
    return mod_content


# =====================================================================
# 7. 命令行接口
# =====================================================================

def main():
    parser = argparse.ArgumentParser(
        prog="poppk",
        description="PopPK Agent - 通用自动化群体药动学建模工具"
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("run", help="一键自动化建模")
    p.add_argument("--data", "-d", required=True, help="NONMEM CSV数据文件")
    p.add_argument("--workspace", "-w", default=None, help="工作目录")
    p.add_argument("--max-iter", type=int, default=10, help="最大迭代次数")
    p.add_argument("--no-vpc", action="store_true", help="跳过VPC")
    p.set_defaults(func=lambda a: run_automation(
        a.data, a.workspace or str(Path(a.data).parent / "poppk_workspace"),
        a.max_iter, not a.no_vpc))

    p = sub.add_parser("features", help="数据画像")
    p.add_argument("--data", "-d", required=True)
    p.set_defaults(func=lambda a: (lambda p: (print(f"\n=== {p.csv_name} ===\n  {p.summary()}"), 0)[1])(profile_dataset(a.data)))

    p = sub.add_parser("nca", help="NCA初始值估算")
    p.add_argument("--data", "-d", required=True)
    p.set_defaults(func=lambda a: (lambda p: (print(f"\n=== NCA初始值 ===\n{json.dumps(estimate_nca(a.data, p), indent=2)}"), 0)[1])(profile_dataset(a.data)))

    p = sub.add_parser("generate", help="只生成模型")
    p.add_argument("--data", "-d", required=True)
    p.add_argument("--run", default="1")
    p.add_argument("--output", "-o", default=None)
    p.set_defaults(func=lambda a: (lambda p, n: (lambda m: (Path(a.output or f"run{a.run}.mod").write_text(m), print(f"生成: {a.output or f'run{a.run}.mod'}"), 0)[2])(generate_model(p, a.run, n)))(profile_dataset(a.data), estimate_nca(a.data, profile_dataset(a.data))))

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
