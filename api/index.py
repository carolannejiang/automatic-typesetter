"""Vercel function entry point: exposes the bookformatter WSGI app.

vercel.json rewrites every path to this function, and the app routes by
the original request path.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bookformatter.serverless import app  # noqa: E402,F401
