<#
.SYNOPSIS
Review or create the dedicated NYC 311 cloud environment. Default mode is offline review.
.EXAMPLE
./infra/Initialize-Gcp.ps1 -ConfigPath ./infra/gcp.example.json
.EXAMPLE
./infra/Initialize-Gcp.ps1 -ConfigPath ./.local/gcp.json -Apply
#>
[CmdletBinding()]
param([string]$ConfigPath = (Join-Path $PSScriptRoot 'gcp.example.json'), [switch]$Apply)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$config = Read-Nyc311CloudConfig -Path $ConfigPath -ForApply:$Apply
$project = $config.project_id
$pipelineEmail = "$($config.pipeline_account_id)@$project.iam.gserviceaccount.com"
$reporterServiceEmail = "$($config.reporter_account_id)@$project.iam.gserviceaccount.com"
$services = @('bigquery.googleapis.com', 'storage.googleapis.com',
    'iam.googleapis.com', 'iamcredentials.googleapis.com', 'cloudresourcemanager.googleapis.com',
    'cloudbilling.googleapis.com', 'billingbudgets.googleapis.com', 'logging.googleapis.com')
$plan = [ordered]@{
    mode = $(if ($Apply) { 'apply' } else { 'offline_review_no_cloud_calls' })
    project = $project; location = $config.location
    organization_id = $config.organization_id
    billing_account = $config.billing_account_id
    monthly_alert_budget_usd = $config.budget_amount_usd
    budget_is_hard_spending_cap = $false
    datasets = $config.dataset_ids
    bucket = "gs://$($config.raw_bucket)"
    bucket_controls = @('uniform bucket-level access', 'public access prevention enforced', '7-day soft delete', 'no object ACLs', 'no automatic deletion')
    pipeline = $pipelineEmail
    pipeline_project_roles = @('roles/bigquery.jobUser', 'roles/serviceusage.serviceUsageConsumer')
    pipeline_dataset_access = 'WRITER on only the four named datasets'
    pipeline_bucket_roles = @('roles/storage.objectCreator', 'roles/storage.objectViewer')
    operator = $config.operator_email
    operator_impersonation = 'roles/iam.serviceAccountTokenCreator on the pipeline and reporter service accounts individually'
    reporter_service_account = $reporterServiceEmail
    optional_desktop_reporter = $config.reporter_email
    reporter_project_roles = @('roles/bigquery.jobUser', 'roles/serviceusage.serviceUsageConsumer')
    reporter_dataset_access = 'READER on reporting only'
    desktop_identity_note = $(if ($config.reporter_email) { 'Use the optional distinct user for Desktop OAuth; validate actual Desktop behavior separately.' } else { 'One-account setup: Desktop OAuth uses the operator. Reporter service-account probes prove the scoped role design, not owner-account least privilege.' })
    cloud_storage_data_access_audit = $config.enable_storage_data_access_logs
    services = $services
    exclusions = @('no service-account keys', 'no runtime Owner/Editor', 'no VM', 'no scheduler', 'no public bucket or dataset', 'no auto teardown')
}
$plan | ConvertTo-Json -Depth 8
if (-not $Apply) { return }
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { throw 'Install the Google Cloud CLI before applying.' }
$activeAccount = (Invoke-Nyc311Gcloud -Arguments @('config','get-value','account') -Capture).Trim()
if ($activeAccount -ne $config.operator_email) { throw 'The active gcloud account must match operator_email. Authenticate interactively before applying.' }
$impersonation = (Invoke-Nyc311Gcloud -Arguments @('config','get-value','auth/impersonate_service_account') -Capture).Trim()
if ($impersonation -and $impersonation -ne '(unset)') { throw 'Run bootstrap as the operator, without a gcloud default impersonation setting.' }

