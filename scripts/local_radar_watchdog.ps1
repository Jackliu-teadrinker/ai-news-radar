# local_radar_watchdog.ps1
# 职责：本地 watchdog——在 GH Actions 调度失灵时，主动检查并触发 radar。
# 设计目标：本地不依赖 gh CLI / GH Actions scheduler,走 git push + on:push 触发。
#
# 铁律(SOUL):
#   - 路径辨识:Test-Path .git 必须 True(避免操作孤儿目录 C:\Users\86571\ai-news-radar\)
#   - 禁止 print("OK") 不检查 returncode:每步 git 命令都必检 $LASTEXITCODE
#   - 所有 push 必须独立 API 验证(不能信 git push 的退出码)
#   - 所有错误显式退出,不能 silent fail
#   - 跑完必须输出结构化 JSON 行
#
# 触发节奏(由 OpenClaw cron 决定):
#   - 10min / 30min / 1h 均可,推荐 30min
#   - 脚本本身有"age 阈值"控制是否实际 push
#
# 退出码:
#   0 = OK(无需 push,数据新鲜)
#   1 = FAIL(路径错 / fetch 失败 / push 失败 / 验证失败)
#   2 = RECOVERED(本次 push 成功触发,数据恢复中)
#   3 = CRITICAL(age > 6h,严重告警,已写日志待 Jack 查)

[CmdletBinding()]
param(
    [string]$RepoDir = "C:\Users\86571\ai-news-radar-gh",
    [int]$RecoverThresholdMin = 90,    # 超过此分钟数触发空 commit + push
    [int]$CriticalThresholdMin = 360,  # 超过此分钟数记 CRITICAL(只日志,不自动 push,避免污染)
    [string]$GitName = "radar-local-watchdog",
    [string]$GitEmail = "865715887@qq.com"
)

$ErrorActionPreference = "Continue"
$ts = (Get-Date).ToString("o")

function Write-Status {
    param(
        [string]$Status,
        [string]$Action,
        [string]$LocalSha,
        [string]$OriginSha,
        [int]$AgeMin,
        [string]$Message,
        [string]$PushSha = ""
    )
    $obj = @{
        ts = $ts
        status = $Status
        action = $Action
        local_sha = $LocalSha
        origin_sha = $OriginSha
        age_min = $AgeMin
        msg = $Message
        push_sha = $PushSha
    }
    $json = $obj | ConvertTo-Json -Compress
    Write-Host "[$ts] [$Status/$Action] $Message (age=${AgeMin}min)"
    Write-Host $json
}

# ---------- 1. 路径辨识铁律 ----------
if (-not (Test-Path $RepoDir)) {
    Write-Status -Status "FAIL" -Action "path_check" -LocalSha "" -OriginSha "" -AgeMin 0 -Message "repo dir not found: $RepoDir"
    exit 1
}
if (-not (Test-Path (Join-Path $RepoDir ".git"))) {
    Write-Status -Status "FAIL" -Action "path_check" -LocalSha "" -OriginSha "" -AgeMin 0 -Message "not a git repo (no .git): $RepoDir. HINT: orphan dir C:\Users\86571\ai-news-radar\ is FORBIDDEN."
    exit 1
}

