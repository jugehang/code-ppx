# PopPK Agent - 自动化群体药动学建模平台

基于 LLM 和 PopPK 模型规则库的自动化群体药动学建模平台，当前专注于单克隆抗体 (mAb) 人体研究。

## 核心功能

- **自动化建模循环**: 数据特征分析 → AI选择模型结构 → 生成NONMEM控制流(.mod) → 运行拟合 → 解析LST输出 → 诊断错误 → GOF/VPC评估 → 迭代优化
- **规则库驱动**: 内置FDA法规、单抗药代动力学、NONMEM语法、CDISC数据标准、模型评估等6大命名空间规则
- **多LLM后端支持**: 本地模型(LM Studio/Ollama)、API调用(OpenAI/Claude等)、VS Code插件(Claude Code/Codex)
- **AI视觉诊断**: 自动生成并判读GOF图、VPC图、个体拟合图
- **R脚本集成**: GOF绘图、VPC绘图、个体拟合图、参数表格生成

## 项目结构

```
PopPK_Agent/
├── core/                    # 核心自动化引擎
│   ├── config.py            # 统一配置管理
│   ├── llm_backend.py       # LLM后端抽象层
│   ├── nonmem_runner.py     # NONMEM执行引擎
│   ├── lst_parser.py        # LST文件解析器
│   ├── model_generator.py   # .mod控制流生成器
│   ├── diagnostics.py       # 诊断图生成管道
│   ├── rule_engine.py       # 规则库引擎
│   └── automation_loop.py   # 主自动化循环
├── agents/                  # AI智能体
│   ├── model_selector.py    # 模型结构选择
│   ├── error_diagnostician.py # 错误诊断
│   ├── gof_auditor.py       # GOF视觉审计
│   └── vpc_auditor.py       # VPC视觉审计
├── scripts/                 # R脚本
│   ├── gof_plot_script.R
│   ├── vpc_plot_script.R
│   ├── individual_plot_script.R
│   └── pk_parameters_script.R
├── rules/
│   └── poppk_rules.json     # PopPK规则库
├── config/
│   └── project_config.json  # 项目配置
└── data/                    # 测试数据与模型
```

## 快速开始

### 环境要求

- Python 3.10+
- R 4.0+ (with tidyverse, ggpubr, jsonlite, nonmem2R, flextable, officer)
- NONMEM 7.4+
- PsN (for VPC/bootstrap)

### 安装

```bash
pip install -r requirements.txt
```

### 配置

编辑 `config/project_config.json` 设置项目参数，编辑 `core/config.py` 设置LLM后端。

### 运行自动化建模

```bash
python -m PopPK_Agent.core.automation_loop
```

## 规则库

规则库 (`poppk_rules.json`) 包含以下命名空间:

| 命名空间 | 说明 |
|---------|------|
| @Regulatory | FDA群体药代动力学指南 |
| @BioPhys | 单抗药代动力学特性 |
| @ModelingTechniques | NONMEM控制流语法 |
| @DataStandards | CDISC SDTM/ADaM标准 |
| @ModelEvaluation | GOF、VPC、Bootstrap评估 |
| @CovariateAnalysis | 协变量分析方法 |
| @mAb_EarlyClinical | 单抗早期临床研究 |
| @Reporting | 报告规范 |

## License

MIT