$projects = @(ConvertFrom-Nyc311JsonList -Json (Invoke-Nyc311Gcloud -Arguments @('projects','list',"--filter=projectId=$project",'--format=json') -Capture))
if ($projects.Count -eq 0) {
    $createArguments = @('projects','create',$project,'--name=NYC 311 Service Operations','--labels=managed_by=nyc311,purpose=portfolio')
    if ($config.organization_id) { $createArguments += "--organization=$($config.organization_id)" }
    Invoke-Nyc311Gcloud -Arguments $createArguments
} elseif ($projects.Count -ne 1 -or $null -eq $projects[0].PSObject.Properties['labels'] -or
    $projects[0].labels.managed_by -ne 'nyc311' -or $projects[0].labels.purpose -ne 'portfolio') {
    throw 'Refusing to modify an existing project without this demo ownership label. Choose a new dedicated project ID.'
}
$projectInfo = Invoke-Nyc311Gcloud -Arguments @('projects','describe',$project,'--format=json') -Capture | ConvertFrom-Json
$billingInfo = Invoke-Nyc311Gcloud -Arguments @('billing','projects','describe',$project,'--format=json') -Capture | ConvertFrom-Json
if ($billingInfo.billingAccountName -and $billingInfo.billingAccountName -ne "billingAccounts/$($config.billing_account_id)") {
    throw 'The project is already linked to another billing account; no billing link was changed.'
}
Invoke-Nyc311Gcloud -Arguments @('billing','projects','link',$project,"--billing-account=$($config.billing_account_id)")
Invoke-Nyc311Gcloud -Arguments (@('services','enable') + $services + @("--project=$project"))

$accounts = @(ConvertFrom-Nyc311JsonList -Json (Invoke-Nyc311Gcloud -Arguments @('iam','service-accounts','list',"--project=$project",'--format=json') -Capture))
foreach ($account in @(@{ id = $config.pipeline_account_id; email = $pipelineEmail; label = 'NYC311 bounded pipeline' }, @{ id = $config.reporter_account_id; email = $reporterServiceEmail; label = 'NYC311 read-only reporter' })) {
    if (-not ($accounts | Where-Object { $_.email -eq $account.email })) {
        Invoke-Nyc311Gcloud -Arguments @('iam','service-accounts','create',$account.id,"--project=$project","--display-name=$($account.label)")
    }
    foreach ($role in @('roles/bigquery.jobUser','roles/serviceusage.serviceUsageConsumer')) {
        Invoke-Nyc311Gcloud -Arguments @('projects','add-iam-policy-binding',$project,"--member=serviceAccount:$($account.email)","--role=$role",'--condition=None')
    }
    Invoke-Nyc311Gcloud -Arguments @('iam','service-accounts','add-iam-policy-binding',$account.email,"--project=$project", "--member=user:$($config.operator_email)",'--role=roles/iam.serviceAccountTokenCreator','--condition=None')
}
if ($config.reporter_email) {
    foreach ($role in @('roles/bigquery.jobUser','roles/serviceusage.serviceUsageConsumer')) {
        Invoke-Nyc311Gcloud -Arguments @('projects','add-iam-policy-binding',$project,"--member=user:$($config.reporter_email)","--role=$role",'--condition=None')
    }
}

