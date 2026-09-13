$ErrorActionPreference = "Stop"

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $project ".venv\Scripts\pythonw.exe"
$app = Join-Path $project "app.py"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Local Voice Flow is not installed. Run setup.bat first."
}

$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "Local Voice Flow.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $python
$shortcut.Arguments = '"' + $app + '"'
$shortcut.WorkingDirectory = $project
$shortcut.Description = "Local Voice Flow"
$shortcut.Save()

Start-Process -FilePath $python -ArgumentList ('"' + $app + '"') -WorkingDirectory $project
"Local Voice Flow will now start automatically when you sign in."
