# 安装教程

有三种装法，选一种就行。没用过命令行的选方法一或方法二。

Claude 的菜单名称会随版本更新变化。下面的路径对不上时，以 [Claude 官方帮助文档](https://support.claude.com/en/articles/12512180-using-skills-in-claude) 为准。

## 第 0 步：下载安装包

打开 [Releases 页面](https://github.com/xinxu23/short-video-remake/releases)，在最新版本下面点 `short-video-remake.skill` 下载。

## 方法一：在 Claude 设置里上传（网页版、桌面版通用）

1. 打开 Claude，进入 **设置（Settings）→ 功能（Capabilities）**。
2. 打开 **代码执行和文件创建（Code execution and file creation）**。Skills 依赖这个功能，不开就找不到上传入口。
3. 在同一页找到 **Skills**，点 **上传（Upload skill）**，选择刚下载的文件。
4. 上传后确认 short-video-remake 旁边的开关是打开的。
5. 新开一个对话，说「拆解这条视频」并上传一个 mp4，测试是否生效。

**上传框不认 .skill 文件？** 把文件后缀从 `.skill` 改成 `.zip` 再上传。这个文件本身就是 zip 压缩包，改名不影响内容。

**团队版或企业版账号找不到 Skills？** 需要管理员先在组织设置里开启。

## 方法二：在 Claude 桌面版对话里装

1. 在 Claude 桌面版新开一个对话，把 `short-video-remake.skill` 拖进对话框。
2. 发送「帮我安装这个 skill」。
3. Claude 会显示一张文件卡片，点卡片上的 **Save skill**。

## 方法三：Claude Code（会用终端的人）

```bash
git clone https://github.com/xinxu23/short-video-remake.git ~/.claude/skills/short-video-remake
```

这种方式的渲染在你自己电脑上运行，需要先装好依赖：

```bash
brew install ffmpeg                      # Mac；Windows 用户从 ffmpeg.org 下载
pip install -r ~/.claude/skills/short-video-remake/requirements.txt
```

## 不用 Claude，直接跑渲染器

只需要「口播视频 → 成片」这一步的话，不装 Skill 也能用，但需要自己写 `timeline.json`：

```bash
git clone https://github.com/xinxu23/short-video-remake.git
cd short-video-remake
pip install -r requirements.txt
cd examples/demo
python ../../scripts/render.py timeline.json
```

## 常见问题

**装好了，但 Claude 没按这个流程走？**
对话里说得明确一点，比如「用 short-video-remake 拆解这条视频」。

**渲染时提示找不到 ffmpeg？**
在 Claude 对话里可以让它先安装 ffmpeg。装不上的话，改用方法三在自己电脑上运行。

**成片里的中文显示成方块？**
电脑上缺中文字体。在 `timeline.json` 的 `style.fonts` 里指定一个字体文件路径，Mac 可以用 `/System/Library/Fonts/PingFang.ttc`。

**能处理 Vlog、多段素材吗？**
目前不行。它适合单机位口播加截图的视频。多段素材请先在剪映里剪成一条完整口播，再交给它包装。
