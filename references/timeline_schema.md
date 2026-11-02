# timeline.json 写法

```json
{
  "video": "talk.mp4",            // 口播主视频（相对 timeline.json 的路径）
  "srt": "talk.srt",              // 剪映导出的字幕，可选
  "output": "final.mp4",
  "trim": [0.5, 62.0],            // 可选，只用素材的这一段（秒）
  "highlight": ["十倍", "扣一"],   // 字幕里要变黄的关键词
  "style": { ... },               // 可选，见下方
  "events": [ ... ]
}
```

## 事件通用字段

| 字段 | 说明 |
|---|---|
| `type` | title / badges / tool / pip / bigtext / zoom / flash / sfx |
| `start` 或 `at` | 开始秒数 |
| `cue` | 用字幕关键词定位开始时间（与 start 二选一，推荐） |
| `offset` | 在 cue 定位基础上再偏移的秒数，可为负 |
| `end` / `dur` / `until` | 结束：秒数 / 持续时长 / 下一句含该关键词的字幕开始时 |
| `anim` | 覆盖入场动画：pop / rise / slide / cut |
| `sfx` | 覆盖音效：whoosh / pop / ding / click / none / 自定义音频文件路径 |
| `y_offset` | 竖向微调，画面高度比例，如 -0.03 |

## 各类型字段

**title**：`lines` 多行文字、`sizes` 每行字号（1080宽基准）、`sub` 小字、`sub_size`、`color`、`font`(serif/sans)

**badges**：`items: [{name, value, avatar, color, initial, bg}]`、`stagger` 错峰间隔(默认0.35s)

**tool**：`name`、`icon`（PNG路径，可省）、`color` 和 `initial`（无图标时生成）、`icon_size`(默认150)、`desc` 可选一行说明

**pip**：`image` 或 `video`、`width`（画面宽度比例，默认0.62）、`aspect`（高/宽，默认0.62）、`label` 下方标签、`border`、`border_color`、`scroll`（长图是否滚动，默认 true）。长截图自动从上往下滚动，普通图慢推，视频从头播放（无声）。

**bigtext**：`text`、`size`(默认120)、`color`

**zoom**：`scale`(默认1.15)、`mode`：`punch` 瞬间切近景 / `push` 平滑推近

**flash**：`dur`(默认0.25)、`color`

**sfx**：`sound` 单独放一个音效

## style

```json
{
  "width": 1080, "height": 1920, "fps": 30,
  "cream": "#F8EDC9",            // 标题/工具名颜色
  "top_y": 0.19,                 // 顶部包装区中心位置
  "zoom_center": [0.5, 0.40],    // 推镜中心（人脸位置）
  "auto_punch": {"every_cues": 2, "scale": 1.12},   // 每2句字幕切一次景别
  "caption": {"size": 64, "y": 0.66, "max_chars": 12, "highlight": "#FFD54A", "enabled": true},
  "text_stroke": 3,              // 标题描边，浅色背景下保证可读
  "sfx_volume": 0.55,
  "bgm": "bgm.mp3", "bgm_volume": 0.10,
  "fonts": {"serif": "/path/font.ttf", "sans": "/path/font.ttf"},
  "crf": 20, "preset": "medium"
}
```
