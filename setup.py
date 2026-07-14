"""PopPK Agent setup - 可安装的自动化群体药动学建模工具包"""
from setuptools import setup, find_packages

setup(
    name="poppk-agent",
    version="0.1.0",
    description="基于LLM和规则库的自动化群体药动学建模工具 - 支持任意NONMEM数据集",
    author="Gehang Ju",
    python_requires=">=3.9",
    packages=find_packages(),
    py_modules=["poppk"],
    install_requires=[
        "openai>=1.0.0",
        "pandas>=2.0.0",
        "Pillow>=10.0.0",
        "openpyxl>=3.1.0",
        "tabulate>=0.9.0",
        "python-dotenv>=1.0.0",
    ],
    entry_points={
        "console_scripts": [
            "poppk=poppk:main",
        ],
    },
)