Push-Location $RepoDir
try {
    # ---------- 2. fetch origin master ----------
    $fetchOut = git fetch origin master *>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Status "FAIL" -Action "fetch" -LocalSha "" -OriginSha "" -AgeMin 0 -Message "git fetch origin master failed (exit=$LASTEXITCODE): $fetchOut"
        exit 1
    }

    # ---------- 3. 拿 SHA ----------
    $originSha = (git rev-parse origin/master).Trim()
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Status "FAIL" -Action "rev_parse_origin" -LocalSha "" -OriginSha "" -AgeMin 0 -Message "git rev-parse origin/master failed"
        exit 1
    }

    $localSha = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Status "FAIL" -Action "rev_parse_head" -LocalSha "" -OriginSha "" -AgeMin 0 -Message "git rev-parse HEAD failed"
        exit 1
    }

    # ---------- 4. 算 age (用 origin/master commit 时间) ----------
    # 用 commit 时间而不是 generated_at 是因为 git 永远能查到,data 文件可能缺失
    $commitTimeStr = (git log -1 --format="%ci" origin/master).Trim()
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Status "FAIL" -Action "log_origin" -LocalSha $localSha -OriginSha $originSha -AgeMin 0 -Message "git log origin/master failed"
        exit 1
    }
    try {
        $commitTime = [DateTime]::Parse($commitTimeStr).ToUniversalTime()
    } catch {
        Write-Status -Status "FAIL" -Action "parse_time" -LocalSha $localSha -OriginSha $originSha -AgeMin 0 -Message "failed to parse commit time: $commitTimeStr"
        exit 1
    }
    $now = [DateTime]::UtcNow
    $ageMin = [int]([Math]::Floor(($now - $commitTime).TotalMinutes))

    # ---------- 5. 本地 vs origin drift 检查 ----------
    $driftRaw = git rev-list --left-right --count origin/master...HEAD
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Status "FAIL" -Action "rev_list" -LocalSha $localSha -OriginSha $originSha -AgeMin $ageMin -Message "git rev-list failed"
        exit 1
    }
    $parts = $driftRaw -split "\s+"
    # git rev-list --left-right origin/master...HEAD:
    #   left  = commits in origin/master NOT in HEAD  (origin ahead of local = LOCAL IS BEHIND)
    #   right = commits in HEAD NOT in origin/master  (HEAD ahead of origin = LOCAL IS AHEAD)
    $localBehind = [int]$parts[0]
    $localAhead = [int]$parts[1]

    if ($localAhead -gt 0) {
        # 本地比 origin 多 commit,这是异常状态(不应该有 local commits)
        Write-Status -Status "FAIL" -Action "drift_ahead" -LocalSha $localSha -OriginSha $originSha -AgeMin $ageMin -Message "local is $localAhead commit(s) ahead of origin — UNEXPECTED, manual intervention required"
        exit 1
    }
    if ($localBehind -gt 0) {
        # 本地落后,先拉平(fast-forward only)
        $pullOut = git pull --ff-only origin master *>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Status -Status "FAIL" -Action "pull_ff" -LocalSha $localSha -OriginSha $originSha -AgeMin $ageMin -Message "git pull --ff-only failed (exit=$LASTEXITCODE): $pullOut"
            exit 1
        }
        $localSha = (git rev-parse HEAD).Trim()
    }

    # ---------- 6. 决策:是否触发 ----------
    if ($ageMin -le $RecoverThresholdMin) {
        # 数据新鲜,无需动作
        Write-Status -Status "OK" -Action "no_op" -LocalSha $localSha -OriginSha $originSha -AgeMin $ageMin -Message "data fresh, no action needed"
        exit 0
    }

    if ($ageMin -ge $CriticalThresholdMin) {
        # 太老了,不自动 push(避免污染),只记 CRITICAL 日志
        Write-Status -Status "CRITICAL" -Action "log_only" -LocalSha $localSha -OriginSha $originSha -AgeMin $ageMin -Message "age=$ageMin min exceeds critical threshold ($CriticalThresholdMin), NOT auto-pushing to avoid pollution. Manual intervention required."
        # 仍写一行 alert 到 console,便于 cron 邮件/通知捞
        Write-Host "ALERT: radar appears stuck for $ageMin minutes. Last commit: $originSha"
        exit 3
    }

    # ---------- 7. age 在 [90, 360):触发空 commit + push ----------
    # 检查 working tree 干净(空 commit 也要干净)
    # 用 --porcelain 但忽略 untracked files(?前缀)— untracked 不影响空 commit
    # 只关心 modified(M)、staged(A/M)、deleted(D)这些真正会污染 commit 的
    $dirty = git status --porcelain | Where-Object { $_ -notmatch '^\?\?' }
    if ($dirty) {
        Write-Status -Status "FAIL" -Action "dirty_tree" -LocalSha $localSha -OriginSha $originSha -AgeMin $ageMin -Message "working tree has tracked-file changes, refusing empty commit. Status: $dirty"
        exit 1
    }

    # 设置 git author
    git config user.name $GitName *>&1 | Out-Null
    git config user.email $GitEmail *>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Status "FAIL" -Action "git_config" -LocalSha $localSha -OriginSha $originSha -AgeMin $ageMin -Message "git config failed"
        exit 1
    }

    # 空 commit
    $commitMsg = "radar-local-watchdog: age=${ageMin}min exceeds ${RecoverThresholdMin}min, triggering on:push (2026-06-15 13:30 CST infra)"
    $commitOut = git commit --allow-empty -m $commitMsg *>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Status "FAIL" -Action "empty_commit" -LocalSha $localSha -OriginSha $originSha -AgeMin $ageMin -Message "git commit --allow-empty failed (exit=$LASTEXITCODE): $commitOut"
        exit 1
    }

    $newLocalSha = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Status "FAIL" -Action "rev_parse_new" -LocalSha $newLocalSha -OriginSha $originSha -AgeMin $ageMin -Message "git rev-parse HEAD (after commit) failed"
        exit 1
    }

    # push(走 Windows Credential Manager 凭证,不走 gh keyring)
    $pushOut = git push origin master *>&1
    if ($LASTEXITCODE -ne 0) {
        # push 失败,回滚 commit
        git reset --hard HEAD~1 *>&1 | Out-Null
        Write-Status -Status "FAIL" -Action "push" -LocalSha $newLocalSha -OriginSha $originSha -AgeMin $ageMin -Message "git push failed (exit=$LASTEXITCODE), commit rolled back. Output: $pushOut"
        exit 1
    }

    # ---------- 8. 独立 API 验证 push 成功 ----------
    # 不能信 git push 的退出码,必须 query 一次 origin/master
    Start-Sleep -Seconds 2  # 给 GH 一点时间消化
    $verifyOut = git ls-remote origin master *>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Status "FAIL" -Action "verify_remote" -LocalSha $newLocalSha -OriginSha $originSha -AgeMin $ageMin -Message "git ls-remote failed (exit=$LASTEXITCODE): $verifyOut"
        exit 1
    }
    # ls-remote 输出格式: "<sha>\t<ref>"
    $remoteSha = ($verifyOut -split "\s+")[0].Trim()
    if ($remoteSha -ne $newLocalSha) {
        Write-Status -Status "FAIL" -Action "verify_mismatch" -LocalSha $newLocalSha -OriginSha $remoteSha -AgeMin $ageMin -Message "local=$newLocalSha but remote=$remoteSha — push did NOT land. CRITICAL: GH may have rejected or still propagating."
        exit 1
    }

    # ---------- 9. 成功 ----------
    Write-Status -Status "RECOVERED" -Action "empty_commit_pushed" -LocalSha $newLocalSha -OriginSha $remoteSha -AgeMin $ageMin -Message "empty commit pushed, on:push should trigger Update AI News Radar within seconds" -PushSha $newLocalSha
    exit 2
}
finally {
    Pop-Location
}
