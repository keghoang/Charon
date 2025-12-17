"""Entry point for running galt as a module: python -m galt"""
import sys
import os

# Add the parent directory to sys.path so imports work correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Now run the main module
from galt import main
sys.exit(0)