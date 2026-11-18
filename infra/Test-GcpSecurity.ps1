<#
.SYNOPSIS
Read-only cloud configuration inspection; optional reporter authorization dry runs.
.DESCRIPTION
No rows are read or changed. Reporter checks use BigQuery dry runs under keyless
reporter service-account impersonation, plus existing physical table names.
They prove the role design, not the permissions of an owner's Desktop OAuth login.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [string]$OutputPath,
    [switch]$TestReporter,
    [ValidatePattern('^[A-Za-z_][A-Za-z0-9_]*$')][string]$ReportingTable,
    [ValidatePattern('^[A-Za-z_][A-Za-z0-9_]*$')][string]$RawTable
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$config = Read-Nyc311CloudConfig -Path $ConfigPath -ForApply
if ($TestReporter -and (-not $ReportingTable -or -not $RawTable)) { throw 'Reporter dry runs require existing ReportingTable and RawTable names.' }
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { throw 'Install/authenticate the Google Cloud CLI first.' }
$defaultImpersonation = (Invoke-Nyc311Gcloud -Arguments @('config','get-value','auth/impersonate_service_account') -Capture).Trim()
if ($defaultImpersonation -and $defaultImpersonation -ne '(unset)') { throw 'Remove the gcloud global impersonation setting before this check; the reporter probe sets impersonation explicitly.' }
$project = $config.project_id
$pipelineEmail = "$($config.pipeline_account_id)@$project.iam.gserviceaccount.com"
$reporterServiceEmail = "$($config.reporter_account_id)@$project.iam.gserviceaccount.com"
$checks = [System.Collections.Generic.List[object]]::new()
function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    $checks.Add([pscustomobject]@{ check = $Name; outcome = $(if ($Passed) {'pass'} else {'fail'}); detail = $Detail })
}
function Get-RoleName {
    param([string]$Role)
    switch ($Role) {
        'roles/bigquery.dataViewer' { return 'READER' }
        'roles/bigquery.dataEditor' { return 'WRITER' }
        'roles/bigquery.dataOwner' { return 'OWNER' }
        default { return $Role }
    }
}
$token = (Invoke-Nyc311Gcloud -Arguments @('auth','print-access-token',"--account=$($config.operator_email)") -Capture).Trim()
try {
    $policy = Invoke-Nyc311Api -Method POST -Uri "https://cloudresourcemanager.googleapis.com/v1/projects/${project}:getIamPolicy" -Token $token -Body @{ options = @{ requestedPolicyVersion = 3 } }
    $publicBindings = @($policy.bindings | Where-Object { @($_.members | Where-Object { $_ -in @('allUsers','allAuthenticatedUsers') }).Count -gt 0 })
    Add-Check 'project_no_public_binding' ($publicBindings.Count -eq 0) 'Inspects this project policy; inherited organization/folder and group membership require separate review.'
    $expectedProjectRoles = @{
        "serviceAccount:$pipelineEmail" = @('roles/bigquery.jobUser','roles/serviceusage.serviceUsageConsumer')
        "serviceAccount:$reporterServiceEmail" = @('roles/bigquery.jobUser','roles/serviceusage.serviceUsageConsumer')
    }
    if ($config.reporter_email) { $expectedProjectRoles["user:$($config.reporter_email)"] = @('roles/bigquery.jobUser','roles/serviceusage.serviceUsageConsumer') }
    foreach ($member in $expectedProjectRoles.Keys) {
        $memberBindings = @($policy.bindings | Where-Object { $member -in $_.members })
        $actual = @($memberBindings | ForEach-Object { $_.role } | Sort-Object -Unique)
        $unexpected = @($actual | Where-Object { $_ -notin $expectedProjectRoles[$member] })
        $missing = @($expectedProjectRoles[$member] | Where-Object { $_ -notin $actual })
        $conditional = @($memberBindings | Where-Object { $null -ne $_.PSObject.Properties['condition'] })
        $name = $(if ($member -eq "serviceAccount:$pipelineEmail") { 'pipeline' } elseif ($member -eq "serviceAccount:$reporterServiceEmail") { 'reporter_service_account' } else { 'desktop_reporter' })
        Add-Check "${name}_project_roles" ($unexpected.Count -eq 0 -and $missing.Count -eq 0 -and $conditional.Count -eq 0) "Unexpected=$($unexpected -join ','); missing=$($missing -join ','); conditional=$($conditional.Count)."
    }
    foreach ($kind in @('raw','work','reporting','control')) {
        $datasetId = $config.dataset_ids.$kind
        $dataset = Invoke-Nyc311Api -Method GET -Uri "https://bigquery.googleapis.com/bigquery/v2/projects/$project/datasets/$datasetId" -Token $token
        Add-Check "${kind}_region" ($dataset.location -eq $config.location) 'Dataset and raw storage must use the configured region.'
        $expected = @(Get-Nyc311AccessEntries -Config $config -Kind $kind | ForEach-Object { "$($_.role):$($_.userByEmail)" } | Sort-Object)
        $actual = @($dataset.access | ForEach-Object {
            if ($null -ne $_.PSObject.Properties['userByEmail']) { "$(Get-RoleName $_.role):$($_.userByEmail)" }
            else { 'unexpected-access-entry' }
        } | Sort-Object)
        Add-Check "${kind}_explicit_dataset_access" (($expected -join '|') -eq ($actual -join '|')) 'Exact individual grants only; no special project groups, public domains, views, or group grants in this demo.'
    }
    $bucket = Invoke-Nyc311Api -Method GET -Uri "https://storage.googleapis.com/storage/v1/b/$($config.raw_bucket)" -Token $token
    Add-Check 'bucket_uniform_access' ([bool]$bucket.iamConfiguration.uniformBucketLevelAccess.enabled) 'Object ACLs disabled.'
    Add-Check 'bucket_public_access_prevention' ($bucket.iamConfiguration.publicAccessPrevention -eq 'enforced') 'Public access prevention enforced on this bucket.'
    Add-Check 'bucket_region' ($bucket.location.ToLowerInvariant() -eq $config.location) 'Same region as BigQuery.'
    $bucketPolicy = Invoke-Nyc311Api -Method GET -Uri "https://storage.googleapis.com/storage/v1/b/$($config.raw_bucket)/iam" -Token $token
    $publicBucket = @($bucketPolicy.bindings | Where-Object { @($_.members | Where-Object { $_ -in @('allUsers','allAuthenticatedUsers') }).Count -gt 0 })
    Add-Check 'bucket_no_public_binding' ($publicBucket.Count -eq 0) 'No public IAM member in the bucket policy.'
    $pipelineBucketRoles = @($bucketPolicy.bindings | Where-Object { "serviceAccount:$pipelineEmail" -in $_.members } | ForEach-Object { $_.role } | Sort-Object -Unique)
    Add-Check 'pipeline_capture_append_only' (($pipelineBucketRoles -join '|') -eq 'roles/storage.objectCreator|roles/storage.objectViewer') 'Pipeline may create and read captured objects; it has no bucket-scoped delete/overwrite role.'
    $reporterBucketRoles = @($bucketPolicy.bindings | Where-Object { "serviceAccount:$reporterServiceEmail" -in $_.members -or ($config.reporter_email -and "user:$($config.reporter_email)" -in $_.members) })
    Add-Check 'reporter_no_raw_bucket_grant' ($reporterBucketRoles.Count -eq 0) 'Reporter service account and optional human reporter receive no raw capture grant.'
    foreach ($identity in @(@{ name = 'pipeline'; email = $pipelineEmail }, @{ name = 'reporter'; email = $reporterServiceEmail })) {
        $keys = @(ConvertFrom-Nyc311JsonList -Json (Invoke-Nyc311Gcloud -Arguments @('iam','service-accounts','keys','list',"--iam-account=$($identity.email)", "--project=$project", "--account=$($config.operator_email)",'--managed-by=user','--format=json') -Capture))
        Add-Check "$($identity.name)_no_user_managed_keys" ($keys.Count -eq 0) 'Keyless impersonation is expected; Google-managed signing keys are not credential files.'
        $saPolicy = Invoke-Nyc311Gcloud -Arguments @('iam','service-accounts','get-iam-policy',$identity.email,"--project=$project", "--account=$($config.operator_email)",'--format=json') -Capture | ConvertFrom-Json
        $tokenCreators = @($saPolicy.bindings | Where-Object { $_.role -eq 'roles/iam.serviceAccountTokenCreator' })
        $tokenMembers = @($tokenCreators | ForEach-Object { $_.members })
        Add-Check "$($identity.name)_impersonation_scoped" ($tokenMembers.Count -eq 1 -and $tokenMembers[0] -eq "user:$($config.operator_email)") 'Only the configured operator has an explicit token-creator binding on this service account.'
    }
    $auditEntries = @()
    if ($null -ne $policy.PSObject.Properties['auditConfigs']) {
        $auditEntries = @($policy.auditConfigs | Where-Object { $_.service -in @('storage.googleapis.com','allServices') } | ForEach-Object { $_.auditLogConfigs })
    }
    if ($config.enable_storage_data_access_logs) {
        foreach ($type in @('DATA_READ','DATA_WRITE')) {
            $complete = @($auditEntries | Where-Object { $_.logType -eq $type -and ($null -eq $_.PSObject.Properties['exemptedMembers'] -or @($_.exemptedMembers).Count -eq 0) })
            Add-Check "storage_audit_$type" ($complete.Count -gt 0) 'Non-exempt project data access audit configuration is present.'
        }
    }
    $checks.Add([pscustomobject]@{ check = 'reporter_service_account_authorization'; outcome = 'unverified'; detail = 'Run -TestReporter with existing physical reporting/raw tables. It impersonates the read-only reporter service account; policy inspection alone does not prove effective access.' })
    $checks.Add([pscustomobject]@{ check = 'desktop_oauth_least_privilege'; outcome = 'unverified'; detail = $(if ($config.reporter_email) { 'Optional human reporter has scoped grants; verify the actual Power BI OAuth account and its effective access separately.' } else { 'One-account setup uses operator OAuth in Desktop. An owner retains broad access; service-account probes prove role design only, not owner-account least privilege.' }) })
    if ($TestReporter) {
        $reporterToken = (Invoke-Nyc311Gcloud -Arguments @('auth','print-access-token',"--account=$($config.operator_email)","--impersonate-service-account=$reporterServiceEmail") -Capture).Trim()
        try {
            $quote = [char]96
            $reportRef = "$quote$project.$($config.dataset_ids.reporting).$ReportingTable$quote"
            $rawRef = "$quote$project.$($config.dataset_ids.raw).$RawTable$quote"
            $probes = @(
                @{ name = 'reporter_reporting_select'; sql = "SELECT COUNT(*) FROM $reportRef"; expected = 200 },
                @{ name = 'reporter_raw_select_denied'; sql = "SELECT COUNT(*) FROM $rawRef"; expected = 403 },
                @{ name = 'reporter_reporting_write_denied'; sql = "DELETE FROM $reportRef WHERE FALSE"; expected = 403 }
            )
            foreach ($probe in $probes) {
                $body = @{ jobReference = @{ projectId = $project; location = $config.location }; configuration = @{ dryRun = $true; query = @{ query = $probe.sql; useLegacySql = $false; maximumBytesBilled = '1000000000' } } }
                $status = 200
                $accessDenied = $false
                try {
                    $job = Invoke-RestMethod -Method POST -Uri "https://bigquery.googleapis.com/bigquery/v2/projects/$project/jobs" -Headers @{ Authorization = "Bearer $reporterToken" } -ContentType 'application/json' -Body ($body | ConvertTo-Json -Depth 10) -MaximumRedirection 0 -ErrorAction Stop
                    if ($null -ne $job.PSObject.Properties['status'] -and $null -ne $job.status.PSObject.Properties['errorResult']) {
                        $accessDenied = $job.status.errorResult.reason -eq 'accessDenied'
                        $status = $(if ($accessDenied) { 403 } else { 400 })
                    }
                } catch {
                    $status = 0
                    if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
                    # A quota or policy failure may also use HTTP 403. Count only
                    # BigQuery's accessDenied reason as the expected permission denial.
                    $accessDenied = Test-Nyc311BigQueryAccessDenied -Failure $_
                }
                $passed = $status -eq $probe.expected -and ($probe.expected -ne 403 -or $accessDenied)
                Add-Check $probe.name $passed "Dry run only; expected HTTP $($probe.expected), observed HTTP $status; accessDenied=$accessDenied."
            }
            $pendingCheck = $checks | Where-Object { $_.check -eq 'reporter_service_account_authorization' }
            $null = $checks.Remove($pendingCheck)
        } finally { $reporterToken = $null }
    }
} finally { $token = $null }
$result = [ordered]@{
    checked_at_utc = [DateTime]::UtcNow.ToString('o')
    scope = 'Project-local policy inspection and optional reporter-service-account dry runs; no claim about owner Desktop OAuth least privilege or uninspected inherited/group access.'
    cloud_resources_modified = $false
    checks = @($checks.ToArray())
}
$json = $result | ConvertTo-Json -Depth 10
if ($OutputPath) {
    $destination = [IO.Path]::GetFullPath($OutputPath)
    $parentPath = [IO.Path]::GetDirectoryName($destination)
    if (-not (Test-Path -LiteralPath $parentPath)) { throw 'Create the chosen output directory first.' }
    [IO.File]::WriteAllText($destination, $json, [Text.UTF8Encoding]::new($false))
}
$json
if (@($checks | Where-Object { $_.outcome -eq 'fail' }).Count -gt 0) { throw 'One or more cloud security checks failed. Inspect the recorded results.' }
