#!/usr/bin/env python3
"""WordFree — точка входа при запуске из исходников: python3 main.py [файл]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wordfree.app import main  # noqa: E402

if __name__ == "__main__":
    main()
