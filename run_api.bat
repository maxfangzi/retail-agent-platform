@echo off
rem 一键启动：用本仓库 venv 的 python 起 API 服务（不依赖 conda/activate）
cd /d %~dp0
.venv\Scripts\python.exe -m uvicorn app.api.main:app --reload --port 8000
