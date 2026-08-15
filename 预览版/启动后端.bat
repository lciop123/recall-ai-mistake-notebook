@echo off
rem Recall 错题本 - 一键启动后端（独立进程，不随命令行窗口关闭而退出）
cd /d "%~dp0backend"
set PYTHONIOENCODING=utf-8
powershell -Command "Start-Process -FilePath 'D:\python3\python.exe' -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory '%~dp0backend' -WindowStyle Hidden -RedirectStandardOutput '%~dp0backend\data\backend.log' -RedirectStandardError '%~dp0backend\data\backend.err.log'"
echo 后端启动中（约 8 秒后可用）...
timeout /t 8 /nobreak >nul
curl -s --max-time 5 http://127.0.0.1:8000/api/health >nul 2>&1 && echo ✅ 后端已就绪: http://127.0.0.1:8000 || echo ⚠️ 启动未完成，请查看 backend\data\backend.err.log
pause
