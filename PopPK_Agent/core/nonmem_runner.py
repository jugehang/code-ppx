"""
NONMEM执行引擎

负责:
- 运行NONMEM (.mod文件)
- 运行PsN VPC
- 运行R脚本 (GOF/VPC/个体图/参数表)
- 管理运行目录和输出文件
"""

import os
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)


class NonmemRunner:
    """NONMEM运行引擎"""

    def __init__(self, config):
        self.config = config
        self.workspace = Path(config.workspace_dir)

    def run_nonmem(self, run_id: int, mod_file: Optional[str] = None) -> Tuple[bool, str]:
        """
        运行NONMEM

        Args:
            run_id: 模型编号
            mod_file: .mod文件路径（默认 run{id}.mod）

        Returns:
            (success, output_log)
        """
        mod_path = Path(mod_file) if mod_file else self.workspace / f"run{run_id}.mod"

        if not mod_path.exists():
            logger.error(f"控制流文件不存在: {mod_path}")
            return False, f"文件不存在: {mod_path}"

        logger.info(f"启动 NONMEM Run {run_id}: {mod_path.name}")

        # 准备环境
        env = self.config.nonmem.get_env()

        # 直接调用 nmfe76 (输出 .lst 到同一目录)
        nmfe_path = self.config.nonmem.nonmem_path
        lst_name = f"run{run_id}.lst"

        if os.path.exists(nmfe_path):
            # 直接 nmfe76 模式: nmfe76 run{id}.mod run{id}.lst
            nm_cmd = [
                nmfe_path,
                str(mod_path.name),
                lst_name,
            ]
            logger.info(f"使用 nmfe76 直接模式: {nmfe_path}")
        else:
            # 降级为 PsN execute
            psn_execute = self.config.nonmem.psn_execute
            output_dir = f"run{run_id}_psn"
            if os.path.exists(str(self.workspace / output_dir)):
                shutil.rmtree(str(self.workspace / output_dir))
            nm_cmd = [
                psn_execute,
                str(mod_path.name),
                f"-directory={output_dir}",
                "-clean=1",
            ]
            logger.info(f"降级为 PsN execute 模式: {psn_execute}")

        try:
            result = subprocess.run(
                nm_cmd,
                cwd=str(self.workspace),
                env=env,
                capture_output=True,
                text=True,
                timeout=3600  # 1小时超时
            )

            output = result.stdout + "\n" + result.stderr

            # 检查LST文件是否生成
            lst_path = self.workspace / f"run{run_id}.lst"

            # PsN execute 模式: LST在子目录中，复制到工作区
            if not lst_path.exists() and 'psn_dir' in dir():
                psn_dir = self.workspace / output_dir
                psn_lst = None
                # 搜索 PsN 输出目录中的 .lst 文件
                if psn_dir.exists():
                    for f in psn_dir.glob("*.lst"):
                        psn_lst = f
                        break
                    # 也可能在不同子目录
                    if not psn_lst:
                        for f in psn_dir.rglob("*.lst"):
                            psn_lst = f
                            break

                if psn_lst and psn_lst.exists():
                    shutil.copy2(str(psn_lst), str(lst_path))
                    # 同时复制其他关键输出文件
                    for ext in [".ext", ".cov", ".cor", ".phi"]:
                        src = psn_lst.with_suffix(ext)
                        if src.exists():
                            shutil.copy2(str(src), str(self.workspace / f"run{run_id}{ext}"))
                    # 复制 SDTAB 等表文件
                    for tab_file in psn_dir.rglob("SDTAB*"):
                        shutil.copy2(str(tab_file), str(self.workspace / tab_file.name.upper()))
                    for tab_file in psn_dir.rglob("sdtab*"):
                        shutil.copy2(str(tab_file), str(self.workspace / tab_file.name.upper()))

            if lst_path.exists():
                logger.info(f"NONMEM Run {run_id} 完成, LST文件已生成")
                return True, output
            else:
                logger.error(f"NONMEM Run {run_id} 完成但LST文件未生成")
                return False, output + "\n[LST文件未生成]"

        except subprocess.TimeoutExpired:
            logger.error(f"NONMEM Run {run_id} 超时")
            return False, "NONMEM运行超时 (3600s)"
        except Exception as e:
            logger.error(f"NONMEM运行异常: {e}")
            return False, str(e)

    def run_vpc(self, run_id: int, samples: int = 500, stratify_on: str = "STUDY") -> Tuple[bool, str]:
        """
        运行PsN VPC

        Args:
            run_id: 模型编号
            samples: 仿真样本量
            stratify_on: 分层变量

        Returns:
            (success, output_log)
        """
        mod_file = self.workspace / f"run{run_id}.mod"
        vpc_dir = self.workspace / f"vpc_dir_{run_id}"

        if not mod_file.exists():
            logger.error(f"模型文件不存在: {mod_file}")
            return False, f"文件不存在: {mod_file}"

        # 清理旧目录
        if vpc_dir.exists():
            shutil.rmtree(vpc_dir)

        cmd = [
            self.config.nonmem.psn_path,
            str(mod_file),
            f"-samples={samples}",
            f"-dir={vpc_dir.name}",
            f"-stratify_on={stratify_on}",
            "-idv=TIME",
            "-bin_by_count=1",
            "-no_of_bins=12",
        ]

        logger.info(f"启动 PsN VPC (Run {run_id}, samples={samples})")

        env = self.config.nonmem.get_env()

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.workspace),
                env=env,
                capture_output=True,
                text=True,
                timeout=7200  # 2小时超时
            )

            vpc_results = vpc_dir / "vpc_results.csv"
            if vpc_results.exists():
                logger.info(f"VPC仿真完成: {vpc_results}")
                return True, result.stdout
            else:
                return False, result.stdout + result.stderr + "\n[vpc_results.csv未生成]"

        except subprocess.TimeoutExpired:
            return False, "VPC运行超时"
        except Exception as e:
            return False, str(e)

    def run_r_script(self, script_name: str, *args) -> Tuple[bool, str]:
        """
        运行R脚本

        Args:
            script_name: R脚本文件名
            *args: 传递给R脚本的参数

        Returns:
            (success, output_log)
        """
        script_path = self.workspace / script_name
        if not script_path.exists():
            logger.error(f"R脚本不存在: {script_path}")
            return False, f"文件不存在: {script_path}"

        cmd = [self.config.nonmem.rscript_path, script_name] + list(args)

        logger.info(f"运行R脚本: {script_name} {' '.join(args)}")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=600  # 10分钟超时
            )

            if result.returncode == 0:
                logger.info(f"R脚本执行成功: {script_name}")
                return True, result.stdout
            else:
                logger.error(f"R脚本执行失败: {script_name}")
                return False, result.stdout + "\n" + result.stderr

        except subprocess.TimeoutExpired:
            return False, f"R脚本超时: {script_name}"
        except Exception as e:
            return False, str(e)

    def generate_all_diagnostics(self, run_id: int, run_vpc: bool = True) -> dict:
        """
        生成所有诊断图

        Args:
            run_id: 模型编号
            run_vpc: 是否运行VPC（耗时较长）

        Returns:
            各步骤的结果字典
        """
        results = {
            "vpc": None,
            "gof": None,
            "individual": None,
            "pk_table": None,
        }

        # 1. VPC (可选)
        if run_vpc:
            vpc_ok, vpc_log = self.run_vpc(run_id)
            results["vpc"] = {"success": vpc_ok, "log": vpc_log}
            if not vpc_ok:
                logger.warning("VPC运行失败，跳过VPC绘图")
            else:
                vpc_plot_ok, vpc_plot_log = self.run_r_script("vpc_plot_script.R", str(run_id))
                results["vpc_plot"] = {"success": vpc_plot_ok, "log": vpc_plot_log}

        # 2. GOF图
        gof_ok, gof_log = self.run_r_script("gof_plot_script.R", str(run_id))
        results["gof"] = {"success": gof_ok, "log": gof_log}

        # 3. 个体拟合图
        ind_ok, ind_log = self.run_r_script("individual_plot_script.R", str(run_id))
        results["individual"] = {"success": ind_ok, "log": ind_log}

        # 4. 参数表 (R脚本)
        pk_ok, pk_log = self.run_r_script("pk parameters script.R", str(run_id))
        results["pk_table"] = {"success": pk_ok, "log": pk_log}

        return results

    def get_output_files(self, run_id: int) -> dict:
        """获取运行后的输出文件路径"""
        return {
            "lst": self.workspace / f"run{run_id}.lst",
            "ext": self.workspace / f"run{run_id}.ext",
            "cov": self.workspace / f"run{run_id}.cov",
            "sdtab": self.workspace / f"SDTAB{run_id}",
            "gof_plot": self.workspace / f"GOF_mod{run_id}.jpg",
            "vpc_plot": self.workspace / f"VPC_mod{run_id}.jpg",
            "vpc_stratified": self.workspace / f"VPC_Stratified_mod{run_id}.jpg",
            "individual_plot": self.workspace / f"Individual_Plots_Run{run_id}.pdf",
            "pk_table_docx": self.workspace / f"Table5_Run{run_id}_Final_Parameters.docx",
            "pk_table_csv": self.workspace / f"data_run{run_id}.csv",
        }
