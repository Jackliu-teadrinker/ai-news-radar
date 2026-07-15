# check_local_drift.ps1
# 沙盒检查：只读，不修改任何状态。
# 用途：看一眼本地 vs origin 的 drift 状态，决定要不要跑 local_sync.ps1。
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\check_local_drift.ps1
# 退出码：
#   0 = OK（drift = 0 或 < warn）
#   2 = WARN（drift > warn 但 < fail）
#   3 = FAIL（drift > fail 或路径错）

[CmdletBinding()]
param(
    [string]$RepoDir = "C:\Users\86571\ai-news-radar-gh",
    [int]$WarnThreshold = 10,
    [int]$FailThreshold = 50
)

$ErrorActionPreference = "Continue"
$ts = (Get-Date).ToString("o")

# ---------- 路径辨识铁律 ----------
if (-not (Test-Path $RepoDir)) {
    Write-Host "[$ts] FAIL: repo dir not found: $RepoDir"
    exit 3
}
if (-not (Test-Path (Join-Path $RepoDir ".git"))) {
    Write-Host "[$ts] FAIL: not a git repo (no .git): $RepoDir"
    Write-Host "[$ts] HINT: orphan dir C:\Users\86571\ai-news-radar\ is FORBIDDEN."
    exit 3
}

Push-Location $RepoDir
try {
    # ---------- 静默 fetch（只读，不 pull） ----------
    $fetchOut = git fetch origin master *>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[$ts] FAIL: git fetch failed (exit=$LASTEXITCODE): $fetchOut"
        exit 3
    }

    $localSha = (git rev-parse HEAD).Trim()
    $originSha = (git rev-parse origin/master).Trim()

    $localShort = $localSha.Substring(0, 7)
    $originShort = $originSha.Substring(0, 7)

    # ---------- 脏工作区检查 ----------
    $dirty = git status --porcelain

    # ---------- drift 计算 ----------
    $driftRaw = git rev-list --left-right --count origin/master...HEAD
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[$ts] FAIL: git rev-list failed"
        exit 3
    }
    $parts = $driftRaw -split "\s+"
    # git rev-list --left-right --count origin/master...HEAD:
    #   left  = commits in origin/master NOT in HEAD  (LOCAL BEHIND origin)
    #   right = commits in HEAD NOT in origin/master  (LOCAL AHEAD of origin)
    # Jack 2026-06-22: bug fix — was reading parts[0]/[1] as ahead/behind
    # (inverted). Correct: parts[0] = local behind, parts[1] = local ahead.
    $behind = [int]$parts[0]
    $ahead = [int]$parts[1]   # tracked separately for clarity (currently unused for status)

    # ---------- 状态判断 ----------
    $status = "OK"
    $exitCode = 0
    if ($ahead -gt 0) {
        # Local has commits origin doesn't — divergent state, fail so caller notices.
        $status = "FAIL"
        $exitCode = 3
    }
    elseif ($behind -gt $FailThreshold) {
        $status = "FAIL"
        $exitCode = 3
    }
    elseif ($behind -gt $WarnThreshold) {
        $status = "WARN"
        $exitCode = 2
    }

    # ---------- 格式化输出 ----------
    Write-Host "========================================"
    Write-Host " Local Drift Report @ $ts"
    Write-Host "========================================"
    Write-Host " Repo:         $RepoDir"
    Write-Host " Local HEAD:   $localShort"
    Write-Host " Origin HEAD:  $originShort"
    Write-Host " Drift:        $behind commit(s) behind, $ahead commit(s) ahead"
    Write-Host " Status:       $status"
    if ($dirty) {
        Write-Host " Working tree: DIRTY"
    } else {
        Write-Host " Working tree: CLEAN"
    }
    Write-Host "========================================"

    $json = "{`"ts`":`"$ts`",`"local_sha`":`"$localShort`",`"origin_sha`":`"$originShort`",`"drift_behind`":$behind,`"drift_ahead`":$ahead,`"dirty`":$([bool]$dirty),`"status`":`"$status`"}"
    Write-Host $json

    exit $exitCode
}
finally {
    Pop-Location
}
