"""Thin MCP wrappers around ``GazzettaService``. Only this package and server.py know FastMCP."""

from .gazzetta import register

__all__ = ["register"]
