<#
  doctor.ps1 —— 雷达一键体检（把 POSTMORTEM 里的「5 分钟定位」变成一条命令）

  用法：
    .\doctor.ps1              # 人读摘要
    .\doctor.ps1 -Json        # 机器可读（给告警/API 用）

  退出码：0 全绿 | 1 有 WARN | 2 有 FAIL
#>
param([switch]$Json, [int]$StaleMinutes = 90)

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root    = 'E:\WIKI数据库\雷达数据'
$Repo    = Join-Path $Root '_repo'
$Live    = Join-Path $Root 'live'
$Py      = Join-Path $Root '.venv\Scripts\python.exe'
$Metrics = Join-Path $Root 'metrics.jsonl'
$Logs    = Join-Path $Root 'logs'
$SiteIndexUrl = 'https://jackliu-teadrinker.github.io/ai-news-radar/data/days/index.json'
$SiteSnapshotUrl = 'https://jackliu-teadrinker.github.io/ai-news-radar/data/latest-24h-min.json'
$Git     = 'C:\Users\86571\AppData\Local\hermes\tools\git-2.53.0+3-win32-x64\mingw64\bin\git.exe'
if (-not (Test-Path -LiteralPath $Git)) { $Git = 'git.exe' }

$rows = New-Object System.Collections.ArrayList
function Add-Row([string]$item, [string]$status, [string]$detail) {
  [void]$rows.Add([pscustomobject]@{ item = $item; status = $status; detail = $detail })
}

# 1) 依赖环境
if (Test-Path -LiteralPath $Py) {
  $probe = & $Py -c "import feedparser,requests,trafilatura,selectolax,googlenewsdecoder;print('ok')" 2>&1
  if ($probe -match 'ok') { Add-Row '依赖' 'PASS' 'venv + 5 个包齐全' }
  else { Add-Row '依赖' 'FAIL' ("导入失败：" + ($probe -join ' ')) }
} else { Add-Row '依赖' 'FAIL' "venv 缺失：$Py" }

# 2) 发布仓库与代理
if (Test-Path -LiteralPath (Join-Path $Repo '.git')) {
  $proxy = & $Git -C $Repo config --get http.proxy
  $ver   = & $Git -C $Repo config --get http.version
  if ($proxy -and $ver) { Add-Row 'git 通道' 'PASS' "proxy=$proxy version=$ver" }
  else { Add-Row 'git 通道' 'WARN' '未配置 http.proxy/http.version，push 可能被 reset' }

  $dirty = (& $Git -C $Repo status --porcelain -- data index.html) -join ''
  if (-not $dirty) { Add-Row '工作副本' 'PASS' '无未提交改动' }
  else { Add-Row '工作副本' 'WARN' 'data/index.html 有未提交改动（可能上一轮没推上去）' }
} else { Add-Row 'git 通道' 'FAIL' "发布仓库缺失：$Repo" }

# 3) 线上站点（方案C 之后，新鲜度信号在 days/index.json；
#    latest-24h-min.json 只是每天定版的兜底，年龄大是正常的）
$online = $null
try {
  $online = Invoke-RestMethod ($SiteIndexUrl + '?cb=' + [int][double]::Parse((Get-Date -UFormat %s))) -UseBasicParsing -TimeoutSec 20
} catch { }
if ($online -and $online.generated_at) {
  $age = [math]::Round(((Get-Date).ToUniversalTime() - [datetimeoffset]::Parse($online.generated_at).UtcDateTime).TotalMinutes)
  $st = if ($age -le 45) { 'PASS' } elseif ($age -le $StaleMinutes) { 'WARN' } else { 'FAIL' }
  Add-Row '线上分片' $st ("index.generated_at 距今 {0} 分钟 / {1} 个日期 / latest={2}" -f $age, @($online.days).Count, $online.latest)
} else { Add-Row '线上分片' 'FAIL' 'data/days/index.json 取不到（Pages 或分片链路异常）' }

try {
  $snapOnline = Invoke-RestMethod ($SiteSnapshotUrl + '?cb=' + [int][double]::Parse((Get-Date -UFormat %s))) -UseBasicParsing -TimeoutSec 20
  Add-Row '兜底快照' 'PASS' ("latest-24h-min.json 存在（定版于 {0}，{1} 条；每天只更新一次属正常）" -f $snapOnline.generated_at, $snapOnline.total_items)
} catch { Add-Row '兜底快照' 'WARN' 'latest-24h-min.json 取不到，前端分片失败时无兜底' }

# 4) 本地 live
$liveFile = Join-Path $Live 'latest-24h-min.json'
if (Test-Path -LiteralPath $liveFile) {
  try {
    $local = Get-Content -LiteralPath $liveFile -Raw -Encoding utf8 | ConvertFrom-Json
    $lag = '—'
    if ($online -and $local.generated_at -eq $online.generated_at) { $lag = '与线上分片一致' }
    elseif ($online) { $lag = '本地更新（下一轮会进分片）' }
    Add-Row '本地 live' 'PASS' ("generated_at={0} / {1} 条 / {2}" -f $local.generated_at, $local.total_items, $lag)
  } catch { Add-Row '本地 live' 'FAIL' 'JSON 解析失败（文件可能被写坏）' }
} else { Add-Row '本地 live' 'FAIL' "缺少 $liveFile" }

