[CmdletBinding()]
param(
    [switch]$Browser
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required. Install Git, then run this script again."
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install uv, then run this script again."
}

Push-Location $RepositoryRoot
try {
    uv sync
    if ($Browser) {
        uv sync --extra browser
        uv run playwright install chromium
    }
    uv run wechat-reader-mcp doctor
}
finally {
    Pop-Location
}

Write-Host "Installation verified. Choose a client template under clients/."
