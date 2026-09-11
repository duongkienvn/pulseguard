# Build script for PulseGuard Agent GUI
# Run this script to create a standalone executable

# Activate virtual environment if exists
if (Test-Path ".\venv\Scripts\Activate.ps1") {
    & .\venv\Scripts\Activate.ps1
}

# Install requirements
Write-Host "Installing requirements..." -ForegroundColor Cyan
pip install -r agent_service/requirements-gui.txt

# Build executable
Write-Host "Building executable..." -ForegroundColor Cyan

$pyinstallerArgs = @(
    "--onefile",
    "--windowed",
    "--name", "PulseGuardAgent",
    "agent_service/gui_agent.py"
)

# Add icon if it exists
if (Test-Path "agent_service/icon.ico") {
    $pyinstallerArgs += "--icon"
    $pyinstallerArgs += "agent_service/icon.ico"
}

pyinstaller @pyinstallerArgs

Write-Host ""
Write-Host "Build complete!" -ForegroundColor Green
Write-Host "Executable is located at: dist/PulseGuardAgent.exe" -ForegroundColor Yellow
