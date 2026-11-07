# Seedance（火山方舟）接口要点

核对日期：2026-11-06。来源：火山方舟官方文档「创建视频生成任务 API」和「Seedance 2.0 快速入门」。接口有变化时，以官方文档为准，并更新 `scripts/seedance.py`。

平时用 `scripts/seedance.py`，不要手写请求。本文件用于排错和理解脚本行为。

## 接口

- 创建任务：`POST https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks`
- 查询任务：`GET https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks/{id}`
- 鉴权：`Authorization: Bearer $ARK_API_KEY`。其他地域或代理可设环境变量 `ARK_BASE_URL`。

## 首尾帧请求体

```json
{
  "model": "doubao-seedance-2-0-mini-260615",
  "content": [
    {"type": "text", "text": "<七段式提示词>"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}, "role": "first_frame"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}, "role": "last_frame"}
  ],
  "resolution": "720p",
  "ratio": "16:9",
  "duration": 5,
  "generate_audio": true,
  "watermark": false
}
```

- 首尾帧模式要两张图，`role` 分别是 `first_frame` 和 `last_frame`。只给首帧时，`role` 可省略。
- 首帧、首尾帧、全能参考（`reference_image`）三种模式互斥，不能混用。
- 首尾帧画幅不同时，以首帧为准，尾帧会被居中裁剪。所以提交前要让两张图尺寸一样。

## 图片限制

- `url` 可以是公网 URL、`asset://<ID>`，或 Base64：`data:image/<格式小写>;base64,<数据>`。本地图用 Base64。
- 格式：jpeg、png、webp、bmp、tiff、gif；2.0 起还支持 heic、heif。
- 宽高比（宽/高）0.4–2.5；宽和高各 300–6000 px。
- 单张小于 30 MB；整个请求体小于 64 MB。

## 参数

| 参数 | 说明 |
| --- | --- |
| `resolution` | 480p、720p、1080p、4k。2.0 Fast 和 Mini 只有 480p、720p。 |
| `ratio` | 16:9、4:3、1:1、3:4、9:16、21:9、adaptive。2.x 默认 adaptive。 |
| `duration` | 整数秒。2.0 系列 4–15；2.5 为 4–30，-1 表示由模型决定。 |
| `generate_audio` | 默认 true（2.0、2.5）。 |
| `watermark` | 默认 false。 |
| `return_last_frame` | 默认 false。为 true 时可从查询结果拿到尾帧 JPEG，适合连贯式接戏。 |
| `seed`、`camera_fixed`、`frames` | 文档只列给 1.0 pro 系列。 |
| `callback_url` | 状态变化时回调。 |
| `execution_expires_after` | 任务过期秒数，默认 172800（48 小时）。 |

## 查询结果

- `status`：`queued`、`running`、`succeeded`、`failed`、`expired`。
- 成功后：`content.video_url`；开了 `return_last_frame` 时还有 `content.last_frame_url`。
- `usage.completion_tokens`：按它计费。脚本把它记进 `ledger.jsonl`，便于和账单对账。
- 视频 URL 有有效期（旧版文档写 24 小时）。拿到后马上下载，脚本会自动下载。

## 模型和价格（估算）

| 模型 ID | 说明 | 720p 价格（估算） |
| --- | --- | --- |
| `doubao-seedance-2-5-260628` | 2.5，质量最好 | 约 ¥1.5/秒（Eian 文章） |
| `doubao-seedance-2-0-mini-260615` | 2.0 mini，便宜 | 约 ¥0.5/秒（Eian 文章） |
| `doubao-seedance-2-0-260128` | 2.0 | 未核实，报价时用 `--price-per-sec` 指定 |
| `doubao-seedance-2-0-fast-260128` | 2.0 Fast | 未核实，报价时用 `--price-per-sec` 指定 |

- 价格以火山方舟账单为准。账单和估算差得多时，用 `--price-per-sec` 覆盖。
- 其他分辨率按像素数比例估算（1080p 约是 720p 的 2.25 倍）。这是估算，不是官方价。
- 开通 Seedance 2.0 有门槛（例如账户余额、节省计划或资源包）。被拒时把原始报错告诉用户。

## 报错

- 欠费、余额不足、额度用完：脚本退出码 3。按规矩 7 停下，不充值，先粗剪已有片段。
- 缺 `ARK_API_KEY`：退出码 4。请用户自己设置环境变量。
- 超预算：退出码 5。告诉用户，等他决定。
