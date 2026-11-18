[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExportRoot,
    [ValidatePattern('^[a-z][a-z0-9_]{0,62}$')][string]$ReleaseId = 'dsny_20261118',
    [ValidatePattern('^$|^[a-z][a-z0-9_]{0,62}$')][string]$WorkingCopyName = '',
    [ValidateSet('CSV','BigQuery')][string]$Mode = 'CSV',
    [string]$SourceProject = 'SET_GCP_PROJECT_ID',
    [string]$BillingProject = 'SET_GCP_BILLING_PROJECT_ID',
    [ValidatePattern('^[a-zA-Z0-9_]+$')][string]$Dataset = 'nyc311_reporting'
)
$ErrorActionPreference = 'Stop'
# Generate a git-ignored working copy. Published source stays machine-independent.
$sourceRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$destination = Join-Path $sourceRoot '.local'
if ($WorkingCopyName) { $destination = Join-Path $destination $WorkingCopyName }
$exportDirectory = (Resolve-Path -LiteralPath $ExportRoot).Path
if ($Mode -eq 'CSV') {
    $manifestFile = Join-Path (Join-Path $exportDirectory $ReleaseId) 'release_metadata.csv'
    if (-not (Test-Path -LiteralPath $manifestFile)) { throw "Missing release export: $manifestFile" }
}
New-Item -ItemType Directory -Path $destination -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $sourceRoot 'NYC311.pbip') -Destination $destination -Force
foreach ($folder in @('NYC311.SemanticModel', 'NYC311.Report')) {
    # This command copies source files into the same subfolder on repeat runs.
    $target = Join-Path $destination $folder
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $sourceRoot $folder) -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse -Force
    }
}
$expressionPath = Join-Path $destination 'NYC311.SemanticModel\definition\expressions.tmdl'
$expressions = [System.IO.File]::ReadAllText($expressionPath)
$parameters = @{
    pMode=$Mode; pExportRoot=$exportDirectory.Replace('\','/'); pReleaseId=$ReleaseId;
    pSourceProject=$SourceProject; pBillingProject=$BillingProject; pDataset=$Dataset
}
foreach ($parameter in $parameters.GetEnumerator()) {
    $value = '"' + $parameter.Value.Replace('"','""') + '"'
    $pattern = '(?m)^(expression ' + [regex]::Escape($parameter.Key) + ' = )"(?:[^"]|"")*"( meta .*)$'
    $replacementValue = $value
    $expressions = [regex]::Replace($expressions, $pattern, [System.Text.RegularExpressions.MatchEvaluator]{param($m) $m.Groups[1].Value + $replacementValue + $m.Groups[2].Value})
}
[System.IO.File]::WriteAllText($expressionPath, $expressions, (New-Object System.Text.UTF8Encoding($false)))
Write-Output (Join-Path $destination 'NYC311.pbip')
