[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^localhost:[0-9]{1,5}$')][string]$Server,
    [string]$Database,
    [ValidatePattern('^[a-z][a-z0-9_]{0,62}$')][string]$ReleaseId = 'dsny_20261118',
    [Parameter(Mandatory = $true)][string]$AdomdLibrary,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'validation\desktop'),
    [string]$QueryFile = (Join-Path $PSScriptRoot 'reconciliation.dax')
)
$ErrorActionPreference = 'Stop'
# This tool reads the already-open Desktop model. It never processes, refreshes,
# alters, or deploys that model. All query sections must start with EVALUATE.
[System.Reflection.Assembly]::LoadFrom((Resolve-Path -LiteralPath $AdomdLibrary).Path) | Out-Null
$connection = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection
$connection.ConnectionString = "Data Source=$Server;Application Name=NYC311ReadOnlyEvidence"
$connection.Open()
try {
    if ([string]::IsNullOrWhiteSpace($Database)) {
        $catalogs = $connection.GetSchemaDataSet('DBSCHEMA_CATALOGS', $null).Tables[0]
        if ($catalogs.Rows.Count -ne 1) { throw 'Expected exactly one Desktop catalog; pass -Database explicitly.' }
        $Database = [string]$catalogs.Rows[0].CATALOG_NAME
    }
} finally { $connection.Close() }
# Do not accept a connection-string segment as a database identifier.
if ($Database -match '[;\r\n]') { throw 'Unexpected Desktop catalog name.' }
$connection.ConnectionString = "Data Source=$Server;Initial Catalog=$Database;Application Name=NYC311ReadOnlyEvidence"
$connection.Open()
$results = @()
try {
    $queryText = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $QueryFile).Path)
    $sections = [regex]::Split($queryText, '(?m)(?=^// [A-E]\. )') | Where-Object { $_ -match '(?m)^EVALUATE' }
    if (@($sections).Count -ne 5) { throw 'Expected the five reviewed A-E EVALUATE queries.' }
    foreach ($section in $sections) {
        $match = [regex]::Match($section, '^// ([A-E])\. ([^\r\n]+)')
        if (-not $match.Success) { throw 'Missing query section identifier.' }
        $queryId = $match.Groups[1].Value
        $start = [regex]::Match($section, '(?m)^EVALUATE').Index
        $query = $section.Substring($start).Trim()
        if ($query -match '(?im)^\s*(CREATE|ALTER|DELETE|UPDATE|INSERT|DROP|PROCESS|REFRESH|BEGIN|COMMIT|ROLLBACK)\b') {
            throw 'Only the reviewed read-only DAX queries are allowed.'
        }
        $command = $connection.CreateCommand()
        $command.CommandText = $query
        $command.CommandTimeout = 120
        $reader = $command.ExecuteReader()
        $rows = @()
        try {
            while ($reader.Read()) {
                $row = [ordered]@{}
                for ($column = 0; $column -lt $reader.FieldCount; $column++) {
                    $name = $reader.GetName($column).Trim([char[]]'[]')
                    $row[$name] = if ($reader.IsDBNull($column)) { $null } else { $reader.GetValue($column) }
                }
                $rows += [pscustomobject]$row
            }
        } finally { $reader.Close(); $command.Dispose() }
        if ($queryId -eq 'A' -and ($rows.Count -ne 1 -or $rows[0].release_id -ne $ReleaseId)) {
            throw 'Desktop model is not the expected single published release.'
        }
        $results += [pscustomobject][ordered]@{query_id=$queryId;description=$match.Groups[2].Value;row_count=$rows.Count;rows=$rows;query=$query}
    }
} finally { $connection.Close(); $connection.Dispose() }
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
foreach ($result in $results) {
    [System.IO.File]::WriteAllText((Join-Path $outputPath ($result.query_id + '.dax')), $result.query, $utf8)
    [System.IO.File]::WriteAllText((Join-Path $outputPath ($result.query_id + '.json')), ($result.rows | ConvertTo-Json -Depth 12), $utf8)
    $result.rows | Export-Csv -LiteralPath (Join-Path $outputPath ($result.query_id + '.csv')) -NoTypeInformation -Encoding UTF8
}
$manifest = [ordered]@{
    checked_at_utc=[DateTime]::UtcNow.ToString('o'); outcome='executed';
    engine='Power BI Desktop Analysis Services, read-only ADOMD queries'; release_id=$ReleaseId;
    query_sections=@($results | ForEach-Object { $_.query_id });
    sql_reconciliation='not evaluated by exporter; see separate comparison output'; visual_inspection='not established by this script';
    note='Actual DAX execution outputs; compare separately with the matching BigQuery release outputs.'
}
[System.IO.File]::WriteAllText((Join-Path $outputPath 'manifest.json'), ($manifest | ConvertTo-Json -Depth 8), $utf8)
Write-Output "Executed five read-only DAX checks for $ReleaseId. Results: $outputPath"
