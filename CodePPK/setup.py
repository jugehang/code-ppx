from setuptools import setup, find_packages

setup(
    name="codeppk",
    version="0.1.0",
    description="LLM-powered automated Population PK modeling platform",
    author="Gehang Ju",
    packages=find_packages(),
    install_requires=[
        "openai>=1.0.0",
        "anthropic>=0.20.0",
        "pandas>=2.0.0",
        "openpyxl>=3.1.0",
        "Pillow>=10.0.0",
        "requests>=2.31.0",
    ],
    entry_points={
        "console_scripts": [
            "codeppk=codeppk.cli:main",
        ],
    },
    python_requires=">=3.9",
)
