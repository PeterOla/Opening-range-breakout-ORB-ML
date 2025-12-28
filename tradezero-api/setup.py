from setuptools import setup, find_packages

setup(
    name="tradezero-api",
    version="0.1.0",
    description="A Python wrapper for the TradeZero Web Platform using Selenium",
    author="PeterOla",
    packages=find_packages(),
    install_requires=[
        "selenium>=4.0.0",
        "webdriver-manager>=3.8.0",
        "pandas>=1.0.0",
        "termcolor>=1.1.0",
    ],
    python_requires=">=3.8",
)
