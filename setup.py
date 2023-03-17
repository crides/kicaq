import setuptools
  
with open("README.md", "r") as fh:
    description = fh.read()
  
setuptools.setup(
    name="kicaq",
    version="0.0.1",
    author="crides",
    author_email="zhuhaoqing@live.cn",
    packages=["kicaq"],
    description="Utilities for interfacing with Kicad PCB from cadquery",
    long_description=description,
    long_description_content_type="text/markdown",
    url="https://github.com/crides/kicaq",
    license='MIT',
    python_requires='>=3.10',
    install_requires=[],
    extras_require={
        "cq": ["cadquery>=2"],
    }
)
