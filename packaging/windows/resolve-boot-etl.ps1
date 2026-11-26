param(
    [Parameter(Mandatory)][string]$Directory,
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9_-]{1,48}$')][string]$RunId
)
$ErrorActionPreference = 'Stop'
$target = Join-Path $Directory 'traffic.etl'
if (Test-Path -LiteralPath $target) { return }
# Both names were observed on the MSI when WPR parsed its stopboot arguments.
# Never substitute an unmerged source logger's .etl file.
$files = @(foreach ($leaf in @("StylusTrace-$RunId", '-force')) {
    $path = Join-Path $Directory $leaf
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $item = Get-Item -LiteralPath $path
        if ($item.Length -gt 0 -and -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { $item }
    }
})
if ($files.Count -gt 1) { throw 'Ambiguous merged trace outputs. Preserve the run directory.' }
if ($files.Count -eq 1) { [IO.File]::Move($files[0].FullName, $target) }
