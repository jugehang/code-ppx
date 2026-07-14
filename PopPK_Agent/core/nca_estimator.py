"""
NCA初始值估计器

参考 pyDarwin/nlmixr2autoinit 的思路，从数据自动估算NONMEM参数初始值:
- CL: 从剂量/AUC推算 (CL = Dose / AUC)
- V1: 从C0或Cmax推算 (V = Dose / C0)
- Q/V2: 从分布相斜率推算
- t_half: 从末端相log-linear回归
- 残差模型: 从DV变异度估算比例误差

不依赖R的PKNCA包，纯Python实现，避免额外依赖。
"""

import math
import logging
import statistics
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class NCAParameters:
    """NCA估算的参数"""
    cl: float = 0.012       # 清除率 L/h
    v1: float = 4.0         # 中央室容积 L
    q: float = 0.02         # 室间清除率 L/h
    v2: float = 2.0         # 外周室容积 L
    half_life: float = 336.0  # 半衰期 h (单抗~14天)
    alpha_half: float = 24.0  # 分布相半衰期 h
    cmax: float = 0.0       # 最大浓度
    auc0_inf: float = 0.0   # AUC 0-inf
    prop_error: float = 0.15  # 比例误差初值
    add_error: float = 0.0   # 加合误差初值
    estimated: bool = False  # 是否成功估算

    def to_dict(self) -> dict:
        return {
            "CL": round(self.cl, 6),
            "V1": round(self.v1, 2),
            "Q": round(self.q, 6),
            "V2": round(self.v2, 2),
            "t_half": round(self.half_life, 1),
            "Cmax": round(self.cmax, 4),
            "AUC": round(self.auc0_inf, 1),
            "prop_error": round(self.prop_error, 3),
            "estimated": self.estimated,
        }


