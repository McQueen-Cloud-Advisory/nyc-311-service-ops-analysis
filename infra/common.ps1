# Shared helpers. No authentication or cloud calls happen when this file is loaded.
Set-StrictMode -Version Latest

function Read-Nyc311CloudConfig {
    param([Parameter(Mandatory)][string]$Path, [switch]$ForApply)
    $config = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json
    $required = @('project_id', 'billing_account_id', 'operator_email',
        'location', 'raw_bucket', 'pipeline_account_id', 'dataset_ids',
        'budget_amount_usd', 'enable_storage_data_access_logs')
    $optional = @('reporter_email', 'reporter_account_id', 'organization_id')
    foreach ($name in $required) {
        if ($null -eq $config.PSObject.Properties[$name]) { throw "Missing cloud setting: $name" }
    }
    foreach ($property in $config.PSObject.Properties) {
        if ($property.Name -notin ($required + $optional)) { throw "Unknown cloud setting: $($property.Name)" }
    }
    if ($null -eq $config.PSObject.Properties['reporter_email']) { $config | Add-Member -NotePropertyName reporter_email -NotePropertyValue $null }
    if ($null -eq $config.PSObject.Properties['reporter_account_id']) { $config | Add-Member -NotePropertyName reporter_account_id -NotePropertyValue 'nyc311-reporter' }
    if ($null -eq $config.PSObject.Properties['organization_id']) { $config | Add-Member -NotePropertyName organization_id -NotePropertyValue $null }
    if ($config.organization_id -and [string]$config.organization_id -notmatch '^[0-9]{1,30}$') { throw 'organization_id must be a numeric organization resource ID or null.' }
    if ($null -ne $config.reporter_email -and $config.reporter_email -isnot [string]) { throw 'reporter_email must be a distinct email string, empty string, or null.' }
    if ($config.project_id -notmatch '^[a-z][a-z0-9-]{4,28}[a-z0-9]$') { throw 'Invalid project_id.' }
    if ($config.billing_account_id -notmatch '^[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}$') { throw 'Invalid billing_account_id.' }
    foreach ($name in @('operator_email', 'reporter_email')) {
        if ($name -eq 'reporter_email' -and -not $config.reporter_email) { continue }
        if ($config.$name -notmatch '^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$') {
            throw "$name must be one individual Google account email; wildcards/groups/public principals are unsupported."
        }
    }
    if ($config.reporter_email -and $config.operator_email -eq $config.reporter_email) {
        throw 'Leave reporter_email empty for the one-account setup; an operator/admin cannot demonstrate read-only Desktop access.'
    }
    if ($config.location -notmatch '^[a-z]+-[a-z]+[0-9]$') { throw 'Use one region, for example us-central1, for datasets and storage.' }
    if ($config.raw_bucket -notmatch '^[a-z][a-z0-9-]{1,61}[a-z0-9]$') { throw 'Invalid raw_bucket.' }
    if ($config.pipeline_account_id -notmatch '^[a-z][a-z0-9-]{4,28}[a-z0-9]$') { throw 'Invalid pipeline_account_id.' }
    if ($config.reporter_account_id -notmatch '^[a-z][a-z0-9-]{4,28}[a-z0-9]$') { throw 'Invalid reporter_account_id.' }
    if ($config.reporter_account_id -eq $config.pipeline_account_id) { throw 'Pipeline and reporter service accounts must be distinct.' }
    $datasetNames = @()
    foreach ($name in @('raw', 'work', 'reporting', 'control')) {
        if ($null -eq $config.dataset_ids.PSObject.Properties[$name] -or $config.dataset_ids.$name -notmatch '^[a-z][a-z0-9_]{0,99}$') {
            throw "Missing or invalid dataset_ids.$name."
        }
        $datasetNames += $config.dataset_ids.$name
    }
    if (@($datasetNames | Select-Object -Unique).Count -ne 4) { throw 'Use four distinct datasets.' }
    if ($config.budget_amount_usd -isnot [ValueType] -or $config.budget_amount_usd -is [bool] -or $config.budget_amount_usd -le 0 -or $config.budget_amount_usd -gt 30) {
        throw 'budget_amount_usd must be a number greater than zero and no more than the stated $30 allowance.'
    }
    if ($config.enable_storage_data_access_logs -isnot [bool]) { throw 'enable_storage_data_access_logs must be boolean.' }
    if ($ForApply -and ($config.project_id -like '*change-me*' -or $config.raw_bucket -like '*change-me*' -or
        $config.billing_account_id -eq '000000-000000-000000' -or $config.operator_email -like '*@example.com' -or $config.reporter_email -like '*@example.com')) {
        throw 'Replace all example values in a git-ignored local configuration before applying.'
    }
    return $config
}

