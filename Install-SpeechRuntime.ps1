param(
    [ValidateSet('Auto','Check','Online','Bundle','Pack')][string]$Mode = 'Auto',
    [string]$BundlePath,
    [string]$OutputPath,
    [switch]$KeepCache
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$candidates = @(
    (Join-Path $root '..\..\..\python_embeded\python.exe'),
    (Join-Path $root '..\..\..\python_embedded\python.exe'),
    (Join-Path $root '.speech-runtime\env\Scripts\python.exe')
)
$python = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $python) {
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) { $python = $command.Source }
}
if (-not $python) {
    Write-Error 'Python was not found. Place this plugin under ComfyUI_windows_portable/ComfyUI/custom_nodes.'
    exit 1
}

$arguments = @((Join-Path $root 'tools\speech_runtime_installer.py'), '--mode', $Mode.ToLowerInvariant())
if ($BundlePath) { $arguments += @('--bundle', $BundlePath) }
if ($OutputPath) { $arguments += @('--output', $OutputPath) }
if ($KeepCache) { $arguments += '--keep-cache' }
& $python @arguments
exit $LASTEXITCODE
