"""PythonAnywhere WSGI template for this project.

Copy the contents of this file into your PythonAnywhere WSGI config file and
replace ``YOUR_USERNAME`` if needed.
"""
import os
import sys
from pathlib import Path

PROJECT_HOME = Path("/home/YOUR_USERNAME/FCE-Trainer")

if str(PROJECT_HOME) not in sys.path:
    sys.path.insert(0, str(PROJECT_HOME))

os.chdir(PROJECT_HOME)

from dotenv import load_dotenv

load_dotenv(PROJECT_HOME / ".env")

from wsgi import application

