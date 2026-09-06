# Start Auth Service
Start-Process -FilePath "venv\Scripts\uvicorn" -ArgumentList "auth_service.main:app --reload --port 8000" -NoNewWindow
Write-Host "Started Auth Service on port 8000"

# Start Ingestion Service
Start-Process -FilePath "venv\Scripts\uvicorn" -ArgumentList "ingestion_service.main:app --reload --port 8001" -NoNewWindow
Write-Host "Started Ingestion Service on port 8001"

# Start Distribution Service
Start-Process -FilePath "venv\Scripts\uvicorn" -ArgumentList "distribution_service.main:app --reload --port 8002" -NoNewWindow
Write-Host "Started Distribution Service on port 8002"

# Start Agent
Start-Process -FilePath "venv\Scripts\python" -ArgumentList "-m agent_service.main" -NoNewWindow
Write-Host "Started Agent Service"

# Start Frontend
Set-Location frontend
Start-Process -FilePath "npm" -ArgumentList "run dev" -NoNewWindow
Write-Host "Started Frontend"
Set-Location ..