def estimate_initial_values(
    time_points: List[float],
    concentrations: List[float],
    dose: float,
    route: str = "iv_infusion",
    infusion_duration: float = 0.0,
    wt: float = 70.0,
) -> NCAParameters:
    """
    从浓度-时间数据估算NONMEM初始值

    Args:
        time_points: 时间点列表 (h)
        concentrations: 对应浓度列表 (ng/mL)
        dose: 给药剂量 (mg)
        route: 给药途径
        infusion_duration: 输注持续时间 (h)
        wt: 体重 (kg), 用于标准化

    Returns:
        NCAParameters 估算的初始值
    """
    params = NCAParameters()

    if not time_points or not concentrations or dose <= 0:
        logger.warning("数据不足，使用默认单抗初始值")
        return params

    # 过滤有效数据点 (浓度>0)
    valid = [(t, c) for t, c in zip(time_points, concentrations) if c and c > 0 and t >= 0]
    if len(valid) < 3:
        logger.warning(f"有效数据点不足({len(valid)}<3), 使用默认值")
        return params

    valid.sort(key=lambda x: x[0])
    times = [v[0] for v in valid]
    concs = [v[1] for v in valid]

    params.cmax = max(concs)

    # 1. 估算AUC (梯形法)
    auc = _trapezoid_auc(times, concs)
    if auc <= 0:
        auc = params.cmax * max(times[-1], 1.0) * 0.5  # 粗略估计

    # AUC外推到无穷 (用末端相斜率)
    if len(times) >= 4:
        lambda_z, r2 = _estimate_lambda_z(times, concs)
        if lambda_z and lambda_z > 0 and r2 > 0.7:
            # 外推AUC
            auc_inf = auc + concs[-1] / lambda_z
            params.half_life = math.log(2) / lambda_z
        else:
            auc_inf = auc * 1.5  # 默认外推50%
    else:
        auc_inf = auc * 1.5
        lambda_z = math.log(2) / params.half_life

    params.auc0_inf = auc_inf

    # 2. 估算CL (CL = Dose / AUC)
    # 剂量单位: mg, 浓度: ng/mL, AUC: ng/mL*h
    # CL = Dose(mg) * 1000(ug/mg) * 1000(ng/ug) / AUC(ng/mL*h) / 1000(mL/L) = Dose*1000/AUC (L/h)
    dose_ng = dose * 1e6  # mg -> ng
    cl_est = dose_ng / auc_inf / 1000.0  # L/h

    # 单抗CL范围: 0.004-0.023 L/h (90-560 mL/day)
    cl_est = max(0.001, min(cl_est, 0.1))
    params.cl = cl_est

    # 3. 估算V1 (V = Dose / C0)
    # C0: 初始浓度 (输液后立即)
    if route == "iv_bolus" and times[0] < 0.1:
        c0 = concs[0]
    elif route == "iv_infusion" and infusion_duration > 0:
        # 输液结束时浓度 ≈ Cmax
        c0 = params.cmax
    else:
        c0 = params.cmax

    if c0 > 0:
        v1_est = dose_ng / c0 / 1000.0  # L
    else:
        v1_est = 4.0  # 默认

    # 单抗V1范围: 2-8 L
    v1_est = max(1.0, min(v1_est, 15.0))
    params.v1 = v1_est

    # 4. 估算Q和V2 (从分布相)
    if len(times) >= 6:
        # 分布相斜率 (前1/3数据)
        n_dist = max(3, len(times) // 3)
        alpha_z, alpha_r2 = _estimate_lambda_z(times[:n_dist], concs[:n_dist])
        if alpha_z and alpha_z > lambda_z:
            params.alpha_half = math.log(2) / alpha_z
            # Q/V2 ≈ alpha_z - CL/V1
            k12_k21 = alpha_z - lambda_z
            if k12_k21 > 0:
                params.q = max(0.001, k12_k21 * v1_est * 0.3)
                params.v2 = max(0.5, v1_est * 0.5)

    # 5. 估算残差误差
    # 比例误差: 从DV的变异系数估算
    if len(concs) > 5:
        log_concs = [math.log(c) for c in concs if c > 0]
        if log_concs:
            mean_log = statistics.mean(log_concs)
            sd_log = statistics.stdev(log_concs) if len(log_concs) > 1 else 0.15
            params.prop_error = max(0.05, min(sd_log, 0.5))

    params.estimated = True
    logger.info(f"NCA初始值估算完成: CL={params.cl:.4f} V1={params.v1:.2f} "
                f"Q={params.q:.4f} V2={params.v2:.2f} t1/2={params.half_life:.0f}h "
                f"PropRE={params.prop_error:.3f}")

    return params


def _trapezoid_auc(times: List[float], concs: List[float]) -> float:
    """梯形法计算AUC"""
    auc = 0.0
    for i in range(1, len(times)):
        dt = times[i] - times[i-1]
        auc += (concs[i] + concs[i-1]) / 2.0 * dt
    return auc


def _estimate_lambda_z(
    times: List[float],
    concs: List[float],
    min_points: int = 3
) -> Tuple[float, float]:
    """
    估算末端相消除速率常数 (lambda_z)

    用log-linear回归末端相数据点

    Returns:
        (lambda_z, r_squared)
    """
    if len(times) < min_points:
        return 0.0, 0.0

    # 取末端1/3的数据点
    n = len(times)
    start = max(0, n - n // 2)  # 末端一半
    end_times = times[start:]
    end_concs = concs[start:]

    # 过滤正值
    valid = [(t, c) for t, c in zip(end_times, end_concs) if c > 0]
    if len(valid) < min_points:
        return 0.0, 0.0

    # log-linear回归: ln(C) = ln(C0) - lambda_z * t
    log_concs = [math.log(c) for t, c in valid]
    t_vals = [t for t, c in valid]

    n_pts = len(t_vals)
    if n_pts < 2:
        return 0.0, 0.0

    # 线性回归
    mean_t = statistics.mean(t_vals)
    mean_lc = statistics.mean(log_concs)

    numerator = sum((t - mean_t) * (lc - mean_lc) for t, lc in zip(t_vals, log_concs))
    denominator = sum((t - mean_t) ** 2 for t in t_vals)

    if denominator == 0:
        return 0.0, 0.0

    slope = numerator / denominator
    intercept = mean_lc - slope * mean_t

    # 斜率的绝对值就是lambda_z
    lambda_z = -slope

    if lambda_z <= 0:
        return 0.0, 0.0

    # 计算R²
    predicted = [intercept + slope * t for t in t_vals]
    ss_res = sum((lc - pred) ** 2 for lc, pred in zip(log_concs, predicted))
    ss_tot = sum((lc - mean_lc) ** 2 for lc in log_concs)

    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    return lambda_z, r2


def estimate_from_csv(csv_path: str, profile) -> NCAParameters:
    """从CSV文件估算初始值

    使用每个受试者的中位浓度-时间曲线。
    """
    import csv as csv_mod
    from collections import defaultdict

    # 读取数据 (用csv.reader更健壮)
    with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv_mod.reader(f)
        header = next(reader, None)
        if not header:
            return NCAParameters()

        cols = [c.strip().strip('"').upper() for c in header]

        # 模糊匹配列名
        def find_idx(*names):
            for n in names:
                n_upper = n.upper()
                for i, c in enumerate(cols):
                    if c == n_upper or n_upper in c or c in n_upper:
                        return i
            return -1

        id_idx = find_idx("ID", "SUBJECT")
        time_idx = find_idx("TIME", "TAD")
        dv_idx = find_idx("DV", "CONC")
        amt_idx = find_idx("AMT", "DOSE", "AMOUNT")
        dur_idx = find_idx("DUR", "DURATION")
        wt_idx = find_idx("WT", "WEIGHT")

        if time_idx < 0 or dv_idx < 0:
            return NCAParameters()

        # 收集所有受试者的浓度-时间数据
        subject_data = defaultdict(list)  # {id: [(time, conc), ...]}
        doses = set()
        durations = []

        def safe_val(row, idx):
            if 0 <= idx < len(row):
                v = row[idx].strip()
                if v and v != '.':
                    try:
                        return float(v)
                    except ValueError:
                        return None
            return None

        for row in reader:
            sid = safe_val(row, id_idx)
            t = safe_val(row, time_idx)
            dv = safe_val(row, dv_idx)
            amt = safe_val(row, amt_idx)
            dur = safe_val(row, dur_idx)

            if amt and amt > 0:
                doses.add(amt)
            if dur and dur > 0:
                durations.append(dur)
            if dv and dv > 0 and t is not None:
                subject_data[sid].append((t, dv))

    if not subject_data or not doses:
        return NCAParameters()

    # 使用中位数曲线 (更鲁棒)
    all_times = sorted(set(t for sid_data in subject_data.values() for t, c in sid_data))
    median_curve = []
    for t in all_times:
        concs_at_t = [c for sid_data in subject_data.values()
                      for tt, c in sid_data if abs(tt - t) < 0.5]
        if concs_at_t:
            median_curve.append((t, statistics.median(concs_at_t)))

    if len(median_curve) < 3:
        # 降级用数据最多的受试者
        best_sid = max(subject_data, key=lambda s: len(subject_data[s]))
        median_curve = subject_data[best_sid]

    median_curve.sort()
    times = [t for t, c in median_curve]
    concs = [c for t, c in median_curve]

    dose = max(doses)
    dur = statistics.median(durations) if durations else 0.0
    route = profile.route if profile else "iv_infusion"

    return estimate_initial_values(times, concs, dose, route, dur)
