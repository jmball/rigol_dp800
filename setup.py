import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="rigol_dp800",
    use_scm_version=True,
    setup_requires=["setuptools_scm"],
    author="James Ball",
    author_email="",
    description="Rigol DP800 series control library",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/jmball/rigol_dp800",
    py_modules=["dp800", "virtual_dp800"],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GPL-3.0",
        "Operating System :: OS Independent",
    ],
)
