<#
  run-radar.ps1 —— 机器人新闻雷达「本地采集 + 发布」总控（路线 L）

  数据流向：
    采集产物（全量）  -> E:\WIKI数据库\雷达数据\live\   （archive / curated / 抓取缓存都在这里，永不进仓库）
    站点快照（7 个）  -> _repo\data\  -> git push -> GitHub Pages 自动重建

  为什么这么切：
    live 里的 gn-url-cache.json(6.2MB) 与 curated/(6.6MB) 是仓库历史膨胀的元凶，
    站点前端根本不读它们（见 assets/app.js 的 fetch 列表）；
    真正要公网的只有 7 个文件、约 386KB。

  用法：
    .\run-radar.ps1                 # 采集 + 发布（计划任务用这个）
    .\run-radar.ps1 -OnlyPublish    # 不采集，只把现有 live 快照发布出去
    .\run-radar.ps1 -NoPublish      # 只采集，不发布（调试用）
#>
param(
  [switch]$OnlyPublish,
  [switch]$NoPublish,
  [int]$WindowHours = 24,
  [int]$ArxivWindowHours = 168,   # arXiv 单独用 7 天窗口：周末不宣布论文，24h 会连续 0 条
  [int]$ArchiveDays = 21,
  [int]$LockMinutes = 45,
  [string]$Proxy = 'http://127.0.0.1:7897',   # 本机 Clash 混合端口；直连/HTTP2 会被 Connection reset
  [string]$SiteIndexUrl = 'https://jackliu-teadrinker.github.io/ai-news-radar/data/days/index.json',
  [string]$HeartbeatUrl = ''                   # 可选：UptimeRobot 心跳 URL 等，发布成功后打一下
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = 'E:\WIKI数据库\雷达数据'
$Repo = Join-Path $Root '_repo'
$Live = Join-Path $Root 'live'
$Logs = Join-Path $Root 'logs'
$Py   = Join-Path $Root '.venv\Scripts\python.exe'
$Git  = 'C:\Users\86571\AppData\Local\hermes\tools\git-2.53.0+3-win32-x64\mingw64\bin\git.exe'
if (-not (Test-Path -LiteralPath $Git)) { $Git = 'git.exe' }
$Lock = Join-Path $Root 'run.lock'

# 站点真正读取的快照白名单（其余文件一律留在 live）
$Snapshots = @(
  'latest-24h-min.json',
  'arxiv-papers.json',
  'custom-anchors.json',
  'government-news.json',
  'toutiao-news.json',
  'wechat-articles.json',
  'source-status.json'
)

$Metrics = Join-Path $Root 'metrics.jsonl'
$script:t0 = Get-Date
$script:items = 0
$script:published = $false
$script:verifyOk = $false

New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$logFile = Join-Path $Logs ("radar-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

function Log([string]$msg) {
  $line = "{0} {1}" -f (Get-Date -Format 'HH:mm:ss'), $msg
  Write-Output $line
  Add-Content -LiteralPath $logFile -Value $line -Encoding utf8
}

# PS 5.1 里 `& python ... 2>&1` 会把 stderr 当成 ErrorRecord，配合 $ErrorActionPreference='Stop'
# 直接终止脚本。统一用 Start-Process 重定向到临时文件，只拿退出码和文本。
function Invoke-Native {
  param([string]$Exe, [string[]]$ArgList, [string]$WorkDir)
  $o = Join-Path $env:TEMP ("radar-out-" + [guid]::NewGuid().ToString('N') + ".log")
  $e = Join-Path $env:TEMP ("radar-err-" + [guid]::NewGuid().ToString('N') + ".log")
  $quoted = $ArgList | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
  $p = Start-Process -FilePath $Exe -ArgumentList $quoted -WorkingDirectory $WorkDir `
        -RedirectStandardOutput $o -RedirectStandardError $e -NoNewWindow -PassThru -Wait
  $lines = @()
  if (Test-Path -LiteralPath $o) { $lines += Get-Content -LiteralPath $o -Encoding utf8 }
  if (Test-Path -LiteralPath $e) { $lines += Get-Content -LiteralPath $e -Encoding utf8 }
  Remove-Item -LiteralPath $o, $e -ErrorAction SilentlyContinue
  return @{ Code = $p.ExitCode; Lines = $lines }
}

if (-not (Test-Path -LiteralPath $Py))   { throw "Python venv 缺失：$Py" }
if (-not (Test-Path -LiteralPath $Repo)) { throw "发布仓库缺失：$Repo" }
New-Item -ItemType Directory -Force -Path $Live | Out-Null

# 防重入：上一轮没跑完（默认 45 分钟内）就不再开新的一轮
if (Test-Path -LiteralPath $Lock) {
  $age = ((Get-Date) - (Get-Item -LiteralPath $Lock).LastWriteTime).TotalMinutes
  if ($age -lt $LockMinutes) {
    Log ("[SKIP] 上一轮仍在运行（{0:N0} 分钟前开始），本轮跳过" -f $age)
    exit 0
  }
}
Set-Content -LiteralPath $Lock -Value (Get-Date -Format o) -Encoding utf8

$exitCode = 0
try {
  $env:RADAR_OUTPUT_DIR = $Live
  $env:TZ = 'Asia/Shanghai'
  $env:PYTHONIOENCODING = 'utf-8'
  $env:PYTHONUTF8 = '1'

  # ---------- 1. 采集 ----------
  if (-not $OnlyPublish) {
    Log "[FETCH] 开始采集 -> $Live"

    $steps = @(
      @{ name = 'update_news'; args = @('scripts/update_news.py','--output-dir',$Live,'--window-hours',"$WindowHours",'--rss-opml','feeds/follow.example.opml','--custom-opml','feeds/custom.opml','--archive-days',"$ArchiveDays") },
      @{ name = 'arxiv';       args = @('scripts/arxiv_fetcher.py','--output-dir',$Live,'--window-hours',"$ArxivWindowHours") },
      @{ name = 'government';  args = @('scripts/government_fetcher.py','--output-dir',$Live) },
      @{ name = 'toutiao';     args = @('scripts/toutiao_fetcher.py','--output-dir',$Live) },
      @{ name = 'curated';     args = @('scripts/curated_collector.py','--data-path',(Join-Path $Live 'latest-24h-min.json'),'--curated-dir',(Join-Path $Live 'curated')) }
    )

    foreach ($s in $steps) {
      $t0 = Get-Date
      Log ("[FETCH] {0} ..." -f $s.name)
      $r = Invoke-Native -Exe $Py -ArgList $s.args -WorkDir $Repo
      $r.Lines | ForEach-Object { Add-Content -LiteralPath $logFile -Value ("    " + $_) -Encoding utf8 }
      $r.Lines | Select-Object -Last 4 | ForEach-Object { Write-Output ("    " + $_) }
      Log ("[FETCH] {0} 退出码={1} 用时={2:N0}s" -f $s.name, $r.Code, ((Get-Date) - $t0).TotalSeconds)
      if ($r.Code -ne 0 -and $s.name -eq 'update_news') { throw "update_news 失败（退出码 $($r.Code)），本轮不发布" }
    }

    $latest = Join-Path $Live 'latest-24h-min.json'
    if (-not (Test-Path -LiteralPath $latest)) { throw "采集未产出 latest-24h-min.json" }
    $n = (Get-Content -LiteralPath $latest -Raw -Encoding utf8 | ConvertFrom-Json).total_items
    $script:items = $n
    Log "[GUARD] 本轮条数 = $n"
    if ($n -eq 0) { Log "[GUARD] 本轮 0 条，拒绝覆盖已发布快照；本轮结束（不算失败）"; return }
  }

  # ---------- 2. 发布 ----------
  if ($NoPublish) { Log "[PUBLISH] -NoPublish，跳过发布"; return }

  # 2026-11-09 SELF-HEAL：云端接管过一轮后，远端会比本机多一个 [radar-auto] 提交，
  # 本机如果直接 push 会被拒（non-fast-forward），而且此后每轮都失败 → 本机静默掉队。
  # 所以每轮发布前先对齐 origin/master。_repo 里只有站点快照（本地独有的东西都在 live\），
  # reset --hard 不会丢数据；fetch 失败（代理/网络）就按现状继续，不阻断本轮。
  $sync = Invoke-Native -Exe $Git -ArgList @('-c',"http.proxy=$Proxy",'-c','http.version=HTTP/1.1','fetch','origin','master','--quiet') -WorkDir $Repo
  if ($sync.Code -eq 0) {
    $h1 = (& $Git -C $Repo rev-parse HEAD).Trim()
    # 2026-11-10 事故：无条件 reset --hard 会把本地未推送的代码提交直接抹掉
    # （实测 arxiv 窗口修复 + 翻译代理修复两个提交被丢弃，推送照样报成功、无任何提示）。
    # 只有「待丢弃的提交全是数据快照」时才允许硬对齐；含代码改动一律不碰。
    $ahead = (& $Git -C $Repo rev-list --count 'origin/master..HEAD').Trim()
    $dropOk = $false
    if ($ahead -eq '0') {
      $dropOk = $true
    } else {
      $paths = @(& $Git -C $Repo diff --name-only 'origin/master..HEAD')
      $codePaths = @($paths | Where-Object { $_ -and $_ -notmatch '^(data/|index\.html$)' })
      if ($codePaths.Count -eq 0) {
        $dropOk = $true
        Log ("[SYNC] 本地 {0} 个未推送提交只含数据快照（本轮会重新生成），允许对齐远端" -f $ahead)
      } else {
        Log ("[SYNC] 本地有 {0} 个未推送提交且含代码改动，跳过对齐以免丢失：{1}" -f $ahead, ($codePaths -join ', '))
      }
    }
    if ($dropOk) {
      $rs = Invoke-Native -Exe $Git -ArgList @('reset','--hard','origin/master') -WorkDir $Repo
      if ($rs.Code -eq 0) {
        $h2 = (& $Git -C $Repo rev-parse HEAD).Trim()
        if ($h1 -ne $h2) { Log ("[SYNC] 已对齐 origin/master：{0} -> {1}（云端接管过，本机追平）" -f $h1.Substring(0,7), $h2.Substring(0,7)) }
      } else {
        Log ("[SYNC] reset 失败（退出码 {0}），继续用当前工作区" -f $rs.Code)
      }
    }
  } else {
    Log ("[SYNC] fetch 失败（退出码 {0}，代理/网络问题），本轮按现状发布" -f $sync.Code)
  }

  $liveLatest = Join-Path $Live 'latest-24h-min.json'
  $repoLatest = Join-Path $Repo 'data\latest-24h-min.json'
  $newN = (Get-Content -LiteralPath $liveLatest -Raw -Encoding utf8 | ConvertFrom-Json).total_items
  $prevN = 0
  if (Test-Path -LiteralPath $repoLatest) {
    try { $prevN = (Get-Content -LiteralPath $repoLatest -Raw -Encoding utf8 | ConvertFrom-Json).total_items } catch { $prevN = 0 }
  }
  $script:items = $newN
  Log "[GUARD] 新快照 $newN 条 / 已发布 $prevN 条"
  if ($newN -eq 0) { Log "[GUARD] 新快照 0 条，拒绝发布；本轮结束（不算失败）"; return }
  if ($prevN -ge 20 -and $newN -lt ($prevN * 0.5)) {
    Log "[GUARD] 新快照只有已发布的 $([math]::Round($newN / $prevN * 100))%，疑似源集体故障，拒绝发布；本轮结束（不算失败）"
    return
  }

  foreach ($f in $Snapshots) {
    $src = Join-Path $Live $f
    if (-not (Test-Path -LiteralPath $src)) {
      if ($f -eq 'wechat-articles.json') {
        Set-Content -LiteralPath (Join-Path $Repo "data\$f") -Value '{}' -Encoding utf8
        Log "  [WARN] $f 缺失，用空对象兜底"
        continue
      }
      Log "  [WARN] live 缺少 $f，跳过"
      continue
    }
    # 抓取塌方保护：本轮 0 条就别覆盖已发布的健康快照（arxiv 抓空过一次）
    $obj = $null
    try { $obj = Get-Content -LiteralPath $src -Raw -Encoding utf8 | ConvertFrom-Json } catch { $obj = $null }
    if ($null -ne $obj -and $null -ne $obj.total_items -and $obj.total_items -eq 0 -and $f -ne 'wechat-articles.json') {
      Log "  [GUARD] $f 本轮 0 条，保留仓库里的旧快照"
      continue
    }
    if ($f -eq 'latest-24h-min.json') {
      # 方案C（2026-11-09）：主数据改走按日分片，这份大快照只作为前端兜底，
      # 每天定版一次即可；每轮重写它正是 5.8GB 历史的主因之一。
      $dstSnap = Join-Path $Repo "data\$f"
      $prevGen = $null
      if (Test-Path -LiteralPath $dstSnap) {
        try { $prevGen = (Get-Content -LiteralPath $dstSnap -Raw -Encoding utf8 | ConvertFrom-Json).generated_at } catch { }
      }
      if ($prevGen) {
        try {
          $prevLocalDate = [datetimeoffset]::Parse($prevGen).ToLocalTime().Date
          if ($prevLocalDate -eq (Get-Date).Date) {
            Log "  [SHARD] latest-24h-min.json 今日已定版，本轮只更新按日分片"
            continue
          }
        } catch { }
      }
    }
    Copy-Item -LiteralPath $src -Destination (Join-Path $Repo "data\$f") -Force
  }
  Log "[PUBLISH] 快照已同步到 _repo\data"

  # ---- 方案C：按日分片 data/days/YYYY-MM-DD.json ----
  # 一天一个文件，本轮只向当天分片追加新条目；前端取最近 3 天合并去重。
  # 收益：仓库每天只增约 250 KB，而不是 48 份 190 KB 全量快照。
  $daysRepo = Join-Path $Repo 'data\days'
  $daysLive = Join-Path $Live 'days'
  $daysArchive = Join-Path $Live 'days-archive'
  New-Item -ItemType Directory -Force -Path $daysRepo, $daysLive, $daysArchive | Out-Null

  $todayKey = (Get-Date).ToString('yyyy-MM-dd')
  $snapObj = Get-Content -LiteralPath $liveLatest -Raw -Encoding utf8 | ConvertFrom-Json
  $snapItems = @($snapObj.items_ai)

  # 按 published_at 的本地日期归属分片（不是按「今天跑到哪」）：
  # 昨夜 23:50 发布的条目落在昨天的文件里，指向明确、跨零点的文件也只会自然长满不再变动。
  $groups = @{}
  foreach ($it in $snapItems) {
    if (-not $it.url) { continue }
    $k = $todayKey
    if ($it.published_at) {
      try { $k = [datetimeoffset]::Parse($it.published_at).ToLocalTime().ToString('yyyy-MM-dd') } catch { $k = $todayKey }
    }
    if (-not $groups.ContainsKey($k)) { $groups[$k] = New-Object System.Collections.ArrayList }
    [void]$groups[$k].Add($it)
  }

  foreach ($k in @($groups.Keys | Sort-Object)) {
    $dayPathRepo = Join-Path $daysRepo ($k + '.json')
    $byUrl = [ordered]@{}
    if (Test-Path -LiteralPath $dayPathRepo) {
      try {
        $oldDay = Get-Content -LiteralPath $dayPathRepo -Raw -Encoding utf8 | ConvertFrom-Json
        foreach ($it in @($oldDay.items_ai)) { if ($it.url) { $byUrl[$it.url] = $it } }
      } catch { Log "  [WARN] $k.json 读取失败，按空分片重建" }
    }
    $added = 0
    foreach ($it in $groups[$k]) {
      $prev = $byUrl[$it.url]
      if (-not $prev) { $added++ }
      # 已有条目只在高分时替换值，位置不变 → git delta 只增不重排
      if (-not $prev -or [double]$it.total_score -gt [double]$prev.total_score) { $byUrl[$it.url] = $it }
    }
    $merged = @($byUrl.Values)
    # 无新增且已是「一行一条」的新格式 → 本轮完全不动这个文件（git 零 delta）
    $staleFormat = $false
    if (Test-Path -LiteralPath $dayPathRepo) {
      if ([System.IO.File]::ReadAllText($dayPathRepo) -notmatch "`n") { $staleFormat = $true }
    }
    if ($added -eq 0 -and -not $staleFormat -and $merged.Count -gt 0 -and (Test-Path -LiteralPath $dayPathRepo)) { continue }
    # 一条一行：单行大 JSON 会让 git 无法做行级 delta，整个文件每轮都像"全新"；
    # 每条 item 独占一行后，未变动的条目是逐字节相同的行，git 只存新增/改动的那几行。
    # 注意：单引号字符串里 `n 是字面量，必须用双引号拼换行
    $nl = "`n"
    $itemLines = ($merged | ForEach-Object { ($_ | ConvertTo-Json -Depth 20 -Compress) }) -join (',' + $nl)
    $dayJson = '{"date":"' + $k + '","generated_at":"' + $snapObj.generated_at +
               '","total_items":' + $merged.Count + ',"items_ai":[' + $nl + $itemLines + $nl + ']}' + $nl
    [System.IO.File]::WriteAllText($dayPathRepo, $dayJson, (New-Object System.Text.UTF8Encoding($false)))
    Copy-Item -LiteralPath $dayPathRepo -Destination (Join-Path $daysLive ($k + '.json')) -Force
    Log ("[SHARD] {0}.json：本轮新增 {1} 条，累计 {2} 条" -f $k, $added, $merged.Count)
  }

  # 索引（前端只读这个 + 最近 3 天分片）
  $dayFiles = @(Get-ChildItem -LiteralPath $daysRepo -File -Filter '*.json' |
                Where-Object { $_.BaseName -match '^\d{4}-\d{2}-\d{2}$' } | Sort-Object Name)
  $feedTotal = 0
  try {
    $ss = Get-Content -LiteralPath (Join-Path $Live 'source-status.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $feedTotal = [int]$ss.summary.total_feeds
  } catch { }
  $idxObj = [ordered]@{
    generated_at  = $snapObj.generated_at
    latest        = $todayKey
    days          = @($dayFiles | ForEach-Object { $_.BaseName })
    source_count  = $feedTotal
    archive_total = $snapObj.archive_total
  }
  $idxJson = $idxObj | ConvertTo-Json -Compress
  [System.IO.File]::WriteAllText((Join-Path $daysRepo 'index.json'), $idxJson, (New-Object System.Text.UTF8Encoding($false)))

  # 保留策略：仓库只留最近 60 天，更早的移到 E 盘 days-archive（历史不丢，只是不再随站点发布）
  $cutoff = (Get-Date).Date.AddDays(-60)
  foreach ($f in $dayFiles) {
    if ($f.BaseName -match '^\d{4}-\d{2}-\d{2}$') {
      $d = [datetime]::ParseExact($f.BaseName, 'yyyy-MM-dd', $null)
      if ($d -lt $cutoff) {
        Move-Item -LiteralPath $f.FullName -Destination (Join-Path $daysArchive $f.Name) -Force
        Log ("[SHARD] {0} 超过 60 天，归档到 live\days-archive" -f $f.Name)
      }
    }
  }

  # ---- 每日定版长期留档（2026-11-09）----
  # 分片只有 60 天在仓库里，且会被归档挪走；这里在 E 盘留一份「当天最后一版」，
  # 一年约 70 MB，永久可查、可直接拿去做蒸馏或回溯，不依赖 GitHub 历史。
  $historyDir = Join-Path $Live 'history'
  New-Item -ItemType Directory -Force -Path $historyDir | Out-Null
  $histPath = Join-Path $historyDir ($todayKey + '.json')
  $isNewHist = -not (Test-Path -LiteralPath $histPath)
  Copy-Item -LiteralPath $liveLatest -Destination $histPath -Force
  if ($isNewHist) { Log ("[HISTORY] 新建每日定版 live\history\{0}.json" -f $todayKey) }

  # index.html 版本号（前端缓存击穿）
  $idx = Join-Path $Repo 'index.html'
  if (Test-Path -LiteralPath $idx) {
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')
    $html = Get-Content -LiteralPath $idx -Raw -Encoding utf8
    $html = [regex]::Replace($html, '(<script src="\./assets/app\.js\?v=)[^"]*"', ('${1}' + $stamp + '"'))
    Set-Content -LiteralPath $idx -Value $html -Encoding utf8 -NoNewline
    Log "[PUBLISH] index.html 版本号 -> $stamp"
  }

  # ---- 仓库卫生断言：归档类文件绝不允许回到索引（这是 5.7GB 的死因）----
  $tracked = & $Git -C $Repo ls-files data/ | Where-Object { $_ -match 'curated/|archive\.json|gn-url-cache|seen_urls|title-zh-cache' }
  if ($tracked) { throw ("GUARD: 归档类文件重新进入索引，会造成仓库膨胀：" + ($tracked -join ', ')) }
  # 只统计「被 git 索引跟踪的」data/ 文件体积；工作副本里未跟踪的档案不计入（它们不进仓库）
  $dataBytes = 0
  foreach ($rel in (& $Git -C $Repo ls-files -- data)) {
    $full = Join-Path $Repo $rel
    if (Test-Path -LiteralPath $full) { $dataBytes += (Get-Item -LiteralPath $full).Length }
  }
  Log ("[GUARD] data/ 索引体积 {0:N1} KB（阈值 2048 KB）" -f ($dataBytes / 1KB))
  if ($dataBytes -gt 2MB) { Log "[WARN] data/ 索引超过 2MB，检查是否混入档案或缓存文件" }

  $gitBase = @('-c', "http.proxy=$Proxy", '-c', 'http.version=HTTP/1.1')
  & $Git @gitBase -C $Repo config user.email 'radar-local@users.noreply.github.com' | Out-Null
  & $Git @gitBase -C $Repo config user.name  'radar-local' | Out-Null
  & $Git @gitBase -C $Repo add -- data index.html | Out-Null
  $dirty = & $Git -C $Repo status --porcelain -- data index.html

  if (-not $dirty) {
    Log "[PUBLISH] 无变更，跳过提交"
  } else {
    $stampUtc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    $r = Invoke-Native -Exe $Git -ArgList @('commit','-m',"[radar-local] data refresh $stampUtc") -WorkDir $Repo
    $r.Lines | ForEach-Object { Add-Content -LiteralPath $logFile -Value $_ -Encoding utf8 }
    Log "[PUBLISH] 提交完成（退出码 $($r.Code)），准备推送"

    $p = Invoke-Native -Exe $Git -ArgList @('-c',"http.proxy=$Proxy",'-c','http.version=HTTP/1.1','push','origin','master') -WorkDir $Repo
    $p.Lines | ForEach-Object { Add-Content -LiteralPath $logFile -Value $_ -Encoding utf8 }
    if ($p.Code -eq 0) {
      $script:published = $true
      Log "[PUBLISH] 推送成功 -> GitHub Pages 将自动重建"
    } else {
      $p.Lines | ForEach-Object { Write-Output $_ }
      throw "git push 失败（退出码 $($p.Code)）"
    }
  }

  # ---- 发布后自检：线上 generated_at 必须等于本地这一轮 ----
  # 这是「静默失败」的唯一硬证据：push 成功 ≠ 站点更新（Pages 可能挂、构建可能失败）
  # 方案C 之后每轮都会更新的只有 data/days/index.json（latest-24h-min.json 每天定版一次），
  # 所以自检目标改成索引文件，否则当天第二轮起必然误报"线上未更新"。
  $expect = $snapObj.generated_at
  $online = $null
  $sw = Get-Date
  for ($i = 0; $i -lt 12; $i++) {
    Start-Sleep -Seconds 15
    try {
      $online = Invoke-RestMethod ($SiteIndexUrl + "?cb=" + [int][double]::Parse((Get-Date -UFormat %s))) -UseBasicParsing -TimeoutSec 20
      if ($online.generated_at -eq $expect) { break }
    } catch { $online = $null }
  }
  $waited = [int]((Get-Date) - $sw).TotalSeconds
  if ($online -and $online.generated_at -eq $expect) {
    $script:verifyOk = $true
    Log ("[VERIFY] OK 线上已生效：分片索引 latest={0} days={1}，等待 {2}s" -f $online.latest, (@($online.days).Count), $waited)
  } else {
    $got = if ($online) { $online.generated_at } else { '取不到（站点/网络异常）' }
    Log ("[VERIFY] FAIL 线上仍是 {0}，期望 {1}，等了 {2}s —— Pages 没发布或构建失败" -f $got, $expect, $waited)
    throw "发布后自检失败：线上快照未更新"
  }

  if ($HeartbeatUrl) {
    try {
      Invoke-WebRequest -Uri $HeartbeatUrl -UseBasicParsing -TimeoutSec 10 | Out-Null
      Log "[BEAT] 心跳已上报"
    } catch { Log ("[BEAT] 心跳上报失败（忽略）：" + $_.Exception.Message) }
  }
}
catch {
  Log ("[FAIL] " + $_.Exception.Message)
  $exitCode = 1
}
finally {
  try {
    $line = [ordered]@{
      ts         = (Get-Date).ToUniversalTime().ToString('o')
      items      = $script:items
      published  = $script:published
      verify_ok  = $script:verifyOk
      exit_code  = $exitCode
      elapsed_s  = [int]((Get-Date) - $script:t0).TotalSeconds
    } | ConvertTo-Json -Compress
    Add-Content -LiteralPath $Metrics -Value $line -Encoding utf8
  } catch { }
  Remove-Item -LiteralPath $Lock -ErrorAction SilentlyContinue
}
exit $exitCode
