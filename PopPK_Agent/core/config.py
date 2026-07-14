"""
统一配置管理模块

支持从JSON配置文件和环境变量加载配置，
统一管理LLM后端、NONMEM路径、项目参数等。
"""

import os
import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """LLM后端配置"""
    backend: str = "lmstudio"  # lmstudio | ollama | openai | claude | codex
    base_url: str = "http://localhost:1234/v1"
    api_key: str = "lm-studio"
    model_id: str = "google/gemma-4-26b-a4b"
    temperature: float = 0.1
    max_tokens: int = 4000
    vision_model_id: Optional[str] = None  # 视觉模型ID，如果与文本模型不同

    @classmethod
    def from_env(cls):
        """从环境变量加载"""
        return cls(
            backend=os.getenv("POPPK_LLM_BACKEND", "lmstudio"),
            base_url=os.getenv("POPPK_LLM_BASE_URL", "http://localhost:1234/v1"),
            api_key=os.getenv("POPPK_LLM_API_KEY", "lm-studio"),
            model_id=os.getenv("POPPK_LLM_MODEL_ID", "google/gemma-4-26b-a4b"),
            temperature=float(os.getenv("POPPK_LLM_TEMPERATURE", "0.1")),
            max_tokens=int(os.getenv("POPPK_LLM_MAX_TOKENS", "4000")),
            vision_model_id=os.getenv("POPPK_LLM_VISION_MODEL_ID"),
        )


@dataclass
class NonmemConfig:
    """NONMEM运行环境配置"""
    nonmem_path: str = "/usr/local/bin/nm74"  # NONMEM可执行文件路径
    psn_path: str = "/usr/local/bin/vpc"      # PsN vpc命令路径
    rscript_path: str = "Rscript"              # Rscript路径
    sdk_path: str = "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk"
    max_eval: int = 9999
    estimation_method: str = "1"  # FOCE-I
    run_cov: bool = True

    def get_env(self):
        """获取NONMEM运行所需的环境变量"""
        env = os.environ.copy()
        env["SDKROOT"] = self.sdk_path
        env["LIBRARY_PATH"] = f"{self.sdk_path}/usr/lib"
        env["CPATH"] = f"{self.sdk_path}/usr/include"
        return env


@dataclass
class ProjectConfig:
    """项目配置"""
    project_name: str = "TEST_mAb_PopPK"
    drug_type: str = "Monoclonal Antibody (mAb)"
    units: dict = field(default_factory=lambda: {"time": "Time (h)", "conc": "Concentration (ng/mL)"})
    grouping: dict = field(default_factory=dict)
    psn_settings: dict = field(default_factory=dict)
    data_file: str = "NM_dat_new.csv"

    @classmethod
    def from_json(cls, path: str):
        """从JSON文件加载"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return cls(
                project_name=data.get("project_name", "TEST_mAb_PopPK"),
                drug_type=data.get("drug_type", "Monoclonal Antibody (mAb)"),
                units=data.get("units", {"time": "Time (h)", "conc": "Concentration (ng/mL)"}),
                groupings=data.get("groupings", {}),
                psn_settings=data.get("psn_settings", {}),
                data_file=data.get("data_file", "NM_dat_new.csv"),
            )
        except Exception as e:
            logger.error(f"加载项目配置失败: {e}")
            return cls()


@dataclass
class PopPKConfig:
    """PopPK Agent 总配置"""
    llm: LLMConfig = field(default_factory=LLMConfig.from_env)
    nonmem: NonmemConfig = field(default_factory=NonmemConfig)
    project: ProjectConfig = field(default_factory=ProjectConfig)

    # 路径
    workspace_dir: str = "."
    rules_file: str = "poppk_rules.json"
    project_config_file: str = "project_config.json"

    # 自动化循环参数
    max_iterations: int = 20
    ofv_threshold: float = 3.84  # ΔOFV显著性阈值 (p<0.05)
    rse_threshold: float = 30.0   # RSE可接受阈值
    shrinkage_threshold: float = 30.0  # Shrinkage可接受阈值
    cwres_threshold: float = 6.0  # |CWRES|阈值

    @classmethod
    def load(cls, workspace_dir: str = "."):
        """加载完整配置"""
        config = cls()
        config.workspace_dir = str(Path(workspace_dir).resolve())

        # 加载项目配置
        proj_config_path = Path(workspace_dir) / "project_config.json"
        if proj_config_path.exists():
            config.project = ProjectConfig.from_json(str(proj_config_path))

        # 加载.env文件（如果存在）
        env_file = Path(workspace_dir) / ".env"
        if env_file.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(env_file)
                config.llm = LLMConfig.from_env()
            except ImportError:
                logger.warning("python-dotenv未安装，跳过.env文件加载")

        return config

    def get_rules_path(self) -> Path:
        """获取规则库文件路径"""
        return Path(self.workspace_dir) / self.rules_file

    def get_script_path(self, name: str) -> Path:
        """获取R脚本路径"""
        return Path(self.workspace_dir) / name

    def get_model_path(self, run_id: int) -> Path:
        """获取模型文件路径"""
        return Path(self.workspace_dir) / f"run{run_id}.mod"

    def get_data_path(self) -> Path:
        """获取数据文件路径"""
        return Path(self.workspace_dir) / self.project.data_file
