@echo off
REM Chuyển thư mục vào nơi script
cd /d "D:\Tools\TelemessageAutoforward"

REM Chạy script Python (pythonw chạy ngầm không hiện console)
start "" "C:\Program Files\PyManager\pythonw.exe" "Telethon.py"
