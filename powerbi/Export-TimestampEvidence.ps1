[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^localhost:[0-9]{1,5}$')][string]$Server,
    [string]$Database,
    [Parameter(Mandatory = $true)][string]$AdomdLibrary,
    [Parameter(Mandatory = $true)][string]$ReferenceDirectory,
    [Parameter(Mandatory = $true)][ValidateSet('CSV', 'BigQuery')][string]$ImportMode,
    [Parameter(Mandatory = $true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
# Read-only evidence from the already-refreshed model. This does not execute M,
# alter a model, or authenticate to Google. All expected values come from the
# release's saved export; no offset correction is applied to observed values.
$referencePath = (Resolve-Path -LiteralPath $ReferenceDirectory).Path
$metadata = @(Import-Csv -LiteralPath (Join-Path $referencePath 'release_metadata.csv'))
if ($metadata.Count -ne 1) { throw 'Expected one reference metadata row.' }
$releaseId = $metadata[0].release_id
if ($releaseId -notmatch '^[a-z][a-z0-9_]{0,62}$') { throw 'Invalid reference release ID.' }
$cases = @(Import-Csv -LiteralPath (Join-Path $referencePath 'fct_cases.csv') | Sort-Object created_date, request_id)
$sample = @(@($cases | Select-Object -First 5) + @($cases | Select-Object -Last 5) | Sort-Object request_id -Unique)
if ($sample.Count -eq 0) { throw 'Expected nonempty case references.' }
foreach ($row in $sample) {
    if ($row.request_id -notmatch '^[0-9]+$') { throw 'Timestamp evidence sample requires numeric request IDs.' }
}
$ids = ($sample | ForEach-Object { '"' + $_.request_id + '"' }) -join ', '
$queries = [ordered]@{
    release = @'
EVALUATE
SELECTCOLUMNS(
    'Release',
    "release_id", 'Release'[release_id],
    "observed_at", 'Release'[observed_at],
    "extraction_started_at", 'Release'[extraction_started_at],
    "extraction_ended_at", 'Release'[extraction_ended_at]
)
'@
    cases = @"
EVALUATE
CALCULATETABLE(
    SELECTCOLUMNS(
        'Cases', "request_id", 'Cases'[request_id],
        "observed_at", 'Cases'[observed_at],
        "created_at", 'Cases'[created_at], "closed_at", 'Cases'[closed_at]
    ),
    TREATAS({$ids}, 'Cases'[request_id])
)
ORDER BY [request_id]
"@
}
[System.Reflection.Assembly]::LoadFrom((Resolve-Path -LiteralPath $AdomdLibrary).Path) | Out-Null
$connection = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection
$connection.ConnectionString = "Data Source=$Server;Application Name=NYC311ReadOnlyTimestampEvidence"
$connection.Open()
try {
    if ([string]::IsNullOrWhiteSpace($Database)) {
        $catalogs = $connection.GetSchemaDataSet('DBSCHEMA_CATALOGS', $null).Tables[0]
        if ($catalogs.Rows.Count -ne 1) { throw 'Expected exactly one Desktop catalog.' }
        $Database = [string]$catalogs.Rows[0].CATALOG_NAME
    }
} finally { $connection.Close() }
if ($Database -match '[;\r\n]') { throw 'Unexpected Desktop catalog name.' }
$connection.ConnectionString = "Data Source=$Server;Initial Catalog=$Database;Application Name=NYC311ReadOnlyTimestampEvidence"
$connection.Open()
$actual = [ordered]@{}
try {
    foreach ($name in $queries.Keys) {
        $command = $connection.CreateCommand()
        $command.CommandText = $queries[$name]
        $command.CommandTimeout = 120
        $reader = $command.ExecuteReader()
        $rows = @()
        try {
            while ($reader.Read()) {
                $row = [ordered]@{}
                for ($column = 0; $column -lt $reader.FieldCount; $column++) {
                    $field = $reader.GetName($column).Trim([char[]]'[]')
                    $value = if ($reader.IsDBNull($column)) { $null } else { $reader.GetValue($column) }
                    # Semantic model datetime is timezone-free UTC by contract.
                    # Do not call ToUniversalTime on it, which would assume local time.
                    $row[$field] = if ($value -is [DateTime]) { $value.ToString('yyyy-MM-ddTHH:mm:ss') } else { $value }
                }
                $rows += [pscustomobject]$row
            }
        } finally { $reader.Close(); $command.Dispose() }
        $actual[$name] = $rows
    }
} finally { $connection.Close(); $connection.Dispose() }
if ($actual.release.Count -ne 1 -or $actual.release[0].release_id -ne $releaseId) {
    throw 'The open model is not the expected single release.'
}
function Get-UtcSecond([string]$value) {
    if ([string]::IsNullOrWhiteSpace($value)) { return $null }
    return [DateTimeOffset]::Parse($value, [Globalization.CultureInfo]::InvariantCulture).UtcDateTime.ToString('yyyy-MM-ddTHH:mm:ss')
}
$checks = @()
foreach ($field in @('observed_at', 'extraction_started_at', 'extraction_ended_at')) {
    $expected = Get-UtcSecond $metadata[0].$field
    $observed = $actual.release[0].$field
    $checks += [ordered]@{table='Release';key=$releaseId;field=$field;expected_utc=$expected;observed_utc=$observed;passed=($expected -eq $observed)}
}
if ($actual.cases.Count -ne $sample.Count) { throw 'Case sample row counts differ.' }
foreach ($reference in $sample) {
    $matching = @($actual.cases | Where-Object request_id -eq $reference.request_id)
    if ($matching.Count -ne 1) { throw 'Missing or duplicated case timestamp sample.' }
    foreach ($field in @('observed_at', 'created_at', 'closed_at')) {
        $expected = Get-UtcSecond $reference.$field
        $observed = $matching[0].$field
        $checks += [ordered]@{table='Cases';key=$reference.request_id;field=$field;expected_utc=$expected;observed_utc=$observed;passed=($expected -eq $observed)}
    }
}
$result = [ordered]@{
    checked_at_utc=[DateTime]::UtcNow.ToString('o');release_id=$releaseId;import_mode=$ImportMode;
    outcome= $(if (@($checks | Where-Object { -not $_.passed }).Count -eq 0) { 'passed' } else { 'failed' });
    scope='Executed Desktop UTC timestamps compared with matching release CSV exports';
    precision='whole seconds, intentionally excluding subsecond semantic-model rounding';
    sample='first five and last five cases ordered by creation date and request ID';
    checks_compared=$checks.Count;checks=$checks;
    reference_sha256=@{
        release_metadata=(Get-FileHash -LiteralPath (Join-Path $referencePath 'release_metadata.csv') -Algorithm SHA256).Hash.ToLowerInvariant();
        fct_cases=(Get-FileHash -LiteralPath (Join-Path $referencePath 'fct_cases.csv') -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
foreach ($name in $queries.Keys) {
    [System.IO.File]::WriteAllText((Join-Path $outputPath ('timestamps_' + $name + '.dax')), $queries[$name], $utf8)
    [System.IO.File]::WriteAllText((Join-Path $outputPath ('timestamps_' + $name + '.json')), ($actual[$name] | ConvertTo-Json -Depth 10), $utf8)
}
[System.IO.File]::WriteAllText((Join-Path $outputPath 'timestamp_comparison.json'), ($result | ConvertTo-Json -Depth 10), $utf8)
Write-Output "Timestamp comparison $($result.outcome): $($checks.Count) checks. $outputPath"
if ($result.outcome -ne 'passed') { exit 1 }
