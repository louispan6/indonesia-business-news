# GitHub Pages 上线指南

目标：把本目录发布成一个公开资讯网站，并让 GitHub Actions 每天北京时间 10:00 自动生成新文章。

## 1. 准备上传的文件

上传 `openclaw_id_news/` 目录里的项目文件，但不要上传这些内容：

- `.env`
- `.venv/`
- `__pycache__/`
- `outputs/`

必须包含这些文件和目录：

- `_config.yml`
- `index.md`
- `about.md`
- `main.py`
- `requirements.txt`
- `.env.example`
- `.github/workflows/daily_news.yml`
- `_posts/`，首次没有文章也没关系，脚本会自动创建

## 2. 在 GitHub 网站新建仓库

1. 打开 `https://github.com` 并登录。
2. 点击右上角 `+`。
3. 点击 `New repository`。
4. `Repository name` 填一个仓库名，例如 `indonesia-business-news`。
5. 选择 `Public`，这样 GitHub Pages 可以公开访问。
6. 不要勾选添加 `.gitignore`、license 或 README，避免和本地文件冲突。
7. 点击 `Create repository`。

## 3. 上传代码

推荐使用命令行上传，最稳：

```bash
cd /mnt/d/sister/openclaw_id_news
git init
git add .
git commit -m "init: launch Indonesia business news site"
git branch -M main
git remote add origin https://github.com/你的用户名/indonesia-business-news.git
git push -u origin main
```

如果你只想用 GitHub 网页上传：

1. 进入刚创建的仓库。
2. 点击 `uploading an existing file`。
3. 拖入项目文件，注意不要拖入 `.env`、`.venv/`、`outputs/`。
4. 对 `.github/workflows/daily_news.yml`，如果网页拖拽没有成功创建隐藏目录，就点击 `Add file` -> `Create new file`。
5. 文件名输入 `.github/workflows/daily_news.yml`。
6. 粘贴本地同名文件内容。
7. 点击 `Commit changes`。

## 4. 开启 GitHub Pages

1. 进入仓库页面。
2. 点击 `Settings`。
3. 左侧点击 `Pages`。
4. 在 `Build and deployment` 里，`Source` 选择 `Deploy from a branch`。
5. `Branch` 选择 `main`。
6. 文件夹选择 `/ (root)`。
7. 点击 `Save`。
8. 等 1-10 分钟，页面会显示公开访问地址，通常是：

```text
https://你的用户名.github.io/indonesia-business-news/
```

如果仓库名是 `你的用户名.github.io`，网址会是：

```text
https://你的用户名.github.io/
```

## 5. 配置 DeepSeek API Key

1. 进入仓库页面。
2. 点击 `Settings`。
3. 左侧点击 `Secrets and variables`。
4. 点击 `Actions`。
5. 点击 `New repository secret`。
6. `Name` 填：

```text
DEEPSEEK_API_KEY
```

7. `Secret` 填你的 DeepSeek API Key，不要加引号。
8. 点击 `Add secret`。

## 6. 手动测试自动化

1. 进入仓库页面。
2. 点击 `Actions`。
3. 左侧选择 `Daily Indonesia Business News`。
4. 点击 `Run workflow`。
5. Branch 选择 `main`。
6. 再点击绿色的 `Run workflow`。
7. 等运行完成后，回到 `Code` 页面，确认 `_posts/` 下生成了今天的文章。
8. 等 GitHub Pages 重新部署完成，刷新公开网址即可看到最新简报。

## 7. 自动更新时间

工作流 cron 是：

```yaml
cron: "0 2 * * *"
```

GitHub Actions 的 cron 使用 UTC 时间。北京时间 UTC+8，所以 UTC 02:00 对应北京时间 10:00。

GitHub 的定时任务可能会有几分钟延迟，这是正常现象。
