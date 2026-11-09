<#
  squash-history.ps1 —— 把仓库历史压成单个提交（一次性瘦身，默认只做演练）

  背景：远程仓库 5.7 GB，全是 10 月前「每 30 分钟提交 13 MB」攒出来的。
  增量已经止住（现在每轮约 400 KB），但历史还压在 clone / Pages 构建 / 镜像同步上。

  安全设计：
    - 默认 DryRun：只算预估体积，不动任何东西
    - 真执行需要同时给 -Execute 和 -ConfirmText SQUASH
    - 默认先做 git bundle 全量备份到 backup\（可用 -SkipBackup 跳过）
    - 失败会保留备份并打印回滚命令

  用法：
    .\squash-history.ps1                                   # 演练
    .\squash-history.ps1 -Execute -ConfirmText SQUASH      # 真执行（含备份）
    .\squash-history.ps1 -Execute -ConfirmText SQUASH -SkipBackup   # 不备份（不推荐）
#>
param(
  [switch]$Execute,
  [string]$ConfirmText = '',
  [switch]$SkipBackup,
  [string]$Proxy = 'http://127.0.0.1:7897'
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = 'E:\WIKI数据库\雷达数据'
$Repo = Join-Path $Root '_repo'
$Bak  = Join-Path $Root 'backup'
$Git  = 'C:\Users\86571\AppData\Local\hermes\tools\git-2.53.0+3-win32-x64\mingw64\bin\git.exe'
if (-not (Test-Path -LiteralPath $Git)) { $Git = 'git.exe' }

if (-not (Test-Path -LiteralPath (Join-Path $Repo '.git'))) { throw "发布仓库不存在：$Repo" }

$commits = [int](& $Git -C $Repo rev-list --count HEAD)
$dotGitMB = [math]::Round((Get-ChildItem -LiteralPath (Join-Path $Repo '.git') -Recurse -File -Force | Measure-Object Length -Sum).Sum / 1MB, 1)

Write-Output "== 现状 =="
Write-Output ("本地提交数      : {0}" -f $commits)
Write-Output ("本地 .git 体积  : {0} MB（shallow clone，不代表服务器 5.7 GB）" -f $dotGitMB)
$remoteSize = (gh.exe api repos/Jackliu-teadrinker/ai-news-radar --jq '.size' 2>$null)
if ($remoteSize) { Write-Output ("服务器仓库体积  : {0:N0} MB" -f ([double]$remoteSize / 1024)) }

Write-Output ""
Write-Output "== 预估 =="
Write-Output "压成单提交后，服务器体积预计降到 5-20 MB 量级（.git 只保留当前树的一份 pack）"
Write-Output "代价：所有历史 commit、issue 里的 commit 引用、旧 permalink 失效"
Write-Output ""

if (-not $Execute -or $ConfirmText -ne 'SQUASH') {
  Write-Output "当前是演练模式，未做任何改动。"
  Write-Output "确认要执行： .\squash-history.ps1 -Execute -ConfirmText SQUASH"
  exit 0
}

if ($commits -le 1) {
  Write-Output "已经只有 1 个提交，无需压缩。"
  exit 0
}

# 原生 git 会把进度（如 "Switched to a new branch"）写到 stderr，
# 在 $ErrorActionPreference='Stop' 下会被当成终止错误 → 后面所有步骤都不执行。
# 从这里开始改回 Continue，改由 $LASTEXITCODE 判断成败。
$ErrorActionPreference = 'Continue'

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $SkipBackup) {
  New-Item -ItemType Directory -Force -Path $Bak | Out-Null
  $bundle = Join-Path $Bak ("repo-full-{0}.bundle" -f $stamp)
  Write-Output "[1/4] 备份全部引用到 bundle（大文件，可能几分钟）..."
  & $Git -c "http.proxy=$Proxy" -c http.version=HTTP/1.1 -C $Repo bundle create $bundle --all
  if ($LASTEXITCODE -ne 0) { throw "备份失败，已中止（未做任何修改）" }
  Write-Output ("      备份：{0}（{1:N1} MB）" -f $bundle, ((Get-Item $bundle).Length / 1MB))
} else {
  Write-Output "[1/4] 已跳过备份（-SkipBackup）"
}

Write-Output "[2/4] 生成孤立提交（当前工作树快照）..."
& $Git -C $Repo checkout -q --orphan "squash-$stamp" 2>$null
& $Git -C $Repo add -A
$msg = "chore: 历史瘦身（单提交重建，原 {0} 个提交已归档）" -f $commits
& $Git -C $Repo -c user.name='radar-local' -c user.email='radar-local@users.noreply.github.com' commit -q -m $msg
if ($LASTEXITCODE -ne 0) { throw "生成孤立提交失败" }

Write-Output "[3/4] 切换 master 指向新提交..."
& $Git -C $Repo branch -M master

Write-Output "[4/4] 强制推送（改写远程历史）..."
$push = & $Git -C $Repo -c "http.proxy=$Proxy" -c http.version=HTTP/1.1 push --force origin master 2>&1
$push | ForEach-Object { Write-Output ("      " + $_) }
if ($LASTEXITCODE -ne 0) {
  Write-Output ""
  Write-Output "推送失败。回滚方式："
  Write-Output ("  git -C `"$Repo`" fetch origin && git -C `"$Repo`" reset --hard origin/master")
  if (-not $SkipBackup) { Write-Output ("  或从备份恢复：git clone `"$bundle`" restored") }
  exit 1
}

Start-Sleep -Seconds 3
$newSize = (gh.exe api repos/Jackliu-teadrinker/ai-news-radar --jq '.size')
Write-Output ""
Write-Output "完成。服务器仓库体积：{0:N0} MB（GitHub 侧 GC 可能需要几分钟到几十分钟才回落）" -f ([double]$newSize / 1024)
Write-Output "验证站点：https://jackliu-teadrinker.github.io/ai-news-radar/"
Write-Output "下一轮计划任务会照常提交（新历史从今天重新开始累积）。"
