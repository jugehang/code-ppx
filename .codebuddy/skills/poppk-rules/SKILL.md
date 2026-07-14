---
name: poppk-rules
description: PopPK群体药动学建模规范。强制AI遵循FDA法规、NONMEM语法规范、CDISC数据标准、单抗药代动力学特性和模型评估准则。
allowed-tools:
  - read_file
  - search_content
  - execute_command
---

# PopPK 建模规范规则

## NONMEM 控制流规范

1. 每个记录必须以 `$` 开头，注释以 `;` 表示
2. `$INPUT` 必须使用标准列名: ID, TIME, DV, AMT, RATE, EVID, MDV, CMT
3. `$THETA` 格式: (Lower, Initial, Upper) 或 (Lower, Initial)
4. `$OMEGA` 对角矩阵用于不相关的IIV
5. `$EST` 推荐 METHOD=1 (FOCE-I) + INTER + MAXEVAL=9999
6. `$TABLE` 必须包含 PRED, IPRED, CWRES, CIWRES 用于GOF诊断
7. 每个模型必须有 `$COV` 步骤计算协方差矩阵

## 单抗(mAb)药代动力学特性

1. 非特异性清除率: 90-560 mL/day (通过胞饮作用)
2. 半衰期: 11-30天 (FcRn介导回收)
3. 中央分布容积 V1: 3-5 L
4. IgG亚型 (IgG1/IgG2/IgG4) 半衰期约21天
5. 大剂量跨度时检查TMDD (非线性PK)
6. 需评估免疫原性(ADA)对清除率的影响

## 模型评估准则

1. RSE (相对标准误) < 30% 为可接受
2. Eta-shrinkage < 30% 为可靠
3. |CWRES| 大部分应 < 6
4. |IWRES| vs IPRED 应无趋势 (水平)
5. 嵌套模型比较: ΔOFV > 3.84 (p<0.05), > 6.63 (p<0.01)
6. Bootstrap成功率 > 90% 为稳定
7. VPC: 观测分位数线应落在模拟预测区间内

## 协变量分析规范

1. 连续协变量用幂函数: (WT/70)^THETA (居中于典型值)
2. 分类协变量用比例偏移
3. 前向纳入 p<0.05 (ΔOFV>3.84), 后向剔除 p<0.01 (ΔOFV>6.63)
4. 效应幅度 >20-30% 认为有临床意义
5. 高shrinkage(>30%)参数的协变量效应不可靠

## 数据标准

1. PK浓度数据用CDISC SDTM PC域
2. PK参数数据用PP域
3. 分析数据集用ADaM ADPC/ADPP
4. 必须包含 AVAL, AVISIT 等分析变量

## 报告规范

1. 包含执行摘要、方法、结果、讨论、结论
2. 提交所有电子文件 (数据集.xpt, 控制流.mod, 输出.lst, 报告)
3. 参数需附95%CI或RSE%
4. 包含GOF图、VPC图、Bootstrap结果