function ConvertFrom-Nyc311JsonList {
    param([Parameter(Mandatory)][string]$Json)
    if (-not $Json.TrimStart().StartsWith('[')) { throw 'Expected a JSON array from the list operation.' }
    # Windows PowerShell wraps ConvertFrom-Json's array output when the pipeline
    # itself is inside @(...). Assign first, then let function output enumerate.
    $parsed = $Json | ConvertFrom-Json
    return $parsed
}

function Protect-Nyc311Diagnostic {
    param([AllowEmptyString()][string]$Text)
    $clean = [regex]::Replace($Text, '(?is)-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', '[REDACTED PRIVATE KEY]')
    $clean = [regex]::Replace($clean, '(?im)(authorization\s*[:=]\s*|bearer\s+)[^\r\n]+', '$1[REDACTED]')
    $clean = [regex]::Replace($clean, '(?i)(access_token|refresh_token|id_token|client_secret|private_key)(["\s:=]+)[^\s,}"\r\n]+', '$1$2[REDACTED]')
    $clean = [regex]::Replace($clean, '\bya29\.[A-Za-z0-9._~-]+', '[REDACTED ACCESS TOKEN]')
    $clean = [regex]::Replace($clean, '\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', '[REDACTED JWT]')
    return $clean
}

function Test-Nyc311IamPrincipalPropagation {
    param([Parameter(Mandatory)][string[]]$Arguments, [AllowEmptyString()][string]$Diagnostic)
    if ('add-iam-policy-binding' -notin $Arguments) { return $false }
    # Retry only the exact newly bound service-account principal, never missing
    # projects, invalid roles, denied permissions, or other INVALID_ARGUMENT errors.
    $memberArguments = @($Arguments | Where-Object { $_ -match '^--member=serviceAccount:[a-z0-9-]+@[a-z0-9-]+\.iam\.gserviceaccount\.com$' })
    if ($memberArguments.Count -ne 1) { return $false }
    $principal = $memberArguments[0].Substring('--member=serviceAccount:'.Length)
    $pattern = '(?is)\b(?:INVALID_ARGUMENT|NOT_FOUND)\b.*?\bService account\s+' + [regex]::Escape($principal) + '\s+does not exist\b'
    return $Diagnostic -match $pattern
}

function Invoke-Nyc311Gcloud {
    param([Parameter(Mandatory)][string[]]$Arguments, [switch]$Capture)
    # Array arguments are passed directly, never evaluated as shell source.
    # Keep SDK warnings (including impersonation notices) out of JSON/token stdout.
    # Keep stdout in memory. Auth commands never write either output stream to disk.
    $attempt = 0
    $retryDiagnostics = @()
    do {
        $attempt++
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { $combined = @(& gcloud @Arguments --quiet 2>&1); $exitCode = $LASTEXITCODE }
        finally { $ErrorActionPreference = $previousPreference }
        $result = @($combined | Where-Object { $_ -isnot [Management.Automation.ErrorRecord] })
        $diagnostics = @($combined | Where-Object { $_ -is [Management.Automation.ErrorRecord] } | ForEach-Object { $_.ToString() })
        $retry = $exitCode -ne 0 -and $attempt -lt 6 -and (Test-Nyc311IamPrincipalPropagation -Arguments $Arguments -Diagnostic ($diagnostics -join "`n"))
        if ($retry) {
            $retryDiagnostics += "Attempt $attempt; newly created service-account principal not propagated yet." + "`n" + ($diagnostics -join "`n")
            # Six total attempts, with 1+2+4+8+16 = 31 seconds of bounded delay.
            Start-Sleep -Seconds ([int][math]::Pow(2, $attempt - 1))
        }
    } while ($retry)
    $diagnostics = @($retryDiagnostics) + @($diagnostics)
    $diagnosticPath = $null
    if ($Arguments[0] -ne 'auth' -and $diagnostics.Count -gt 0) {
        $diagnosticRoot = Join-Path (Split-Path $PSScriptRoot -Parent) '.local/gcloud-diagnostics'
        $null = New-Item -ItemType Directory -Path $diagnosticRoot -Force
        $diagnosticPath = Join-Path $diagnosticRoot ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff') + '-' + [guid]::NewGuid().ToString('N') + '.log')
        [IO.File]::WriteAllText($diagnosticPath, (Protect-Nyc311Diagnostic -Text ($diagnostics -join "`n")), [Text.UTF8Encoding]::new($false))
    }
    if ($exitCode -ne 0) {
        # In particular, do not include auth print-access-token output or HTTP headers in errors.
        $detail = $(if ($diagnosticPath) { "Sanitized stderr: $diagnosticPath" } elseif ($Arguments[0] -eq 'auth') { 'Auth output was not logged; check interactive authentication.' } else { 'The command returned no stderr; inspect the account/project without HTTP logging.' })
        throw "gcloud $($Arguments[0]) $($Arguments[1]) failed (exit $exitCode; attempts $attempt). $detail"
    }
    if ($Capture) { return ($result -join "`n") }
}

