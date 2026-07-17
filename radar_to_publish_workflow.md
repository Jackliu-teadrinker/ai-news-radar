# 从雷达到网站：机器人新闻写作发布的完整流程与踩坑实录

> 本文档记录人形机器人/具身智能新闻从雷达采集到网站发布的完整工作流，以及实践中遇到的坑和解决方案。适合媒体编辑、内容运营、技术团队参考。

---

## 一、整体架构

```
RSS 雷达采集 → 数据筛选 → 子智能体写稿 → 配图收集 → 后台发布
     ↓              ↓             ↓            ↓           ↓
 GitHub Actions   JSON 数据    Playwright   图片上传    leader-admin
```

**核心组件：**
- **雷达**：GitHub Actions 定时采集 RSS，输出 curated JSON
- **写稿**：5 个子智能体并行写作，每篇独立文件
- **配图**：loremflickr（免费图）+ 新闻源截图 + 自建图库
- **发布**：Playwright 浏览器自动化操作 leader-admin 后台

---

## 二、雷达数据采集

### 2.1 数据源

```
https://raw.githubusercontent.com/Jackliu-teadrinker/ai-news-radar/master/data/curated/<YYYY-MM-DD>.json
```

**获取最新日期文件列表：**
```bash
curl https://api.github.com/repos/Jackliu-teadrinker/ai-news-radar/contents/data/curated?ref=master
```

### 2.2 数据格式

JSON 数组，每条包含：
- `title`：文章标题
- `description`：摘要
- `url`：原文链接
- `source`：来源
- `tags`：标签数组
- `publish_time`：发布时间

### 2.3 筛选标准

1. **时效性**：优先 24 小时内新闻
2. **相关性**：人形机器人、具身智能、脑机接口优先
3. **质量**：排除股票/ETF/扫地机器人/短快讯
4. **原创性**：排除昨天已发过的选题

---

## 三、写稿流程

### 3.1 子智能体分配

| 主笔 | 风格 | 适用场景 |
|------|------|---------|
| A | 爆款现场感 | 演示/事故/故事 |
| B | 专业大讲堂 | 技术路线争议 |
| C | 锐评毒舌 | PR稿/画饼/争议 |
| D | 论文解读 | arXiv/顶会论文 |
| E | 甲子光年 | 产业叙事/数据驱动 |
| F | 雷锋网 | 技术拆解/产品深挖 |
| G | 晚点科技 | 商业故事/人物决策 |
| H | 量子位 | 论文转化/科技前沿 |
| I | 活动全能 | 主持稿/通稿/致辞 |

### 3.2 写作要求

**必须遵守：**
1. 标题要有冲击力（感叹句/疑问句/数字）
2. 开头场景化，不要平铺直叙
3. 观点前置——每段首句必须是观点句
4. 组合：观点 + 数据 + 案例
5. 禁止虚构引语（用"据XX报道"格式）
6. 禁止使用破折号（—）和引号（""）作为主要标点
7. 长句为主（超过 20 字）
8. 结尾必须回到产业判断（30 字以内）

**文件命名：**
```
<主题>_<风格代号>_<版本>.md
例：比亚迪人形机器人_主笔G_Forbes_v1.md
```

### 3.3 输出目录

```
C:\Users\86571\Desktop\龙虾工作日志\
```

---

## 四、配图处理

### 4.1 封面图要求

**铁律：每篇文章封面图必须不同！**

批量发布时逐篇核查 `img1` 字段，确认不相同后方可提交。

### 4.2 图片来源优先级

1. **原新闻源**：从 Forbes/TechTimes 等下载原始配图
2. **Wikimedia Commons**：CC 协议可商用图片
3. **loremflickr**：免费占位图（关键词精准匹配）
4. **自建图库**：`article_images/` 目录

### 4.3 图片处理

```python
# 推荐尺寸
width = 1024
height = 768
quality = 85
max_kb = 500

# 压缩脚本
from PIL import Image
import io

img = Image.open("input.jpg")
buf = io.BytesIO()
img.save(buf, "JPEG", quality=85)
data = buf.getvalue()

while len(data) > 500*1024:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=q-10)
    data = buf.getvalue()
```

### 4.4 正文配图

