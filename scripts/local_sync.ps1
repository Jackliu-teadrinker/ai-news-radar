# local_sync.ps1
# 职责：本地工作树与 origin/master 同步（fetch + ff-only pull）。
# 铁律（SOUL）：
#   - 路径辨识：Test-Path .git 必须 True，否则硬退出（避免操作孤儿目录）
#   - 禁止 print("OK") 不检查 returncode：每步 git 命令都必检 $LASTEXITCODE
#   - 禁止 push：本脚本只拉不推
#   - 禁止 reset --hard / rebase：只允许 ff-only
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\local_sync.ps1
# 退出码：
#   0 = OK（已同步，drift = 0）
#   2 = WARN（已同步但 drift > 10 commit）
#   3 = FAIL（路径错 / fetch 失败 / pull 非 fast-forward / drift > fail）

[CmdletBinding()]
param(
    [string]$RepoDir = "C:\Users\86571\ai-news-radar-gh",
    [int]$WarnThreshold = 10,
    [int]$FailThreshold = 50
)

# 注意：不用 Stop，否则 git 的 stderr 写入会让脚本异常终止。
$ErrorActionPreference = "Continue"
$ts = (Get-Date).ToString("o")

function Write-Status {
    param([string]$Status, [string]$LocalSha, [string]$OriginSha, [int]$Drift, [string]$Message)
    $json = "{`"ts`":`"$ts`",`"local_sha`":`"$LocalSha`",`"origin_sha`":`"$OriginSha`",`"drift_commits`":$Drift,`"status`":`"$Status`",`"msg`":`"$Message`"}"
    Write-Host "[$ts] $Message"
    Write-Host $json
}

# ---------- 1. 路径辨识铁律 ----------
if (-not (Test-Path $RepoDir)) {
    Write-Status -Status "FAIL" -LocalSha "" -OriginSha "" -Drift 0 -Message "repo dir not found: $RepoDir"
    exit 3
}
if (-not (Test-Path (Join-Path $RepoDir ".git"))) {
    Write-Status -Status "FAIL" -LocalSha "" -OriginSha "" -Drift 0 -Message "not a git repo (no .git): $RepoDir. HINT: orphan dir C:\Users\86571\ai-news-radar\ is FORBIDDEN."
    exit 3
}

Push-Location $RepoDir
try {
    # ---------- 2. fetch ----------
    # 用 *>&1 重定向所有流到 stdout，避免触发 PowerShell stderr 误判
    $fetchOut = git fetch origin master *>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Status "FAIL" -LocalSha "" -OriginSha "" -Drift 0 -Message "git fetch origin master failed (exit=$LASTEXITCODE): $fetchOut"
        exit 3
    }

    # ---------- 3. 拿 SHA ----------
    $originSha = (git rev-parse origin/master).Trim()
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Status "FAIL" -LocalSha "" -OriginSha "" -Drift 0 -Message "git rev-parse origin/master failed"
        exit 3
    }

    $localSha = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Status "FAIL" -LocalSha "" -OriginSha "" -Drift 0 -Message "git rev-parse HEAD failed"
        exit 3
    }

    # ---------- 4. 是否已经最新 ----------
    if ($localSha -eq $originSha) {
        Write-Status -Status "OK" -LocalSha $localSha -OriginSha $originSha -Drift 0 -Message "already up-to-date"
        exit 0
    }

    # ---------- 5. ff-only pull ----------
    $pullOut = git pull --ff-only origin master *>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Status "FAIL" -LocalSha $localSha -OriginSha $originSha -Drift 0 -Message "git pull --ff-only failed (exit=$LASTEXITCODE). Local has likely diverged. Output: $pullOut"
        exit 3
    }

    # ---------- 6. drift 检查 ----------
    $newLocalSha = (git rev-parse HEAD).Trim()
    $driftRaw = git rev-list --left-right --count origin/master...HEAD
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Status "FAIL" -LocalSha $newLocalSha -OriginSha $originSha -Drift 0 -Message "git rev-list failed"
        exit 3
    }

    $parts = $driftRaw -split "\s+"
    # git rev-list --left-right --count origin/master...HEAD:
    #   left  = commits in origin/master NOT in HEAD  (LOCAL BEHIND origin)
    #   right = commits in HEAD NOT in origin/master  (LOCAL AHEAD of origin)
    # Jack 2026-06-22: bug fix — was reading parts[1] (right = local ahead),
    # using it as "$behind" was inverted. Correct: parts[0] = local behind origin.
    $behind = [int]$parts[0]
    $ahead = [int]$parts[1]   # tracked separately for clarity (unused below)

    if ($ahead -gt 0) {
        # Local has commits origin doesn't — divergent state, manual intervention required.
        Write-Status -Status "FAIL" -LocalSha $newLocalSha -OriginSha $originSha -Drift $ahead -Message "local is $ahead commit(s) AHEAD of origin — divergent, refusing auto-sync. Manual intervention required."
        exit 3
    }
    if ($behind -gt $FailThreshold) {
        Write-Status -Status "FAIL" -LocalSha $newLocalSha -OriginSha $originSha -Drift $behind -Message "drift=$behind exceeds fail threshold ($FailThreshold)"
        exit 3
    }
    elseif ($behind -gt $WarnThreshold) {
        Write-Status -Status "WARN" -LocalSha $newLocalSha -OriginSha $originSha -Drift $behind -Message "drift=$behind exceeds warn threshold ($WarnThreshold)"
        exit 2
    }
    else {
        Write-Status -Status "OK" -LocalSha $newLocalSha -OriginSha $originSha -Drift $behind -Message "pulled, drift=$behind"
        exit 0
    }
}
finally {
    Pop-Location
}
