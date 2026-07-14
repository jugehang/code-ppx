---
name: poppk-automation
description: 自动化群体药动学(PopPK)建模。当用户提到NONMEM建模、群体药动学、PK建模、mAb药代动力学、GOF诊断、VPC、模型优化、药动学参数估计等场景时触发。支持从数据到定稿模型的完整自动化流程。
allowed-tools:
  - execute_command
  - read_file
  - write_to_file
  - replace_in_file
  - search_content
  - search_file
  - list_dir
---

# PopPK 自动化群体药动学建模

## 概述

本技能基于LLM和PopPK规则库，实现单克隆抗体(mAb)人体研究的自动化群体药动学建模。
工作流: 数据分析 → AI选择模型结构 → 生成NONMEM控制流(.mod) → 运行拟合 → 解析LST → 诊断图GOF/VPC → AI判读 → 迭代优化 → 定稿。

## 项目结构

```
PopPK_Agent/         - 核心代码和规则库
├── core/            - 自动化引擎
├── agents/           - AI智能体
├── poppk_rules.json  - PopPK规则库(6大命名空间)
├── poppk_model_templates.py - NONMEM模型模板(一室/二室/MM)
├── model_generator.py      - 确定性模型修改引擎
├── mod_validator.py        - .mod文件验证器
├── *.R                     - R诊断脚本
└── *.mod, *.lst            - NONMEM模型和输出文件
CodePPK/             - 编排框架
├── codeppk/engine/  - 主建模循环
├── codeppk/llm/     - LLM后端抽象
└── vscode-extension/ - VS Code扩展
```

## 工作流指令

### 1. 启动自动化建模

当用户要求自动化建模时，执行:

```bash
cd /Users/grahamju/Desktop/CodePPK && python3 -m PopPK_Agent.core.automation_loop --workspace PopPK_Agent --max-iter 20
```

### 2. 运行单个模型

当用户要求运行特定模型时:
1. 确认.mod文件存在 (如 run41.mod)
2. 运行NONMEM: 使用execute_command调用nm74或对应NONMEM可执行文件
3. 运行后解析LST文件: `python3 -c "import sys; sys.path.insert(0,'PopPK_Agent'); from core.lst_parser import LSTParser; p=LSTParser(); r=p.parse('PopPK_Agent/run41.lst',41); print(p.format_summary(r))"`

### 3. GOF图AI审计

当用户要求GOF审计时:
1. 确认GOF_mod{N}.jpg存在
2. 使用规则库判读: 读取PopPK_Agent/poppk_rules.json中的@ModelEvaluation命名空间
3. 引用Rule ID (如ME-GOF-001, ME-GOF-002)给出评价
4. 检查点: DV/PRED是否在对角线两侧, CWRES是否在±6内, |IWRES|vs IPRED是否水平

### 4. VPC图AI审计

当用户要求VPC审计时:
1. 确认VPC_mod{N}.jpg存在
2. 引用ME-VALID-002评估预测区间覆盖
3. 检查点: 观测分位数线是否落在模拟PI内, 中位线覆盖, 变异度预测

### 5. 模型对比

当用户要求对比两个模型时:
1. 分别解析两个LST文件
2. 计算ΔOFV (参考ME-COMP-001: p<0.05需ΔOFV>3.84, p<0.01需>6.63)
3. 对比参数估计、RSE、IIV CV%、Shrinkage
4. 引用规则库评价

## 规则库参考

规则库位于PopPK_Agent/poppk_rules.json，包含6大命名空间:
- @Regulatory: FDA群体药代动力学指南
- @BioPhys: 单抗药代动力学特性(CL 90-560 mL/day, t1/2 11-30天)
- @ModelingTechniques: NONMEM控制流语法
- @DataStandards: CDISC SDTM/ADaM标准
- @ModelEvaluation: GOF/VPC/Bootstrap/Shrinkage评估
- @CovariateAnalysis: 协变量分析(SCM/连续/分类)

## 判定阈值

- RSE < 30%: 参数估计精度可接受
- Shrinkage < 30%: IIV估计可靠
- |CWRES| < 6: 残差可接受
- ΔOFV > 3.84 (p<0.05) 或 > 6.63 (p<0.01): 嵌套模型改进显著
- mAb Vc: 3-5L (中央分布容积)
- mAb CL: 90-560 mL/day

## 注意事项

- NONMEM运行需要设置SDKROOT环境变量 (Mac)
- PsN VPC运行耗时较长, 建议非每次迭代都运行
- AI视觉判读需要多模态模型支持
- 初始值设置参考单抗典型PK参数范围