正文中插入 `<img>` 标签，确保：
- `src` 是完整的 OSS URL
- `style="max-width:100%;margin:16px 0;"`
- `alt` 描述图片内容

---

## 五、后台发布

### 5.1 平台信息

- **地址**：`http://leader-admin.leaderobot.com:7999/`
- **登录账号**：`devtest / 123123`
- **分类**：newsType=150（科技前沿）
- **标签**：[153, 191]（人形机器人 + 具身智能）

### 5.2 鉴权方式

**正确格式：**
```
Authorization: Bearer <token>
```

**错误格式：**
- `***<token>` ❌
- 裸 token ❌
- `Token <token>` ❌

localStorage 存的是裸 token，前端请求会自动加 `Bearer` 前缀。urllib.request 调用时需显式拼接。

### 5.3 发布步骤

#### Step 1: 登录 & 获取 Token

```python
await page.goto(f"{BASE}/user/login")
await page.fill("input#username", "devtest")
await page.fill("input#password", "123123")
await page.click("button:has-text('登 录')")
await asyncio.sleep(8)
token = await page.evaluate("() => localStorage.getItem('Authorization')")
```

#### Step 2: API 保存文章

```python
headers = {
    "Authorization": "Bearer " + token,
    "Content-Type": "application/json",
    "X-Request-Id": "auto-pub-v2"
}

article = {
    "title": "文章标题",
    "description": "摘要",
    "content": "<p>正文HTML</p>",
    "newsType": 150,
    "img1": "封面图URL",
    "author": "小渊",
    "publishStatus": "DRAFT",
    "tags": [153, 191]
}

req = urllib.request.Request(
    f"{BASE}/api/admin/news/save",
    data=json.dumps(article, ensure_ascii=False).encode("utf-8"),
    headers=headers
)
r = urllib.request.urlopen(req, timeout=10)
result = json.loads(r.read().decode())
article_id = result["data"]["id"]
```

#### Step 3: 点击发布按钮

```python
await page.goto(f"{BASE}/news/list")
# 找到文章行，点击"发布"按钮
# 确认弹窗（Enter 兜底）
```

### 5.4 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| save API 返回 500 | 后端维护 | 暂停发布，等待恢复后重试 |
| 封面图相同 | 批量发布时复用同一张 | 逐篇检查 img1 字段 |
| 正文图片 URL 截断 | CKEditor 转义 HTML | 用 evaluate(innerHTML) 写入 |
| 段落无空行 | HTML 中连续 `<p><p>` | 确保 `</p>\n\n<p>` 结构 |
| 401 Unauthorized | Token 过期或格式错误 | 重新登录，检查 `Bearer` 前缀 |

---

## 六、发布前自检清单

### 6.1 内容检查

- [ ] 标题有冲击力（感叹句/疑问句/数字）
- [ ] 开头场景化，非平铺直叙
- [ ] 每段首句是观点句
- [ ] 包含：观点 + 数据 + 案例
- [ ] 无虚构引语
- [ ] 无破折号（—）和引号（""）
- [ ] 长句为主（超过 20 字）
- [ ] 结尾有产业判断

### 6.2 图片检查

- [ ] 封面图唯一（逐篇核查 img1）
- [ ] 正文配图 URL 完整（无截断）
- [ ] 图片与内容高度相关
- [ ] 图片大小 < 500KB

### 6.3 HTML 检查

- [ ] `<p>` 标签间有空行（`</p>\n\n<p>`）
- [ ] 无连续 `<p><p>` 无间隙
- [ ] 封面图 `img1` 字段非空
- [ ] 分类 `newsType` 正确

### 6.4 发布检查

- [ ] save API 返回 200（非 500）
- [ ] 文章状态为 PUBLISH
- [ ] 前台预览正常显示

---

## 七、踩坑实录

### 7.1 CKEditor 内容注入

**问题**：通过 `evaluate(innerHTML=...)` 注入含 `<img>` 标签的 HTML 时，CKEditor 对 URL 做了实体转义，导致图片 src 被截断。

**解决**：
1. 先用 `evaluate()` 注入纯文本内容
2. 再通过编辑器原生图片上传按钮插入图片
3. 或使用 `keyboard.type()` 分段粘贴

### 7.2 封面图上传

**问题**：Playwright 上传图片后，DOM 中读取到的 OSS URL 始终是旧图。

