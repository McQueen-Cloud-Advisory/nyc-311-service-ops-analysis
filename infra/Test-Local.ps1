# Offline checks for the provisioning guardrails. No cloud credentials or SDK needed.
$ErrorActionPreference = 'Stop'
$files = @('common.ps1','Initialize-Gcp.ps1','Test-GcpSecurity.ps1','Test-Local.ps1')
foreach ($name in $files) {
    $parseErrors = $null
    $parseTokens = $null
    $null = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $name), [ref]$parseTokens, [ref]$parseErrors)
    if ($parseErrors.Count -gt 0) { throw "$name parse failed: $($parseErrors -join ', ')" }
}
. (Join-Path $PSScriptRoot 'common.ps1')
# Shadow HTTP only inside this child scope: these checks cannot reach the network.
& {
    function Invoke-RestMethod {
        param($Method, $Uri, $Headers, $ErrorAction, $MaximumRedirection, $Body, $ContentType)
        return [pscustomobject]@{ quota_project = $Headers['x-goog-user-project']; maximum_redirection = $MaximumRedirection }
    }
    $withQuota = Invoke-Nyc311Api -Method GET -Uri 'https://billingbudgets.googleapis.com/v1/billingAccounts/example/budgets' -Token 'synthetic-test-only' -QuotaProject 'nyc311-test'
    if ($withQuota.quota_project -ne 'nyc311-test' -or $withQuota.maximum_redirection -ne 0) { throw 'Quota-project header/redirect contract failed.' }
    $withoutQuota = Invoke-Nyc311Api -Method GET -Uri 'https://storage.googleapis.com/storage/v1/b/example' -Token 'synthetic-test-only'
    if ($withoutQuota.quota_project) { throw 'Optional quota-project header should be omitted.' }
    $rejected = $false
    try { $null = Invoke-Nyc311Api -Method GET -Uri 'https://billingbudgets.googleapis.com/v1/billingAccounts/example/budgets' -Token 'synthetic-test-only' -QuotaProject "invalid`r`nheader: value" } catch { $rejected = $true }
    if (-not $rejected) { throw 'Unsafe quota project must be rejected before HTTP.' }
}
$emptyList = @(ConvertFrom-Nyc311JsonList -Json '[]')
$deniedBody = '{"error":{"errors":[{"reason":"accessDenied"}]}}'
$detailFailure = [pscustomobject]@{ErrorDetails=[pscustomobject]@{Message=$deniedBody}; Exception=[pscustomobject]@{Response=$null}}
if (-not (Test-Nyc311BigQueryAccessDenied -Failure $detailFailure)) { throw 'Structured permission denial in ErrorDetails was missed.' }
foreach ($body in @('{"error":{"errors":[{"reason":"quotaExceeded"}]}}', 'invalid-json')) {
    $detailFailure.ErrorDetails.Message = $body
    if (Test-Nyc311BigQueryAccessDenied -Failure $detailFailure) { throw 'Non-permission errors must not count as access denied.' }
}
$streamResponse = [pscustomobject]@{Body=$deniedBody}
$streamResponse | Add-Member -MemberType ScriptMethod -Name GetResponseStream -Value { [IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($this.Body)) }
$streamFailure = [pscustomobject]@{ErrorDetails=$null; Exception=[pscustomobject]@{Response=$streamResponse}}
if (-not (Test-Nyc311BigQueryAccessDenied -Failure $streamFailure)) { throw 'Windows PowerShell response-stream permission denial was missed.' }
$oneProject = @(ConvertFrom-Nyc311JsonList -Json '[{"projectId":"nyc311-test","labels":{"managed_by":"nyc311","purpose":"portfolio"}}]')
$twoProjects = @(ConvertFrom-Nyc311JsonList -Json '[{"projectId":"first"},{"projectId":"second"}]')
if ($emptyList.Count -ne 0 -or $oneProject.Count -ne 1 -or $oneProject[0].projectId -ne 'nyc311-test' -or $twoProjects.Count -ne 2) { throw 'JSON list flattening regression failed.' }
$sensitiveDiagnostic = 'Authorization: Bearer synthetic-secret' + "`n" + 'access_token=synthetic-token refresh_token=synthetic-refresh client_secret=synthetic-client'
$cleanDiagnostic = Protect-Nyc311Diagnostic -Text $sensitiveDiagnostic
if ($cleanDiagnostic -match 'synthetic-secret|synthetic-token|synthetic-refresh|synthetic-client') { throw 'Diagnostic redaction regression failed.' }
$testPrincipal = 'nyc311-pipeline@nyc311-test.iam.gserviceaccount.com'
$bindingArguments = @('projects','add-iam-policy-binding','nyc311-test',"--member=serviceAccount:$testPrincipal",'--role=roles/bigquery.jobUser')
$propagationMessage = "INVALID_ARGUMENT: Service account $testPrincipal does not exist."
if (-not (Test-Nyc311IamPrincipalPropagation -Arguments $bindingArguments -Diagnostic $propagationMessage)) { throw 'New-principal propagation must be retryable.' }
foreach ($message in @('PERMISSION_DENIED: User cannot change IAM.', 'INVALID_ARGUMENT: Role does not exist.', 'NOT_FOUND: Project does not exist.', 'INVALID_ARGUMENT: Service account different@nyc311-test.iam.gserviceaccount.com does not exist.')) {
    if (Test-Nyc311IamPrincipalPropagation -Arguments $bindingArguments -Diagnostic $message) { throw 'Unrelated IAM errors must not retry.' }
}
foreach ($command in @(@('auth','print-access-token'), @('iam','service-accounts','create','nyc311-pipeline'))) {
    if (Test-Nyc311IamPrincipalPropagation -Arguments $command -Diagnostic $propagationMessage) { throw 'Non-binding command must not retry.' }
}
$example = Join-Path $PSScriptRoot 'gcp.example.json'
$bucketConfig = Read-Nyc311CloudConfig -Path $example
$bucketBody = Get-Nyc311BucketCreateBody -Config $bucketConfig | ConvertTo-Json -Depth 8 | ConvertFrom-Json
if ($bucketBody.name -ne $bucketConfig.raw_bucket -or $bucketBody.location -ne $bucketConfig.location -or $bucketBody.storageClass -ne 'STANDARD') { throw 'Atomic bucket identity/region contract failed.' }
if ($bucketBody.labels.managed_by -ne 'nyc311' -or $bucketBody.labels.purpose -ne 'portfolio') { throw 'Atomic bucket ownership-label contract failed.' }
if ($bucketBody.iamConfiguration.uniformBucketLevelAccess.enabled -ne $true -or $bucketBody.iamConfiguration.publicAccessPrevention -ne 'enforced') { throw 'Atomic bucket access-control contract failed.' }
if ($bucketBody.softDeletePolicy.retentionDurationSeconds -ne 604800 -or $null -ne $bucketBody.PSObject.Properties['acl'] -or $null -ne $bucketBody.PSObject.Properties['defaultObjectAcl']) { throw 'Atomic bucket recovery/no-ACL contract failed.' }
$plan = & (Join-Path $PSScriptRoot 'Initialize-Gcp.ps1') -ConfigPath $example | ConvertFrom-Json
if ($plan.mode -ne 'offline_review_no_cloud_calls' -or $plan.budget_is_hard_spending_cap) { throw 'Review mode/alert-budget semantics failed.' }
if ($plan.reporter_service_account -ne 'nyc311-reporter@nyc311-demo-change-me.iam.gserviceaccount.com' -or $plan.optional_desktop_reporter) { throw 'One-account service-account reporter plan failed.' }
$rejected = $false
try { $null = Read-Nyc311CloudConfig -Path $example -ForApply } catch { $rejected = $true }
if (-not $rejected) { throw 'Placeholder configuration should never apply.' }
$tempConfig = Join-Path ([IO.Path]::GetTempPath()) ("nyc311-security-test-" + [guid]::NewGuid().ToString('N') + '.json')
try {
    foreach ($case in @('public_principal','same_identity','over_budget','shell_project','duplicate_dataset','unknown_setting','same_service_account','invalid_organization')) {
        $config = Get-Content -LiteralPath $example -Raw | ConvertFrom-Json
        switch ($case) {
            'public_principal' { $config.reporter_email = 'allUsers' }
            'same_identity' { $config.reporter_email = $config.operator_email }
            'over_budget' { $config.budget_amount_usd = 31 }
            'shell_project' { $config.project_id = 'demo; echo unsafe' }
            'duplicate_dataset' { $config.dataset_ids.raw = $config.dataset_ids.reporting }
            'unknown_setting' { $config | Add-Member -NotePropertyName grant_owner -NotePropertyValue $true }
            'same_service_account' { $config.reporter_account_id = $config.pipeline_account_id }
            'invalid_organization' { $config.organization_id = '123; unsafe' }
        }
        [IO.File]::WriteAllText($tempConfig, ($config | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
        $rejected = $false
        try { $null = Read-Nyc311CloudConfig -Path $tempConfig } catch { $rejected = $true }
        if (-not $rejected) { throw "Unsafe case accepted: $case" }
    }
    $config = Get-Content -LiteralPath $example -Raw | ConvertFrom-Json
    $config.PSObject.Properties.Remove('reporter_email')
    $config.PSObject.Properties.Remove('reporter_account_id')
    [IO.File]::WriteAllText($tempConfig, ($config | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    $singleAccountConfig = Read-Nyc311CloudConfig -Path $tempConfig
    if ($singleAccountConfig.reporter_email -or $singleAccountConfig.reporter_account_id -ne 'nyc311-reporter') { throw 'Optional reporter settings did not default safely.' }
    $reportingEntries = @(Get-Nyc311AccessEntries -Config $singleAccountConfig -Kind 'reporting')
    $rawEntries = @(Get-Nyc311AccessEntries -Config $singleAccountConfig -Kind 'raw')
    if ($reportingEntries.Count -ne 3 -or $rawEntries.Count -ne 2) { throw 'One-account dataset grant boundary failed.' }
    $singleAccountConfig.reporter_email = 'reader@example.com'
    $withHuman = @(Get-Nyc311AccessEntries -Config $singleAccountConfig -Kind 'reporting')
    if ($withHuman.Count -ne 4) { throw 'Optional distinct human reporter grant is missing.' }
} finally {
    if (Test-Path -LiteralPath $tempConfig) { Remove-Item -LiteralPath $tempConfig }
}
[pscustomobject]@{ outcome = 'pass'; script_parse_checks = $files.Count; configuration_guardrails = 9; one_account_boundary_checks = 4; json_list_checks = 3; diagnostic_redaction_checks = 1; iam_retry_classification_checks = 7; atomic_bucket_checks = 4; quota_project_checks = 3; permission_error_checks = 4; cloud_calls = 0 } | ConvertTo-Json
