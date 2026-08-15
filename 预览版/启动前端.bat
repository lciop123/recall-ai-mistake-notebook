@echo off
rem Recall 错题本 - 一键启动前端（需后端已启动）
cd /d "%~dp0frontend"
call npm run dev
pause
