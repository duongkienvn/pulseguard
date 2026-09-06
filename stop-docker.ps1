# StatusMonitor Docker Shutdown Script
# This script stops all StatusMonitor services
#
# Usage:
#   .\stop-docker.ps1          # Stop services (keep data)
#   .\stop-docker.ps1 -Clean   # Stop and remove volumes/images

param(
    [switch]$Clean
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  StatusMonitor - Docker Shutdown" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Stopping services..." -ForegroundColor Yellow

# Use both compose files to ensure all services are stopped regardless of how they were started
docker-compose -f docker-compose.yml -f docker-compose.prod.yml down

if ($Clean) {
    Write-Host ""
    Write-Host "Cleaning up volumes and images..." -ForegroundColor Yellow
    docker-compose -f docker-compose.yml -f docker-compose.prod.yml down -v --rmi all
    Write-Host "✓ Cleanup completed (volumes and images removed)" -ForegroundColor Green
}
else {
    Write-Host "✓ Services stopped (data preserved)" -ForegroundColor Green
    Write-Host ""
    Write-Host "To also remove volumes and images, run: .\stop-docker.ps1 -Clean" -ForegroundColor Yellow
}

Write-Host ""
