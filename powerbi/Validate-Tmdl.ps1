[CmdletBinding()]
param(
    [string]$AmoLibrary = (Join-Path $PSScriptRoot '.tools\amo-19.120.1\lib\net472'),
    [string]$Output = (Join-Path $PSScriptRoot 'validation\tmdl_validation.json')
)
$ErrorActionPreference = 'Stop'
$library = (Resolve-Path -LiteralPath $AmoLibrary).Path
foreach ($dll in @('Microsoft.AnalysisServices.Core.dll', 'Microsoft.AnalysisServices.Tabular.dll')) {
    [System.Reflection.Assembly]::LoadFrom((Join-Path $library $dll)) | Out-Null
}
$modelFolder = Join-Path $PSScriptRoot 'NYC311.SemanticModel\definition'
$model = [Microsoft.AnalysisServices.Tabular.TmdlSerializer]::DeserializeDatabaseFromFolder($modelFolder)
$result = [ordered]@{
    checked_at_utc = [DateTime]::UtcNow.ToString('o')
    outcome = 'passed'
    check = 'Microsoft TmdlSerializer.DeserializeDatabaseFromFolder'
    parser = 'Microsoft.AnalysisServices 19.120.1 (net472)'
    table_count = $model.Model.Tables.Count
    relationship_count = $model.Model.Relationships.Count
    measure_count = ($model.Model.Tables | ForEach-Object { $_.Measures.Count } | Measure-Object -Sum).Sum
    tables = @($model.Model.Tables | ForEach-Object { $_.Name })
    desktop_open = 'unverified'
    refresh = 'unverified'
    dax_execution = 'unverified'
    note = 'Metadata deserialization does not execute M, validate DAX results, or render the report.'
}
$outputPath = [System.IO.Path]::GetFullPath($Output)
New-Item -ItemType Directory -Path ([System.IO.Path]::GetDirectoryName($outputPath)) -Force | Out-Null
[System.IO.File]::WriteAllText($outputPath, ($result | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding($false)))
Write-Output "PASS: $($result.table_count) TMDL tables; $($result.relationship_count) relationships; $($result.measure_count) measures."
