"""py2app build configuration.

Build:
    python setup.py py2app
"""
from setuptools import setup

APP = ["netaudit_launcher.py"]
DATA_FILES = [("templates", ["templates/index.html"])]
OPTIONS = {
    "argv_emulation": False,
    "strip": True,
    "plist": {
        "CFBundleName": "NetAudit",
        "CFBundleDisplayName": "NetAudit",
        "CFBundleIdentifier": "dev.sreeb.netaudit",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    },
    "packages": [
        "fastapi",
        "uvicorn",
        "starlette",
        "pydantic",
        "pydantic_core",
        "jinja2",
        "psutil",
        "mac_vendor_lookup",
        "dotenv",
        "anyio",
        "sniffio",
        "click",
        "h11",
        "zeroconf",
        "ifaddr",
    ],
    "includes": [
        "api",
        "config",
        "db",
        "scanner",
        "fingerprint",
        "netaudit_launcher",
        "anyio._backends._asyncio",
        "asyncio",
        "email.mime.text",
    ],
}

setup(
    name="NetAudit",
    version="0.1.0",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
