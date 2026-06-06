"""py2app build configuration.

Build:
    python setup.py py2app
"""
import glob

from setuptools import setup

APP = ["netaudit_launcher.py"]
DATA_FILES = [
    ("templates", ["templates/index.html"]),
    ("menubar", sorted(glob.glob("assets/menubar/menubar_*.png"))),
]
OPTIONS = {
    "argv_emulation": False,
    "strip": True,
    "iconfile": "NetAudit.icns",
    "plist": {
        "CFBundleName": "NetAudit",
        "CFBundleDisplayName": "NetAudit",
        "CFBundleIdentifier": "dev.sreeb.netaudit",
        "CFBundleVersion": "0.9.5",
        "CFBundleShortVersionString": "0.9.5",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSAppTransportSecurity": {
            "NSAllowsLocalNetworking": True,
            "NSExceptionDomains": {
                "127.0.0.1": {"NSExceptionAllowsInsecureHTTPLoads": True},
                "localhost": {"NSExceptionAllowsInsecureHTTPLoads": True},
            },
        },
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
        "rumps",
        "objc",
    ],
    "includes": [
        "api",
        "config",
        "db",
        "scanner",
        "fingerprint",
        "network",
        "settings",
        "netaudit_launcher",
        "anyio._backends._asyncio",
        "asyncio",
        "email.mime.text",
        "Foundation",
        "AppKit",
        "WebKit",
        "PyObjCTools.AppHelper",
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