$token = (Invoke-Nyc311Gcloud -Arguments @('auth','print-access-token') -Capture).Trim()
try {
    foreach ($kind in @('raw','work','reporting','control')) {
        $dataset = $config.dataset_ids.$kind
        $datasetUri = "https://bigquery.googleapis.com/bigquery/v2/projects/$project/datasets/$dataset"
        $existing = Invoke-Nyc311Api -Method GET -Uri $datasetUri -Token $token -AllowNotFound
        if ($null -eq $existing) {
            $body = @{
                datasetReference = @{ projectId = $project; datasetId = $dataset }
                location = $config.location
                description = "NYC311 $kind; public-data demo, private cloud access"
                labels = @{ managed_by = 'nyc311'; purpose = 'portfolio' }
                access = @(Get-Nyc311AccessEntries -Config $config -Kind $kind)
            }
            $null = Invoke-Nyc311Api -Method POST -Uri "https://bigquery.googleapis.com/bigquery/v2/projects/$project/datasets" -Token $token -Body $body
        } else {
            if ($null -eq $existing.PSObject.Properties['labels'] -or $existing.labels.managed_by -ne 'nyc311' -or $existing.location -ne $config.location) {
                throw "Dataset $dataset is not the expected managed dataset/region. No dataset policy was changed."
            }
            # Existing ACLs are not silently replaced. The read-only verifier detects drift.
        }
    }
    $bucketUri = "https://storage.googleapis.com/storage/v1/b/$($config.raw_bucket)"
    $bucket = Invoke-Nyc311Api -Method GET -Uri $bucketUri -Token $token -AllowNotFound
    if ($null -eq $bucket) {
        # Create ownership labels and security controls atomically, so an interrupted
        # apply can safely recognize its bucket on the next run.
        $null = Invoke-Nyc311Api -Method POST -Uri "https://storage.googleapis.com/storage/v1/b?project=$project" -Token $token -Body (Get-Nyc311BucketCreateBody -Config $config)
    } elseif ([string]$bucket.projectNumber -ne [string]$projectInfo.projectNumber -or $bucket.labels.managed_by -ne 'nyc311') {
        throw 'Refusing to change a bucket outside this managed project.'
    }
    foreach ($role in @('roles/storage.objectCreator','roles/storage.objectViewer')) {
        Invoke-Nyc311Gcloud -Arguments @('storage','buckets','add-iam-policy-binding',"gs://$($config.raw_bucket)","--member=serviceAccount:$pipelineEmail","--role=$role")
    }
    if ($config.enable_storage_data_access_logs) {
        $policyUri = "https://cloudresourcemanager.googleapis.com/v1/projects/${project}:getIamPolicy"
        $policy = Invoke-Nyc311Api -Method POST -Uri $policyUri -Token $token -Body @{ options = @{ requestedPolicyVersion = 3 } }
        $auditConfigs = @()
        if ($null -ne $policy.PSObject.Properties['auditConfigs']) { $auditConfigs = @($policy.auditConfigs) }
        $storageAudit = @($auditConfigs | Where-Object { $_.service -eq 'storage.googleapis.com' })
        if ($storageAudit.Count -gt 1) { throw 'Unexpected duplicate Cloud Storage audit configuration; inspect manually.' }
        # Keep existing entries and exemptions; add non-exempt entries for the demo data access types.
        $existingLogs = @()
        if ($storageAudit.Count -eq 1) { $existingLogs = @($storageAudit[0].auditLogConfigs) }
        foreach ($logType in @('DATA_READ','DATA_WRITE')) {
            if (-not ($existingLogs | Where-Object { $_.logType -eq $logType })) { $existingLogs += @{ logType = $logType } }
        }
        $auditConfigs = @($auditConfigs | Where-Object { $_.service -ne 'storage.googleapis.com' }) + @(@{ service = 'storage.googleapis.com'; auditLogConfigs = $existingLogs })
        $policy | Add-Member -NotePropertyName auditConfigs -NotePropertyValue $auditConfigs -Force
        $null = Invoke-Nyc311Api -Method POST -Uri "https://cloudresourcemanager.googleapis.com/v1/projects/${project}:setIamPolicy" -Token $token -Body @{ policy = $policy; updateMask = 'auditConfigs,etag' }
    }
    $budgetRoot = "https://billingbudgets.googleapis.com/v1/billingAccounts/$($config.billing_account_id)/budgets"
    $budgetName = "nyc311-$project"
    $budget = @{
        displayName = $budgetName
        budgetFilter = @{ projects = @("projects/$($projectInfo.projectNumber)"); calendarPeriod = 'MONTH'; creditTypesTreatment = 'EXCLUDE_ALL_CREDITS' }
        amount = @{ specifiedAmount = @{ currencyCode = 'USD'; units = [string][math]::Floor($config.budget_amount_usd); nanos = [int](($config.budget_amount_usd % 1) * 1000000000) } }
        thresholdRules = @(@{ thresholdPercent = 0.5 }, @{ thresholdPercent = 0.8 }, @{ thresholdPercent = 1.0 })
        notificationsRule = @{ disableDefaultIamRecipients = $false; enableProjectLevelRecipients = $true }
    }
    $matchingBudgets = @()
    $pageToken = ''
    do {
        $uri = $budgetRoot + '?pageSize=100'
        if ($pageToken) { $uri += '&pageToken=' + [uri]::EscapeDataString($pageToken) }
        $page = Invoke-Nyc311Api -Method GET -Uri $uri -Token $token -QuotaProject $project
        if ($null -ne $page.PSObject.Properties['budgets']) { $matchingBudgets += @($page.budgets | Where-Object { $_.displayName -eq $budgetName }) }
        $pageToken = ''
        if ($null -ne $page.PSObject.Properties['nextPageToken']) { $pageToken = $page.nextPageToken }
    } while ($pageToken)
    if ($matchingBudgets.Count -eq 0) {
        $null = Invoke-Nyc311Api -Method POST -Uri $budgetRoot -Token $token -Body $budget -QuotaProject $project
    } elseif ($matchingBudgets.Count -ne 1) { throw 'Multiple budgets have this demo name; inspect them before continuing.' }
    Write-Output 'Bootstrap completed. Run infra/Test-GcpSecurity.ps1 and inspect budget recipients before loading data.'
} finally { $token = $null }
