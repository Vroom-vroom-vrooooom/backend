param(
    [string]$Project = 'vroom-514610',
    [string]$Region = 'asia-northeast3',
    [string]$Gcloud = 'gcloud',
    [string]$Model = 'claude-sonnet-5-5'
)
$ErrorActionPreference = 'Stop'
$SourceDirectory = Split-Path $PSScriptRoot
& $Gcloud run deploy chagok-api --project=$Project --region=$Region --source $SourceDirectory --service-account="chagok-runtime@$Project.iam.gserviceaccount.com" --build-service-account="projects/$Project/serviceAccounts/chagok-builder@$Project.iam.gserviceaccount.com" --allow-unauthenticated --cpu=1 --memory=512Mi --min=0 --max=2 --concurrency=20 --timeout=120 --set-env-vars="GOOGLE_CLOUD_PROJECT=$Project,ANTHROPIC_MODEL=$Model" --set-secrets='ANTHROPIC_API_KEY=chagok-anthropic:1,JWT_SECRET=chagok-jwt:1,INVITE_KEY=chagok-invite:1' --quiet
if ($LASTEXITCODE -ne 0) { throw 'Cloud Run deployment failed' }
