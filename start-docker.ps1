# StatusMonitor Docker Startup Script
# This script builds and starts all StatusMonitor services using Docker Compose
#
# Usage:
#   .\start-docker.ps1           # Development mode (all ports exposed)
#   .\start-docker.ps1 -Prod     # Production mode (minimal ports)
#   .\start-docker.ps1 -NoBuild  # Skip build step

param(
    [switch]$Prod,
    [switch]$NoBuild
)

$mode = if ($Prod) { "Production" } else { "Development" }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  StatusMonitor - Docker Startup" -ForegroundColor Cyan
Write-Host "  Mode: $mode" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Docker is running
try {
    docker info | Out-Null
    Write-Host "✓ Docker is running" -ForegroundColor Green
}
catch {
    Write-Host "✗ Docker is not running. Please start Docker Desktop." -ForegroundColor Red
    exit 1
}

# Check for .env file
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Host ""
        Write-Host "⚠ No .env file found. Creating from .env.example..." -ForegroundColor Yellow
        Copy-Item ".env.example" ".env"
        Write-Host "✓ Created .env file. Please review and update values for production." -ForegroundColor Yellow
    }
}

# Build images (always uses base docker-compose.yml)
if (-not $NoBuild) {
    Write-Host ""
    Write-Host "Building Docker images..." -ForegroundColor Yellow
    docker-compose build

    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ Build failed. Please check the error messages above." -ForegroundColor Red
        exit 1
    }

    Write-Host ""
    Write-Host "✓ Build completed successfully" -ForegroundColor Green
}

# Start services
Write-Host ""
Write-Host "Starting services in $mode mode..." -ForegroundColor Yellow

if ($Prod) {
    # Production: merge base + prod override files
    docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
} else {
    # Development: use base file only (all ports exposed)
    docker-compose up -d
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Failed to start services. Please check the error messages above." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "✓ All services started successfully!" -ForegroundColor Green
Write-Host ""

if ($Prod) {
    Write-Host "Services running (Production):" -ForegroundColor Cyan
    Write-Host "  Frontend:       http://localhost:80" -ForegroundColor White
    Write-Host "  Ingestion:      http://localhost:8001 (for agents)" -ForegroundColor White
    Write-Host ""
    Write-Host "Internal services (not exposed):" -ForegroundColor DarkGray
    Write-Host "  Auth, Distribution, History, PostgreSQL, Redis, InfluxDB" -ForegroundColor DarkGray
} else {
    Write-Host "Services running (Development):" -ForegroundColor Cyan
    Write-Host "  Frontend:       http://localhost:5173" -ForegroundColor White
    Write-Host "  Auth Service:   http://localhost:8000" -ForegroundColor White
    Write-Host "  Ingestion:      http://localhost:8001" -ForegroundColor White
    Write-Host "  Distribution:   http://localhost:8002" -ForegroundColor White
    Write-Host "  History:        http://localhost:8003" -ForegroundColor White
    Write-Host "  PostgreSQL:     localhost:5432" -ForegroundColor White
    Write-Host "  Redis:          localhost:6379" -ForegroundColor White
    Write-Host "  InfluxDB:       http://localhost:8086" -ForegroundColor White
}

Write-Host ""
Write-Host "Commands:" -ForegroundColor Yellow
Write-Host "  View logs:      docker-compose logs -f" -ForegroundColor White
Write-Host "  Stop services:  .\stop-docker.ps1" -ForegroundColor White
Write-Host "  Service status: docker-compose ps" -ForegroundColor White
Write-Host ""