function Invoke-Nyc311Api {
    param(
        [Parameter(Mandatory)][ValidateSet('GET','POST','PATCH','PUT')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token,
        [object]$Body,
        [switch]$AllowNotFound,
        [string]$ETag,
        [ValidatePattern('^[a-z][a-z0-9-]{4,28}[a-z0-9]$')][string]$QuotaProject
    )
    $parsed = [uri]$Uri
    if ($parsed.Scheme -ne 'https' -or $parsed.Host -notin @('bigquery.googleapis.com', 'storage.googleapis.com', 'cloudresourcemanager.googleapis.com', 'billingbudgets.googleapis.com')) {
        throw 'Refusing credentials to an unexpected API host.'
    }
    $headers = @{ Authorization = "Bearer $Token" }
    if ($QuotaProject) { $headers['x-goog-user-project'] = $QuotaProject }
    if ($ETag) { $headers['If-Match'] = $ETag }
    $request = @{ Method = $Method; Uri = $Uri; Headers = $headers; ErrorAction = 'Stop'; MaximumRedirection = 0 }
    if ($null -ne $Body) { $request.Body = ($Body | ConvertTo-Json -Depth 30 -Compress); $request.ContentType = 'application/json; charset=utf-8' }
    try { return Invoke-RestMethod @request }
    catch {
        $status = $null
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        if ($AllowNotFound -and $status -eq 404) { return $null }
        throw "GCP $Method $($parsed.AbsolutePath) failed (HTTP $status). No credentials or response body were logged."
    }
}

function Get-Nyc311BucketCreateBody {
    param([Parameter(Mandatory)]$Config)
    return @{
        name = $Config.raw_bucket
        location = $Config.location
        storageClass = 'STANDARD'
        labels = @{ managed_by = 'nyc311'; purpose = 'portfolio' }
        iamConfiguration = @{
            uniformBucketLevelAccess = @{ enabled = $true }
            publicAccessPrevention = 'enforced'
        }
        softDeletePolicy = @{ retentionDurationSeconds = 604800 }
    }
}

function Test-Nyc311BigQueryAccessDenied {
    param([Parameter(Mandatory)]$Failure)
    # Windows PowerShell 5 often leaves ErrorDetails empty. Read its response
    # stream in memory, and retain only the structured reason, never the body.
    $errorText = ''
    if ($null -ne $Failure.PSObject.Properties['ErrorDetails'] -and $Failure.ErrorDetails -and $Failure.ErrorDetails.Message) {
        $errorText = $Failure.ErrorDetails.Message
    }
    if (-not $errorText -and $null -ne $Failure.Exception.PSObject.Properties['Response'] -and $Failure.Exception.Response) {
        $reader = $null
        try {
            $reader = [IO.StreamReader]::new($Failure.Exception.Response.GetResponseStream())
            $buffer = [char[]]::new(65537)
            $length = $reader.ReadBlock($buffer, 0, $buffer.Length)
            if ($length -le 65536) { $errorText = [string]::new($buffer, 0, $length) }
        } catch { return $false }
        finally { if ($reader) { $reader.Dispose() } }
    }
    if (-not $errorText) { return $false }
    try {
        $errorBody = $errorText | ConvertFrom-Json
        return @($errorBody.error.errors | Where-Object { $_.reason -eq 'accessDenied' }).Count -gt 0
    } catch { return $false }
    finally { $errorText = $null }
}

function Get-Nyc311AccessEntries {
    param([Parameter(Mandatory)]$Config, [Parameter(Mandatory)][string]$Kind)
    $pipelineEmail = "$($Config.pipeline_account_id)@$($Config.project_id).iam.gserviceaccount.com"
    $reporterServiceEmail = "$($Config.reporter_account_id)@$($Config.project_id).iam.gserviceaccount.com"
    $entries = @(
        @{ role = 'OWNER'; userByEmail = $Config.operator_email },
        @{ role = 'WRITER'; userByEmail = $pipelineEmail }
    )
    if ($Kind -eq 'reporting') {
        $entries += @{ role = 'READER'; userByEmail = $reporterServiceEmail }
        if ($Config.reporter_email) { $entries += @{ role = 'READER'; userByEmail = $Config.reporter_email } }
    }
    return $entries
}
