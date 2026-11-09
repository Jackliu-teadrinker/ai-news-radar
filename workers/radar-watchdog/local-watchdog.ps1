<#
  local-watchdog.ps1 — 本地兜底哨兵（Windows 任务计划，每 30 分钟一次）

  和 Cloudflare Worker 版本职责相同：在 GitHub 之外检查 Pages 数据年龄，
  必要时补一刀 dispatch；若 dispatch 返回「Actions has been disabled」，
  就把事故写进日志并（可选）打 webhook。gh 已在本机登录即可用，不需要额外 token。

  注册任务（管理员 PowerShell 里跑一次）：
    schtasks /create /tn "radar-watchdog" /sc minute /mo 30 /f ^
      /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"C:\path\to\local-watchdog.ps1\""

  手动跑一次：
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\local-watchdog.ps1
#>

[CmdletBinding()]
param(
  [int]$WarnMinutes = 90,
  [string]$Repo = "Jackliu-teadrinker/ai-news-radar",
  [string]$Workflow = "update-news.yml",
  [string]$DataUrl = "https://jackliu-teadrinker.github.io/ai-news-radar/data/latest-24h-min.json",
  [string]$WebhookUrl = $env:RADAR_ALERT_WEBHOOK,
  [string]$LogDir = "$env:LOCALAPPDATA\radar-watchdog"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$logFile = Join-Path $LogDir "watchdog.log"

function Write-Log([string]$Level, [string]$Message) {
  $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Level, $Message
  Add-Content -Path $logFile -Value $line -Encoding utf8
  Write-Output $line
  if ($WebhookUrl) {
    try {
      $body = @{ text = "[radar-watchdog][$Level] $Message" } | ConvertTo-Json -Compress
      Invoke-WebRequest -Uri $WebhookUrl -Method Post -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 15 | Out-Null
    } catch { Write-Output "  (webhook failed: $($_.Exception.Message))" }
  }
}

try {
  $json = Invoke-RestMethod -Uri ("{0}?cb={1}" -f $DataUrl, [int][double]::Parse((Get-Date -UFormat %s))) -UseBasicParsing -TimeoutSec 20
} catch {
  Write-Log "CRIT" "Pages 数据取不到：$($_.Exception.Message)"
  exit 1
}

$generatedAt = $json.generated_at
if (-not $generatedAt) { Write-Log "CRIT" "数据里没有 generated_at"; exit 1 }

$ageMin = [math]::Round(((Get-Date).ToUniversalTime() - [datetimeoffset]::Parse($generatedAt).UtcDateTime).TotalMinutes)
Write-Log "INFO" ("generated_at={0} age={1}min items={2}" -f $generatedAt, $ageMin, $json.total_items)

if ($ageMin -le $WarnMinutes) { exit 0 }

$dispatchOut = & gh.exe workflow run $Workflow --repo $Repo --ref master 2>&1
if ($LASTEXITCODE -eq 0) {
  Write-Log "WARN" ("数据已 {0} 分钟未更新 -> 已补 dispatch" -f $ageMin)
  exit 0
}

if ($dispatchOut -match "disabled") {
  Write-Log "CRIT" ("Actions 被停用，dispatch 失败：{0}。去 https://github.com/{1}/actions 点 re-enable" -f ($dispatchOut -join " "), $Repo)
  exit 2
}

Write-Log "WARN" ("数据已 {0} 分钟未更新，dispatch 也失败：{1}" -f $ageMin, ($dispatchOut -join " "))
exit 1