**原因**：上传组件异步更新，需要等待上传完成后再提取 URL。

**解决**：
```python
await cover_input.set_input_files(img_path)
await asyncio.sleep(6)  # 等待上传完成
oss_url = await page.evaluate("""
    () => {
        const imgs = document.querySelectorAll('img[src*='oss']');
        for(const img of imgs) return img.src;
        return '';
    }
""")
```

### 7.3 API 鉴权格式

**问题**：`Authorization` 头格式错误导致 401。

**发现过程**：
- `***<token>` → 401 ❌
- 裸 token → 401 ❌
- `Bearer <token>` → 200 ✅

**教训**：前端自动加 `Bearer`，但 urllib 需手动拼接。

### 7.4 段落空行约束

**问题**：HTML 中 `<p>` 标签之间没有空行，前台渲染异常。

**正确格式**：
```html
<p>第一段</p>

<p>第二段</p>
```

**错误格式**：
```html
<p>第一段</p><p>第二段</p>
```

---

## 八、自动化脚本

### 8.1 批量发布脚本

```python
# batch_publish.py
import asyncio, json, urllib.request
from playwright.async_api import async_playwright

BASE = "http://leader-admin.leaderobot.com:7999"

ARTICLES = [...]  # 文章列表

async def publish_one(page, api_headers, article):
    # 1. 登录
    # 2. API 保存
    # 3. 点击发布
    # 4. 验证状态
    pass

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await (await browser.new_context()).new_page()
        # ... 登录逻辑
        for article in ARTICLES:
            await publish_one(page, api_headers, article)
        await browser.close()
```

### 8.2 封面图修复脚本

```python
# fix_covers.py
# 用于 save API 恢复后批量更新封面图
for art_id, cover_file in COVER_MAP.items():
    # 1. 打开编辑页
    # 2. 删除旧封面
    # 3. 上传新封面
    # 4. 提取 OSS URL
    # 5. 点击"更 新"按钮
```

---

## 九、最佳实践总结

### 9.1 写作

1. **先诊断再动笔**：确认新闻时效性和独特性
2. **观点先行**：每段首句亮出观点
3. **数据支撑**：用具体数字增强说服力
4. **案例佐证**：每个观点配一个真实案例
5. **产业判断**：结尾回到行业趋势

### 9.2 配图

1. **封面唯一**：绝不重复使用同一张
2. **内容相关**：图片与文章主题高度匹配
3. **格式统一**：1024x768，JPEG，< 500KB
4. **alt 描述**：每张图都有有意义的 alt 文本

### 9.3 发布

1. **API 健康检查**：发布前 ping save API
2. **逐篇验证**：每篇发布后前台预览确认
3. **失败回滚**：发布失败保留草稿，不强行提交
4. **记录日志**：每步操作记录 ID 和时间戳

---

## 十、工具链清单

| 工具 | 用途 | 备注 |
|------|------|------|
| GitHub Actions | RSS 采集 | 定时任务 |
| Playwright | 浏览器自动化 | 登录/上传/发布 |
| urllib.request | API 调用 | save/list/detail |
| PIL/Pillow | 图片处理 | 压缩/格式转换 |
| requests | 网络请求 | 下载新闻配图 |
| loremflickr | 免费占位图 | 关键词搜索 |
| Wikimedia Commons | CC 协议图片 | 需确认版权 |

---

## 附录：快速参考

### 常用命令

```bash
# 本地运行雷达采集
python scripts/update_news.py --output-dir data --window-hours 24

# 启动本地预览
python -m http.server 8080

# 手动触发 GitHub Actions
gh workflow run update-news.yml --repo Jackliu-teadrinker/ai-news-radar
```

### 关键路径

```
雷达数据：data/curated/YYYY-MM-DD.json
写稿目录：龙虾工作日志/*.md
配图目录：龙虾工作日志/article_images_5/
发布脚本：leader-admin-publish/batch_publish*.py
```

### 联系信息

- **雷达仓库**：Jackliu-teadrinker/ai-news-radar
- **后台地址**：leader-admin.leaderobot.com:7999
- **前台地址**：www.leaderobot.com

---

*最后更新：2026-07-17*
*作者：小渊（媒体主编 Jack 的协调者）*
