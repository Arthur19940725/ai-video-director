# 后期命令（ffmpeg）

原则（来自 P7）：

- 全部用代码做，每一步都能重做。
- 中间文件用无损格式（FFV1 + MKV，或 PNG 序列）。只在交付时压一次。
- 新版本存新文件，不覆盖原片段。
- 做完抽查每个切点前后 3 帧（`extract_frames.py --around`）。

下面命令里的 `in.mp4`、`out.mkv` 等都换成项目里的真实路径。

## 1. 先看片段参数

```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate,nb_frames,pix_fmt,color_space,color_primaries,color_transfer \
  -of json clips/S01_v1.mp4
```

## 2. 解码成无损中间文件（按 BT.601 解码）

Seedance 的 mp4 按 BT.601 解码。中间文件统一转成 BT.709，后面的步骤都在 BT.709 下做：

```bash
ffmpeg -i clips/S01_v1.mp4 \
  -vf "scale=in_color_matrix=bt601:out_color_matrix=bt709,format=yuv444p" \
  -c:v ffv1 -level 3 -an post/S01_v1_lossless.mkv
```

## 3. 修片段（先修，修不了才重拍）

剪掉开头那张特别锐的帧（Seedance 2.5），并重排时间戳：

```bash
ffmpeg -i post/S01_v1_lossless.mkv -vf "select='gte(n,1)',setpts=N/FRAME_RATE/TB" -c:v ffv1 post/S01_v1_trim.mkv
```

结尾几帧突然跳（Seedance 2.5）：先抽帧找到最后一张没问题的帧号 K，保留 0..K，再把第 K 帧定格到原时长：

```bash
# D = 要补的秒数
ffmpeg -i post/S01_v1_lossless.mkv -vf "select='lte(n,K)',setpts=N/FRAME_RATE/TB,tpad=stop_mode=clone:stop_duration=D" -c:v ffv1 post/S01_v1_hold.mkv
```

镜头推得不够：先放大 4 倍再 `zoompan`，减少抖动。`Z` 是结尾放大倍数（例如 1.08），`N` 是总帧数：

```bash
ffmpeg -i post/S01_v1_lossless.mkv -vf "scale=iw*4:ih*4:flags=lanczos,zoompan=z='1+(Z-1)*on/N':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1280x720:fps=24" -c:v ffv1 post/S01_v1_push.mkv
```

越到后面越暗越冷（Seedance 2.0 mini）：先测漂移，再按时间线性拉回：

```bash
python <skill>/scripts/extract_frames.py clips/S01_v1.mp4 --out-dir post/S01_v1_check --first-last
python <skill>/scripts/frame_tools.py pair post/S01_v1_check/first.png post/S01_v1_check/last.png --out-dir post/S01_v1_check/pair
# 按 pair 报告的亮度差，用 eq 的逐帧表达式补回（T = 片段秒数，B = 结尾需要补的亮度，0.02 左右起试）
ffmpeg -i post/S01_v1_lossless.mkv -vf "eq=brightness='B*t/T':eval=frame" -c:v ffv1 post/S01_v1_color.mkv
```

色温偏冷用 `colortemperature` 或 `colorbalance` 微调。修完再抽首尾帧，用 `pair` 对比到差值接近 0。

## 4. 调色（按故事分段）

只调彩度和亮度，不动色相。强调色和肤色受保护。不加颗粒、柔光、暗角。

```bash
ffmpeg -i post/S03_v1_lossless.mkv -vf "eq=saturation=1.08:brightness=0.01" -c:v ffv1 post/S03_v1_grade.mkv
```

整体调彩度会影响肤色时，改用 Python 逐帧处理，用遮罩保护肤色和强调色，再抽帧检查肤色。

## 5. 转场

简单淡化或推移用 `xfade`（`offset` = 第一段长度 − 转场长度）：

```bash
ffmpeg -i post/S01.mkv -i post/S02.mkv -filter_complex "[0][1]xfade=transition=fade:duration=0.3:offset=4.7" -c:v ffv1 post/S01_S02.mkv
```

用东西盖屏或带过去的转场（例如一张纸飞过画面）：用 Python 逐帧合成。运动模糊做法：每一帧时间内切 8–16 份子帧，只取前一半（半帧快门，180°）求平均。

## 6. 拼接

所有片段先统一成相同分辨率、帧率、像素格式，再用 concat 滤镜：

```bash
ffmpeg -i post/A.mkv -i post/B.mkv -i post/C.mkv -filter_complex "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]" -map "[v]" -c:v ffv1 post/cut_v1.mkv
```

## 7. 放大和交付

720p 用 lanczos 放大到 1080p，加轻微锐化。不做整段插帧。交付标 BT.709。

只加 `-color_primaries` 等输出参数不够：ffmpeg 8 实测只标上了 colorspace，primaries 和 transfer 还是 unknown。所以在滤镜链末尾用 `setparams` 写进帧里，交付后用 ffprobe 确认三项都是 bt709：

```bash
ffmpeg -i post/cut_v1.mkv -i audio/mix_v1.wav \
  -vf "scale=1920:1080:flags=lanczos,unsharp=5:5:0.4:5:5:0.0,format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709" \
  -c:v libx264 -crf 16 -preset slow -color_primaries bt709 -color_trc bt709 -colorspace bt709 \
  -c:a aac -b:a 192k -shortest final/film_v1.mp4
```

竖版把 `1920:1080` 换成 `1080:1920`。确认标记：

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=color_space,color_primaries,color_transfer -of compact final/film_v1.mp4
```

## 8. 卡点

拍点只从原曲上测，不要在剪过的文件上测。装了 librosa 时：

```python
import librosa
y, sr = librosa.load("audio/song.mp3")
tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
print(tempo, beats[:16])
```

没有 librosa 时，请用户提供 BPM 和第一拍的时间，按 `60 / BPM` 推算。转折对副歌，关键动作对重拍。

## 9. 抽查

```bash
python <skill>/scripts/extract_frames.py final/film_v1.mp4 --out-dir post/check_v1 --around 4.7,9.4 --n 3
python <skill>/scripts/frame_tools.py sheet post/check_v1/*.png --out post/check_v1_sheet.png --cols 7
```

看总表：有没有突跳、颜色跳变、道具数量变化、脸变形。你看不到真正的动态，也听不到声音，要请用户看和听。
