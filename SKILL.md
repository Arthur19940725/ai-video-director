---
name: ai-video-director
description: >-
  AI 生成视频的总导演流程：从一个想法到成片。按步骤完成故事、分镜与配色、画风设定图、每镜首尾帧、七段式视频提示词、Seedance（火山方舟）首尾帧图生视频、ffmpeg 后期和全片复核。
  每次花钱前都先由独立审核 agent 挑错，并请用户批准报价，用最少的钱和最低的抽卡率出片。
  用户想用 AI 做短片、动画短片、剧情视频、MV、广告片，或提到 Seedance、豆包视频、首尾帧、分镜、抽卡、AI 视频提示词、图生视频，或想让 Claude/Codex 当导演、调用 Codex 画图再交给视频模型时，使用本 Skill。
  即使用户没有点名 Seedance，只要用生成式视频模型拍片，也使用本 Skill。
  Directs AI-generated short films end to end (story → storyboard → keyframes → Seedance image-to-video → ffmpeg post), with review gates before every paid step.
  Not for films rendered purely in code (Blender, Remotion, HTML), and not for plain editing of existing footage.
metadata:
  source: https://x.com/EianLu/status/2118317430665613741
  source-title: "Claude code/Codex+Seedance AI视频：从一个想法到成片的全流程（Eian, 2026-11-05）"
---

# AI 视频总导演

你是这支短片的总导演，全程负责。用户只和你沟通，不需要切窗口或复制粘贴。
本流程来自 Eian 的文章（见 frontmatter `source`）。提示词模板原文在 `references/prompts.md`。

## 核心原则：把错误挡在花钱之前

成本一级比一级高：改几个字的提示词几乎免费，重画一张图很便宜，重新生成视频却按秒付钱。

- 文字里能发现的错，不留到图上。
- 图上能发现的错，不留到视频上。

下面每一道审核和确认，都为这个原则服务。进度再急，也不要跳过。

## 分工

| 角色 | 负责 |
| --- | --- |
| 用户 | 选方向、确认画风、批准花钱；看动态、听声音 |
| 你（导演） | 写故事和分镜，写所有提示词，调用其他模型，抽帧放大检查每张图和每段视频，用 ffmpeg 和 Python 做后期 |
| 画师 | 画设定图、样帧和每个镜头的首尾帧。你不自己画。 |
| Seedance（动画师） | 把首尾帧变成几秒钟的视频 |
| 审核 agent | 新开、不带你上下文的 agent。只挑错，不改文件。 |

**选画师**：按顺序取第一个可用的。

1. 你自己就是 Codex：用你自己的生图工具。
2. 本机有 `codex` CLI：用 `scripts/codex_image.py`（见「脚本」）。
3. 宿主有原生生图工具（例如 Antigravity 的图像生成），或已安装生图 Skill：用它，并按命名规则把图存进项目。
4. 都没有：告诉用户，停在写好提示词的阶段。

## 开工前

1. **一次问完**：片长、画幅（16:9 或 9:16）、总预算（人民币）、要不要配乐和字幕、有没有参考片或参考图。
2. **查环境**：运行 `python scripts/doctor.py`，把缺的东西告诉用户。
   - 缺 `ARK_API_KEY` 时，请用户自己到火山方舟控制台申请 API key、开通 Seedance 模型，再设成环境变量（PowerShell：`[Environment]::SetEnvironmentVariable('ARK_API_KEY','<key>','User')`，然后重开终端）。
   - 不要让用户把 key 贴进对话。不要打印 key。
3. **建项目文件夹**：所有文件都放在一个新文件夹里（结构见「项目文件」）。
4. **记预算**：`python scripts/seedance.py budget --project <项目> --set <金额>`。没有预算，脚本拒绝提交。

## 七条规矩

1. 用户确认故事前，不画任何图。
2. 用户确认画风前，不画正式镜头。
3. 提交视频生成前，必须依次满足三点：独立审核 agent 写了「通过」，你给用户报了价，用户同意了。缺一点就不提交。
4. 视频有问题时，按这个顺序处理：能剪掉就剪；剪不掉就用代码修；修不了才重拍，而且只重拍这一镜。重拍前先改提示词或首尾帧，否则原样再拍大概率还是错。
5. 新版本存新文件（`_v2`、`_v3`），不覆盖、不删除旧文件。重拍的新片段不一定更好，最后一起挑。
6. 你看不到真正的动态，也听不到声音。只看过抽帧的内容，要明确说「只看了抽帧」；声音一律请用户听。
7. 不充值，不买额度（Seedance 和 Codex 都一样）。接口返回欠费或额度用完就停，先把已有片段粗剪给用户看。

## 流程

每一步都写明产出和闸门。闸门没过，不进下一步。模板编号（P1–P9）对应 `references/prompts.md`。

