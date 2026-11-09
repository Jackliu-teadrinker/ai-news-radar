<#
  daily-summary.ps1 —— 把 metrics.jsonl + 当日日志汇总成一行日报（Markdown）

  目的：让「异常」表现为趋势而不是事故。每轮采集都在 metrics.jsonl 记一行，
  这里负责把它读成「今天几轮、几轮被 GUARD 拦、平均耗时、源稳定性」。

  用法：
    .\daily-summary.ps1                    # 打印并写 logs\daily-YYYYMMDD.md
    .\daily-summary.ps1 -Days 7            # 回看最近 7 天
    .\daily-summary.ps1 -WebhookUrl "..."  # 额外推送到接受 {"text": "..."} 的 webhook
#>
param(
  [int]$Days = 1,
  [string]$WebhookUrl = $env:RADAR_ALERT_WEBHOOK,
  [switch]$NoWrite
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root    = 'E:\WIKI数据库\雷达数据'
$Metrics = Join-Path $Root 'metrics.jsonl'
$LogDir  = Join-Path $Root 'logs'
$Live    = Join-Path $Root 'live'

if (-not (Test-Path -LiteralPath $Metrics)) { throw "没有 metrics.jsonl：$Metrics" }

$since = (Get-Date).AddDays(-$Days)
$rows = @()
foreach ($l in Get-Content -LiteralPath $Metrics -Encoding utf8) {
  if (-not $l.Trim()) { continue }
  try {
    $o = $l | ConvertFrom-Json
    $ts = [datetimeoffset]::Parse($o.ts)
    if ($ts.LocalDateTime -ge $since) { $rows += $o }
  } catch { }
}

if (-not $rows.Count) { "最近 $Days 天没有运行记录"; exit 0 }

$published = @($rows | Where-Object { $_.published }).Count
$skipped   = @($rows | Where-Object { -not $_.published -and $_.exit_code -eq 0 }).Count
$failed    = @($rows | Where-Object { $_.exit_code -ne 0 }).Count
$mismatch  = @($rows | Where-Object { $_.published -and -not $_.verify_ok }).Count
$durs      = $rows | ForEach-Object { [int]$_.elapsed_s }
$items     = @($rows | Where-Object { $_.items -gt 0 } | ForEach-Object { [int]$_.items })
$avgDur    = if ($durs.Count) { [math]::Round(($durs | Measure-Object -Average).Average, 1) } else { 0 }
$avgItems  = if ($items.Count) { [math]::Round(($items | Measure-Object -Average).Average, 1) } else { 0 }

# 轮次间隔（用相邻 ts 差的中位数判断是否真的每 30 分钟一拍）
$gaps = @()
$sorted = $rows | Sort-Object { [datetimeoffset]::Parse($_.ts) }
for ($i = 1; $i -lt $sorted.Count; $i++) {
  $gaps += ([datetimeoffset]::Parse($sorted[$i].ts) - [datetimeoffset]::Parse($sorted[$i-1].ts)).TotalMinutes
}
$medianGap = if ($gaps.Count) { [math]::Round(($gaps | Sort-Object)[[int]($gaps.Count / 2)], 1) } else { 0 }

# 当前源成功率
$okFeeds = 'n/a'; $totalFeeds = 'n/a'
$statusFile = Join-Path $Live 'source-status.json'
if (Test-Path -LiteralPath $statusFile) {
  try {
    $s = Get-Content -LiteralPath $statusFile -Raw -Encoding utf8 | ConvertFrom-Json
    $okFeeds = $s.summary.successful_feeds
    $totalFeeds = $s.summary.total_feeds
  } catch { }
}

$latest = $sorted[-1]
$stamp = (Get-Date -Format 'yyyy-MM-dd HH:mm')
$md = @()
$md += "# 雷达日报 $stamp（近 $Days 天）"
$md += ""
$md += "| 指标 | 数值 |"
$md += "| --- | --- |"
$md += "| 运行轮次 | $($rows.Count) |"
$md += "| 正常发布 | $published |"
$md += "| GUARD 跳过 | $skipped |"
$md += "| 失败 | $failed |"
$md += "| 发布后自检不符 | $mismatch |"
$md += "| 平均耗时 | $avgDur s |"
$md += "| 平均条数 | $avgItems |"
$md += "| 实际中位间隔 | $medianGap min（目标 30） |"
$md += "| 信源健康 | $okFeeds / $totalFeeds |"
$md += "| 最后一轮 | $($latest.ts) items=$($latest.items) verify=$($latest.verify_ok) |"
$md += ""
if ($failed -gt 0) { $md += "> [!warning] 有 $failed 轮失败，请查 logs\ 中对应时间段的 [FAIL]。`n" }
if ($medianGap -gt 45) { $md += "> [!warning] 中位间隔 $medianGap 分钟，明显慢于 30 分钟：检查本机是否休眠/任务是否被限流。`n" }

$text = $md -join "`n"
Write-Output $text

if (-not $NoWrite) {
  $out = Join-Path $LogDir ('daily-{0}.md' -f (Get-Date -Format 'yyyyMMdd'))
  Set-Content -LiteralPath $out -Value $text -Encoding utf8
  Write-Output "`n已写入 $out"
}

if ($WebhookUrl) {
  try {
    $payload = @{ text = ("[radar] 近 $Days 天：{0} 轮 / 发布 {1} / 跳过 {2} / 失败 {3} / 间隔中位 {4}min / 源 {5}-{6}" -f $rows.Count, $published, $skipped, $failed, $medianGap, $okFeeds, $totalFeeds) } | ConvertTo-Json -Compress
    Invoke-WebRequest -Uri $WebhookUrl -Method Post -Body $payload -ContentType 'application/json' -UseBasicParsing -TimeoutSec 15 | Out-Null
    Write-Output '已推送 webhook'
  } catch { Write-Output ("webhook 推送失败：" + $_.Exception.Message) }
}
