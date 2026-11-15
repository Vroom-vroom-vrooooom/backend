param(
    [string]$Gcloud = 'gcloud',
    [string]$Project = 'vroom-514610',
    [string]$Region = 'asia-northeast3'
)
$ErrorActionPreference = 'Stop'

function Invoke-Gcloud([string[]]$Arguments) {
    & $Gcloud @Arguments
    if ($LASTEXITCODE -ne 0) { throw "gcloud failed: $($Arguments[0..1] -join ' ')" }
}

$Account = "chagok-github-deploy@$Project.iam.gserviceaccount.com"
$Runtime = "chagok-runtime@$Project.iam.gserviceaccount.com"
$ProjectNumber = (& $Gcloud projects describe $Project --format='value(projectNumber)').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot read GCP project' }

Invoke-Gcloud @('services', 'enable', 'iam.googleapis.com', 'iamcredentials.googleapis.com',
    'sts.googleapis.com', 'artifactregistry.googleapis.com', 'run.googleapis.com', "--project=$Project", '--quiet')

& $Gcloud iam service-accounts describe $Account --project=$Project --format=none 2>$null
if ($LASTEXITCODE -ne 0) {
    Invoke-Gcloud @('iam', 'service-accounts', 'create', 'chagok-github-deploy', "--project=$Project", '--quiet')
}
& $Gcloud artifacts repositories describe chagok-images --project=$Project --location=$Region --format=none 2>$null
if ($LASTEXITCODE -ne 0) {
    Invoke-Gcloud @('artifacts', 'repositories', 'create', 'chagok-images', '--repository-format=docker',
        "--project=$Project", "--location=$Region", '--quiet')
}
& $Gcloud iam workload-identity-pools describe github-actions --project=$Project --location=global --format=none 2>$null
if ($LASTEXITCODE -ne 0) {
    Invoke-Gcloud @('iam', 'workload-identity-pools', 'create', 'github-actions',
        "--project=$Project", '--location=global', '--quiet')
}

# Numeric IDs cannot be reclaimed by another GitHub repository/organization.
$ProviderFlags = @{
    '--issuer-uri' = 'https://token.actions.githubusercontent.com'
    '--attribute-mapping' = @{
        'google.subject' = 'assertion.sub'
        'attribute.repository_id' = 'assertion.repository_id'
        'attribute.repository_owner_id' = 'assertion.repository_owner_id'
        'attribute.ref' = 'assertion.ref'
        'attribute.workflow_ref' = 'assertion.workflow_ref'
        'attribute.event_name' = 'assertion.event_name'
    }
    '--attribute-condition' = "assertion.repository_id == '1456469220' && assertion.repository_owner_id == '355321586' && assertion.ref == 'refs/heads/main' && assertion.workflow_ref == 'Vroom-vroom-vrooooom/backend/.github/workflows/deploy.yml@refs/heads/main' && assertion.event_name in ['push', 'workflow_dispatch']"
}
$FlagsPath = Join-Path ([IO.Path]::GetTempPath()) 'chagok-wif-provider.json'
$ProviderFlags | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $FlagsPath -Encoding utf8
try {
    & $Gcloud iam workload-identity-pools providers describe backend-main --workload-identity-pool=github-actions --project=$Project --location=global --format=none 2>$null
    $Operation = if ($LASTEXITCODE -eq 0) { 'update-oidc' } else { 'create-oidc' }
    Invoke-Gcloud @('iam', 'workload-identity-pools', 'providers', $Operation, 'backend-main',
        '--workload-identity-pool=github-actions', "--project=$Project", '--location=global', "--flags-file=$FlagsPath", '--quiet')
} finally {
    Remove-Item -LiteralPath $FlagsPath -ErrorAction SilentlyContinue
}

Invoke-Gcloud @('iam', 'service-accounts', 'add-iam-policy-binding', $Account, "--project=$Project",
    '--role=roles/iam.workloadIdentityUser',
    "--member=principalSet://iam.googleapis.com/projects/$ProjectNumber/locations/global/workloadIdentityPools/github-actions/attribute.repository_id/1456469220", '--format=none', '--quiet')
Invoke-Gcloud @('run', 'services', 'add-iam-policy-binding', 'chagok-api', "--project=$Project", "--region=$Region",
    "--member=serviceAccount:$Account", '--role=roles/run.developer', '--format=none', '--quiet')
Invoke-Gcloud @('iam', 'service-accounts', 'add-iam-policy-binding', $Runtime, "--project=$Project",
    "--member=serviceAccount:$Account", '--role=roles/iam.serviceAccountUser', '--format=none', '--quiet')
Invoke-Gcloud @('artifacts', 'repositories', 'add-iam-policy-binding', 'chagok-images', "--project=$Project", "--location=$Region",
    "--member=serviceAccount:$Account", '--role=roles/artifactregistry.writer', '--format=none', '--quiet')
Invoke-Gcloud @('projects', 'add-iam-policy-binding', $Project, "--member=serviceAccount:$Account",
    '--role=roles/serviceusage.serviceUsageConsumer', '--condition=None', '--format=none', '--quiet')

Write-Output "Workload identity provider: projects/$ProjectNumber/locations/global/workloadIdentityPools/github-actions/providers/backend-main"
Write-Output "Deployment service account: $Account"
