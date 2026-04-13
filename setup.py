from setuptools import find_packages, setup


setup(
    name="traffic-digital-twin",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages("src"),
    install_requires=[
        "fastapi>=0.110,<1",
        "uvicorn>=0.29,<1",
        "sqlalchemy>=2.0,<3",
        "pydantic>=2.6,<3",
        "networkx>=3.2,<4",
        "streamlit>=1.32,<2",
        "httpx>=0.27,<1",
        "pillow>=10,<12",
    ],
    extras_require={"dev": ["pytest>=8,<9"], "osm": ["osmnx>=2.0,<3"]},
)
