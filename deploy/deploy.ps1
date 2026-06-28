#!/usr/bin/env pwsh
# Deploy EnergiBalanse (shedder service) from this machine to the server.
#
# Pushes the chosen branch to origin, then SSHes into the server to pull the
# latest code and (re)build the Docker stack. Compose only recreates the service
# if its image or config actually changed.
#
# Usage:
#   ./deploy/deploy.ps1 -Server you@your-server
#   ./deploy/deploy.ps1 -Server you@your-server -Path /opt/energibalanse -Branch main
#   ./deploy/deploy.ps1 -Server you@your-server -Port 22375   # non-standard SSH port
#
# One-time prerequisites (see CONTAINERIZE-AND-DEPLOY-HANDOFF.md §3):
#   - key-based SSH access to the server
#   - the repo cloned to <Path> on the server
#   - deploy/docker.env created and filled in ON THE SERVER (it is gitignored,
#     so `git reset --hard` below never touches it)
#   - the Tesla token cache seeded into the state volume (see docker-compose.yml)

param(
    [Parameter(Mandatory = $true)] [string]$Server,
    [string]$Path = "/opt/energibalanse",
    [string]$Branch = "main",
    [int]$Port = 22
)

$ErrorActionPreference = "Stop"

Write-Host "==> Pushing '$Branch' to origin..." -ForegroundColor Cyan
git push origin $Branch

# Remote script: sync the checkout to origin/<branch>, then rebuild + restart.
$remote = @"
set -e
cd '$Path'
git fetch --all --prune
git checkout '$Branch'
git reset --hard 'origin/$Branch'
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps
"@

# This file is CRLF on Windows; remote bash treats a trailing '\r' as part of
# each command ('set -e\r' -> "invalid option", blank lines -> $'\r'). Send LF.
$remote = $remote -replace "`r`n", "`n"

Write-Host "==> Deploying on $Server (port $Port, $Path)..." -ForegroundColor Cyan
ssh -p $Port $Server $remote
if ($LASTEXITCODE -ne 0) {
    throw "Remote deploy failed (ssh exit code $LASTEXITCODE)."
}

Write-Host "==> Done. Tail logs with:" -ForegroundColor Green
Write-Host "    ssh -p $Port $Server 'cd $Path && docker compose -f deploy/docker-compose.yml logs -f'"