### 1. 故事

1. 和用户聊，把想法完善成完整故事。用 **P1**。首选片段式结构：镜头之间不用接戏，最稳。连贯式最容易穿帮，用户要求才用。
2. 好故事要过五条标准：符合现实逻辑；一句话说清想表达什么；开头就抓人；旁人反应像真人（问题 → 主角怎么解决 → 旁人什么反应，反应有先后）；AI 拍得出来（避开 `references/pitfalls.md` 里的弱点）。
3. 定稿后新开审核 agent，用 **P2**，只给它故事文件。
4. 按审核意见改，再请用户确认。

产出：`story/story_vN.md`、`reviews/story_review_vN.md`。闸门：审核通过，用户确认故事。

### 2. 分镜和配色

1. 用 **P3** 写分镜表。每镜写清：片中时间、生成秒数（向上取整，多留 0.5 秒）、景别、机位、运镜、谁往哪走（写画面左右）、靠什么表情推进、什么在动、怎么转到下一镜。
2. 有参考片时，用 `extract_frames.py --every 0.5` 抽帧逐帧看，量出机位和进出画比例，再模仿。
3. 配色在画第一张图之前定好。每一场用什么颜色，列成色表 `storyboard/palette.md`。
4. 色块草图：把每镜的主要元素写成 `storyboard/sketch.json`，运行 `sketch.py`。它为每镜画一张 1920×1080 草图，标出 38% 和 62% 线，拼成总表和黑白总表，并报告明暗对比太低的元素。黑白下人和背景分不开，就改配色。

产出：`storyboard/shots_vN.md`、`palette.md`、草图总表。闸门：用户确认分镜表和总表。

### 3. 画风和设定图

1. 你写提示词，画师出 2–3 种画风的样帧，用户选。有参考图最好。
2. 画风定了，再给每个角色和固定道具画设定图：正面、侧面、几个表情。
3. 固定特征要写死位置，例如「纹身在左手臂外侧」。不写死，后面每张图都可能不一样。

产出：`design/style_vN.png`、`design/<角色>_vN.png`。闸门：用户确认画风（规矩 2）。

### 4. 每镜首尾帧

首尾帧就是这个镜头的第一张和最后一张画面。这是降低抽卡率最关键的一步：只靠文字生成，模型容易出逻辑错；雨、帽子、纹身这类小东西只写在文字里，拍着拍着就没了，必须在首尾帧都画上。

1. **先写再画**：每镜写出「首帧画什么、尾帧画什么、中间发生什么」，交给审核 agent，通过后再画。这样能省很多画师额度。
2. **先画内容最多的那张**（通常是尾帧），再在它上面改出首帧。这样两张图的机位和构图一致。
3. 同一地点、同一机位的镜头，直接在前一张图上改。
4. 推镜头：尾帧可以直接把首帧裁一块放大（`frame_tools.py zoom`）。首尾帧构图完全一样，视频就等于不动。
5. 只改一小块时，画师也会重新处理整张图。所以把改好的那一块贴回原图（`frame_tools.py patch`）。
6. 画师出的图不一定正好是目标画幅。用 `frame_tools.py info` 检查，用 `fit` 裁好。首帧和尾帧尺寸必须一样。
7. 用 **P4** 逐条自查。辅助检查：`pair` 叠图找错位，`phone` 缩到手机大小看，放大看有没有多余的东西。

产出：`frames/S01_first_vN.png`、`frames/S01_last_vN.png`。闸门：P4 自查无问题。

### 5. 视频提示词和提交前审核

1. 每镜用七段式模板 **P5**，把每一秒发生什么都写下来。写完对照 `references/pitfalls.md` 查一遍。出了问题先怀疑提示词，再怀疑模型。
2. 新开审核 agent，用 **P6**。材料：提示词、首帧、尾帧、设定图、分镜表、配色规则。审核结果存进 `reviews/`。
3. 报价：`seedance.py quote`。告诉用户：镜头、模型、秒数、单价、本次费用、已花费用、剩余预算。

闸门：审核写了「通过」，用户同意报价（规矩 3）。

### 6. 生成视频

1. 闸门通过后，才运行 `seedance.py submit ... --yes --wait`。没有用户同意，不要加 `--yes`。
2. 省钱：用 720p 生成，后期再放大到 1080p。不专门拍测试片，直接拍第一个正式镜头。新做法先拿一两个最难的镜头试，行得通再全部提交。
3. 选模型：Seedance 2.5 约是 2.0 mini 的 3 倍价。不是特别复杂、特别考验模型的镜头，2.0 mini 就够用。
4. 拿到片段后，用 `extract_frames.py --first-last` 和 `--every 0.5` 抽帧检查。声音请用户听：2.0 mini 自带音效常能直接用；2.5 写了「没有音乐」有时还会混进音乐，这种不用，音效后期另加。
5. 出问题按规矩 4 处理。旧片段保留。