# 5) 计划任务
try {
  $task = Get-ScheduledTask -TaskName 'radar-local-refresh' -ErrorAction Stop
  $info = Get-ScheduledTaskInfo -TaskName 'radar-local-refresh'
  $st = if ($task.State -ne 'Ready' -and $task.State -ne 'Running') { 'FAIL' } elseif ($info.LastTaskResult -ne 0) { 'WARN' } else { 'PASS' }
  Add-Row '计划任务' $st ("state={0} last={1} result={2} next={3}" -f $task.State, $info.LastRunTime, $info.LastTaskResult, $info.NextRunTime)
} catch { Add-Row '计划任务' 'FAIL' '未注册 radar-local-refresh（不会自动更新）' }

# 6) 锁残留
$lock = Join-Path $Root 'run.lock'
if (Test-Path -LiteralPath $lock) {
  $age = ((Get-Date) - (Get-Item -LiteralPath $lock).LastWriteTime).TotalMinutes
  $st = if ($age -gt 45) { 'WARN' } else { 'PASS' }
  Add-Row '运行锁' $st ("残留 {0:N0} 分钟（>45 分钟说明上一轮异常中断）" -f $age)
} else { Add-Row '运行锁' 'PASS' '无残留' }

# 7) 仓库卫生
$tracked = & $Git -C $Repo ls-files -- data
$bad = $tracked | Where-Object { $_ -match 'curated/|archive\.json|gn-url-cache|seen_urls|title-zh-cache' }
if ($bad) { Add-Row '仓库卫生' 'FAIL' ("归档文件回到索引，会重演膨胀：" + ($bad -join ',')) }
else {
  $bytes = 0
  foreach ($rel in $tracked) { $f = Join-Path $Repo $rel; if (Test-Path -LiteralPath $f) { $bytes += (Get-Item -LiteralPath $f).Length } }
  $st = if ($bytes -gt 2MB) { 'WARN' } else { 'PASS' }
  Add-Row '仓库卫生' $st ("data/ 索引 {0:N1} KB / {1} 个文件" -f ($bytes / 1KB), @($tracked).Count)
}

# 8) 近 24 轮指标
if (Test-Path -LiteralPath $Metrics) {
  $lines = Get-Content -LiteralPath $Metrics -Encoding utf8 | Select-Object -Last 24 | Where-Object { $_.Trim() }
  $ok = 0; $bad = 0; $skipped = 0; $durs = @(); $mismatch = 0
  foreach ($l in $lines) {
    try {
      $o = $l | ConvertFrom-Json
      $durs += [int]$o.elapsed_s
      if ($o.exit_code -ne 0) { $bad++ }
      elseif (-not $o.published) { $skipped++ }
      else { $ok++ }
      if ($o.published -and -not $o.verify_ok) { $mismatch++ }
    } catch { }
  }
  $avg = if ($durs.Count) { [math]::Round(($durs | Measure-Object -Average).Average) } else { 0 }
  $st = if ($bad -gt 0) { 'WARN' } elseif ($mismatch -gt 0) { 'FAIL' } else { 'PASS' }
  Add-Row '近期指标' $st ("样本 {0} 轮：发布 {1} / 跳过 {2} / 失败 {3} / 自检不符 {4} / 平均 {5}s" -f $lines.Count, $ok, $skipped, $bad, $mismatch, $avg)
} else { Add-Row '近期指标' 'WARN' 'metrics.jsonl 还没有数据' }

# 9) 今日日志有无 FAIL
$logFile = Join-Path $Logs ('radar-{0}.log' -f (Get-Date -Format 'yyyyMMdd'))
if (Test-Path -LiteralPath $logFile) {
  $lines2 = Get-Content -LiteralPath $logFile -Encoding utf8
  $fails = @($lines2 | Where-Object { $_ -match '\[FAIL\]' }).Count
  $lastFail = ($lines2 | Select-String -Pattern '\[FAIL\]' | Select-Object -Last 1).LineNumber
  $lastOk   = ($lines2 | Select-String -Pattern '\[VERIFY\] OK' | Select-Object -Last 1).LineNumber
  # 只有「最近一次事件是失败」才算当前异常；历史失败已经恢复就不该长期亮黄
  $st = if ($lastFail -and ($lastFail -gt [int]$lastOk)) { 'WARN' } else { 'PASS' }
  Add-Row '今日日志' $st ("[FAIL] 累计 {0} 次；最近一次{1}（{2}）" -f $fails, $(if ($lastFail -and $lastFail -gt [int]$lastOk) { '在最近成功之后' } else { '已被后续成功覆盖' }), (Split-Path $logFile -Leaf))
} else { Add-Row '今日日志' 'WARN' '今天还没有运行日志' }

# ---- 输出 ----
$fail = @($rows | Where-Object { $_.status -eq 'FAIL' }).Count
$warn = @($rows | Where-Object { $_.status -eq 'WARN' }).Count

if ($Json) {
  $rows | ConvertTo-Json -Depth 4
} else {
  $rows | ForEach-Object { "{0,-6} {1,-10} {2}" -f $_.status, $_.item, $_.detail }
  ""
  "合计：PASS {0} / WARN {1} / FAIL {2}" -f (@($rows | Where-Object { $_.status -eq 'PASS' }).Count), $warn, $fail
}

if ($fail -gt 0) { exit 2 }
if ($warn -gt 0) { exit 1 }
exit 0
