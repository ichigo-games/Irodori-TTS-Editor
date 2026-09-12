$ErrorActionPreference = 'Stop'
$engineRoot = if ($env:IRODORI_HOME) { $env:IRODORI_HOME } else { 'E:\Irodori-TTS' }
& "$engineRoot\.venv\Scripts\python.exe" -B "$PSScriptRoot\run.py"
