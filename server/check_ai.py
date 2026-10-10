r"""Teste rápido da conexão com a IA (principal e barato). No PC: .\.venv\Scripts\python.exe check_ai.py
No servidor: ssh root@148.230.123.44 "docker exec fidus_server python -m app.checkai"
"""
import runpy

runpy.run_module("app.checkai", run_name="__main__")
