/**
 * collect_and_push.js
 * 本地增量采集 → git push → GitHub Actions自动部署
 * 
 * 流程：
 *   1. opml_to_radar_json.js   — 本地抓RSS（使用 Windows 代理）
 *   2. inject_gn_min.js      — 注入 GN 分类
 *   3. git add → commit → push — 推送到 GitHub
 *
 * GitHub Actions 的 update-news.yml 检测到新commit，自动触发 Pages 部署
 *
 * 用法: node collect_and_push.js
 */

const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const RADAR_DIR = 'C:/Users/86571/ai-news-radar';
const PROXY = 'http://127.0.0.1:7897';

function runCmd(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, {
      cwd: opts.cwd || RADAR_DIR,
      stdio: opts.stdio || 'inherit',
      shell: false,
      env: { ...process.env, PROXY },
    });
    const timer = setTimeout(() => { child.kill(); reject(new Error(`timeout: ${cmd}`)); }, 180000);
    child.on('close', code => {
      clearTimeout(timer);
      if (code === 0) resolve(code);
      else reject(new Error(`${cmd} exited ${code}`));
    });
    child.on('error', e => { clearTimeout(timer); reject(e); });
  });
}

function gitCmd(args) {
  const result = spawn('git', args, { cwd: RADAR_DIR, shell: false });
  let out = '';
  result.stdout?.on('data', d => out += d);
  result.stderr?.on('data', d => out += d);
  return new Promise((resolve, reject) => {
    result.on('close', code => resolve({ code, out }));
    result.on('error', reject);
  });
}

async function main() {
  console.log('[collect] 开始本地采集...');
  console.log(`[collect] 目录: ${RADAR_DIR}`);

  // Step 1: 增量采集
  console.log('\n[Step 1] opml_to_radar_json.js (增量采集)...');
  await runCmd('node', ['scripts/opml_to_radar_json.js'], { stdio: 'inherit' });

  // Step 2: 注入 GN 分类
  console.log('\n[Step 2] inject_gn_min.js (GN分类)...');
  await runCmd('node', ['scripts/inject_gn_min.js'], { stdio: 'inherit' });

  // Step 3: git add + commit + push
  console.log('\n[Step 3] git add...');
  const addResult = await gitCmd(['add', 'data/latest-24h-min.json', 'data/latest-24h.json']);
  
  // Check if there are changes
  const diffResult = await gitCmd(['diff', '--cached', '--stat']);
  if (!diffResult.out.trim()) {
    console.log('[collect] 数据无变化，跳过提交');
    return;
  }

  const now = new Date().toISOString();
  console.log('[collect] git commit...');
  const commitResult = await gitCmd([
    '-c', 'user.name=local-collector',
    '-c', 'user.email=local@openclaw',
    'commit', '-m', `ci: local collect ${now}`
  ]);
  if (commitResult.code !== 0) {
    console.error('[collect] commit失败:', commitResult.out);
    return;
  }

  console.log('[collect] git push...');
  const pushResult = await gitCmd(['push', 'origin', 'master']);
  if (pushResult.code !== 0) {
    console.error('[collect] push失败（网络或权限问题）:', pushResult.out);
    return;
  }

  console.log('\n[collect] 完成！GitHub Actions 将自动部署更新的数据。');
}

main().catch(e => {
  console.error('[collect] 错误:', e.message);
  process.exit(1);
});
