@echo off
setlocal
set "PATH=C:\Windows\system32;C:\Windows;C:\Windows\System32\Wbem;C:\Windows\System32\WindowsPowerShell\v1.0;C:\SIMULIA\Commands"

cd /d "C:\Users\vfn333\Documents\GitHub\umat-oti-softwarex-manuscript\evidence\2ae2ee0\abaqus_parity\jobs\modelA_uniax_oti"
set "PARITY_CALLS=C:\Users\vfn333\Documents\GitHub\umat-oti-softwarex-manuscript\evidence\2ae2ee0\abaqus_parity\jobs\modelA_uniax_oti\modelA_uniax_oti_calls.txt"
call abaqus job=modelA_uniax_oti input=modelA_uniax_oti.inp cpus=1 interactive ask_delete=OFF > console.txt 2>&1
exit /b %ERRORLEVEL%