### 7. 后期

用 **P7**，命令参考 `references/post-production.md`。全部用代码做：拼接、转场、调色、放大、卡点。做完抽查每个切点前后 3 帧。

### 8. 全片复核和沉淀

1. 新开审核 agent，用 **P8**，只给成片，不给任何结论，让它像观众一样从头看。
2. 修完的成片放进 `final/`。
3. 写 `lessons.md`：画风、最终提示词、犯过的错、实际花费。下次做片先读它。

## 怎样开独立审核 agent

审核 agent 不能带你的上下文。你和用户聊了很久，看故事时会自动脑补；新 agent 什么都不知道，像第一次看片的观众，它看不懂的地方就是真没讲清楚。

- 只给它模板和材料文件路径。不给你的结论、解释或聊天记录。
- 它只读不改。把它的结论原样存进 `reviews/`。
- 开法按宿主选：

| 宿主 | 开法 |
| --- | --- |
| Claude Code | Agent 工具（general-purpose），prompt 是模板加文件路径 |
| Codex | 有子 agent 工具就用；没有就开新会话：`codex exec --skip-git-repo-check -s read-only --ephemeral - < review_prompt.txt` |
| Cursor | 子 agent（Task）；没有就请用户开一个新 chat，贴入模板 |
| agy（Antigravity CLI） | 子 agent；没有就开新会话：`agy -p "<模板和文件路径>"` |

实在开不了新 agent，就告诉用户。你可以自查，但要标明「这是自查，不是独立审核」，并且不能用自查代替规矩 3 的「通过」。

## 四线程模式（可选）

用户想让你在他不在时继续做，或提到「四线程」时，用 **P9**：你当主做，再开审核、监督、代理三个子 agent。代理只能在总预算内批准提交，超预算就停下等用户。所有决定和花费记进 `reviews/decisions.md`，用户回来可以推翻任何决定。

## 项目文件

```
<项目>/
├── brief.md          # 片长、画幅、预算、配乐、字幕、参考
├── budget.json       # seedance.py budget 写入
├── ledger.jsonl      # seedance.py 记录每次提交和花费
├── story/            # story_v1.md ...
├── storyboard/       # shots_v1.md、palette.md、sketch.json、sketches/
├── design/           # 画风样帧、角色和道具设定图
├── frames/           # S01_first_v1.png、S01_last_v1.png ...
├── prompts/          # 生图提示词 img/，视频提示词 video/S01_v1.txt
├── clips/            # S01_v1.mp4 和 S01_v1.mp4.task.json
├── post/             # 无损中间文件
├── reviews/          # 每次审核的原文结论、decisions.md
├── final/            # 成片
└── lessons.md        # 经验沉淀
```

镜头编号用 `S01`、`S02`。版本号只增不改。

## 脚本

脚本在本 Skill 的 `scripts/` 目录。用本 Skill 的绝对路径调用，例如 `python <skill>/scripts/seedance.py ...`。每个脚本都支持 `--help`。

| 脚本 | 用途 |
| --- | --- |
| `doctor.py` | 检查 Python、Pillow、ffmpeg、codex、`ARK_API_KEY`（只报有没有，不打印值） |
| `codex_image.py` | 调用本机 Codex 画一张图：`--prompt-file`、`--out`、可多次 `--ref` 参考图。不覆盖已有文件。额度用完时退出码 3。 |
| `seedance.py` | `budget` 设预算；`quote` 报价；`submit` 提交（不加 `--yes` 只报价不提交；超预算退出码 5；欠费退出码 3）；`wait` 轮询并下载；`status` 查状态；`ledger` 看花费。依赖同目录的 `seedance_lib.py`。 |
| `frame_tools.py` | 图片检查：`info`、`fit`、`zoom`、`patch`、`pair`、`gray`、`phone`、`guides`、`sheet` |
| `sketch.py` | 从 `sketch.json` 画分镜色块草图、总表、黑白总表，并报告明暗对比太低的元素 |
| `extract_frames.py` | 从视频抽帧：`--first-last`、`--every`、`--at`、`--around`（切点前后 `--n` 帧） |

接口细节、模型 ID 和价格在 `references/seedance-api.md`。价格是估算，以火山方舟账单为准。

## 参考文件

- `references/prompts.md`：P1–P9 提示词模板原文，以及画师提示词写法。每到一步，读对应模板。
- `references/pitfalls.md`：AI 视频的固定弱点，以及「模型容易犯的错 → 应该怎么写」对照表。写故事、写视频提示词、审核时都要读。
- `references/seedance-api.md`：Seedance 请求格式、参数、限制和价格。
- `references/post-production.md`：ffmpeg 后期命令。
