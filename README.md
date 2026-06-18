# 喝水提醒（Windows 托盘 + AI）

一个常驻 Windows 系统托盘的喝水提醒小工具：到点从右下角弹出小面板提醒、一键打卡记录，并可接入 AI 大模型自动计算每日饮水目标、生成日报/周报与健康建议，报告还能推送到微信/邮件。数据全部存在本地，可完全离线使用。

## 功能

- **右下角悬浮小面板**：点击托盘图标弹出，含进度环、近 7 天迷你柱状图、喝一杯/快捷毫升/撤销/暂停按钮，点面板外自动收起
- **自适应提醒**：在活跃时段内提醒，且"喝完后重新计时、忽略也会持续提醒"，不会因为没响应就断掉（详见下文）
- **撤销上一杯**：误点打卡可一键撤销当天最近一条记录（面板 / 网页 / 托盘都能撤）
- **Web 可视化控制面板**：进度环、近 7 天柱状图、一键打卡、在线改设置、手动生成报告
- **系统托盘常驻**：右键菜单含喝一杯、撤销、暂停/恢复、打开面板、生成报告、重算目标、退出
- **勿扰时段**（如午休）自动跳过
- **AI 智能目标**：根据体重、气温、运动量计算每日推荐饮水量（未配置 AI 时用公式兜底）
- **AI 日报/周报**：完成率、时间分布、连续达标天数 + 个性化健康建议；同一天结果缓存复用，省 token，也可强制重新生成
- **报告推送**：邮件 / 微信（Server酱 / PushPlus）
- **可选天气接入**（wttr / OpenWeather / 和风），让目标更精准

## 安装与运行

### 方式一：下载免安装版（推荐，无需 Python）

适合直接使用，**不用安装 Python 或任何依赖**：

1. 打开仓库的 **Releases** 页，下载最新的 `water-reminder-windows.zip`
2. 解压到任意位置（比如桌面）
3. 双击文件夹里的 **`喝水提醒.exe`** 即可运行

程序会在 exe 同级目录自动生成 `config.yaml`（首次为默认配置，可用记事本编辑）和 `data\`（喝水记录）。整个文件夹可随意移动，但 exe 不能单独拎出来（依赖在旁边的 `_internal\` 里）。

> 想用 AI 功能：编辑 exe 旁边的 `config.yaml`，把 `ai.enabled` 设为 `true` 并填入 `api_key` 等（见下方「配置」）。

### 方式二：从源码运行（开发者）

需要 Python 3.10+。

```powershell
cd "C:\Users\youku\Desktop\喝水提醒"
pip install -r requirements.txt
copy config.example.yaml config.yaml   # 首次使用，复制一份配置后按需编辑
```

`config.yaml` 已被 `.gitignore` 忽略，用于存放含密钥的个人配置。然后任选一种启动：

```powershell
python -m src.shortcut   # 生成桌面快捷方式，之后双击图标启动(无终端黑窗)
python -m src.main       # 或直接命令行启动
```

启动后程序进入系统托盘（右下角）。左键点击水滴图标弹出小面板，右键打开菜单。

## 提醒逻辑（自适应）

提醒不是固定钟点死板地每隔 N 分钟弹一次，而是按"最近一次活动 + N 分钟"动态排程：

- 每次提醒弹出时，会**立刻排好下一次**——所以即使你忽略它、处于暂停或勿扰时段，到点仍会继续提醒，不会中断。
- **喝水后从那一刻重新计时**：刚喝完不会马上又被催。
- 启动时**不会立刻弹窗打扰**，首次提醒排在一个间隔之后。

间隔、活跃时段、勿扰时段都在 `config.yaml` 的 `reminder` 段配置。

## 控制面板

程序启动时会同时开启本地 Web 控制面板，浏览器访问 http://127.0.0.1:8765 （也可右键托盘选「打开控制面板」）。支持：

- 查看今日进度环、杯数、连续达标天数、忽略次数
- 一键「喝一杯」、自定义毫升打卡、「↩ 撤销」上一杯
- 近 7 天饮水柱状图（绿色表示达标）
- 暂停/恢复提醒、重算目标
- 生成日报/周报（默认复用当天缓存）并推送；「↻ 重新生成」强制刷新
- 在线编辑全部设置并即时生效（端口与开关见 `config.yaml` 的 `web` 段）

## 配置

编辑 `config.yaml`（结构参见 `config.example.yaml`）：

- `reminder`：提醒间隔、杯量、活跃/勿扰时段、快捷毫升按钮
- `profile`：体重、运动量、固定目标（为 0 时自动计算）
- `ai`：OpenAI 兼容接口的 `api_key`/`base_url`/`model`/`wire_api`，设 `enabled: true` 启用
- `weather`：可选天气接入
- `report`：日报/周报生成时间
- `push`：邮件、Server酱、PushPlus 推送配置

### AI 服务商示例

| 服务商 | base_url | model | wire_api |
| --- | --- | --- | --- |
| YesCode（路由网关） | https://co.yes.vg/v1 | gpt-5.5（或 claude-haiku-4.5 / gemini-2.5-flash 等） | `responses` |
| DeepSeek | https://api.deepseek.com | deepseek-chat | `chat` |
| 通义千问 | https://dashscope.aliyuncs.com/compatible-mode/v1 | qwen-plus | `chat` |
| 智谱 GLM | https://open.bigmodel.cn/api/paas/v4 | glm-4-flash | `chat` |
| Kimi | https://api.moonshot.cn/v1 | moonshot-v1-8k | `chat` |

> `wire_api` 是关键：yescode 这类网关走 `responses` 协议，其余标准 OpenAI 兼容接口走 `chat`。

### API Key 的两种填法

1. 直接写在 `config.yaml` 的 `ai.api_key`（本地使用最方便）。
2. 留空 `ai.api_key`，改用环境变量 `WATER_AI_API_KEY`（优先级高于配置文件，避免密钥进入文件）：

```powershell
$env:WATER_AI_API_KEY = "team-xxxx"
python -m src.main
```

### 天气服务商（可选）

天气仅用于让每日饮水目标更精准，不开也能用（用 `default_temp_c`）。

| provider | 是否收费 | 是否要 key | city 填什么 |
| --- | --- | --- | --- |
| wttr（推荐） | 完全免费 | 不需要 | 城市拼音/英文，如 `Beijing` |
| openweather | 免费额度 | 需注册 key | 英文城市名 |
| qweather（和风） | 免费额度 | 需注册 key | LocationID 或 `经度,纬度` |

> 未配置 AI 时，程序仍可正常提醒与统计，目标用公式（体重 × 30ml + 运动补偿 + 高温补偿）计算，报告用内置模板。

## 开机自启

```powershell
python -m src.autostart enable    # 启用
python -m src.autostart disable   # 取消
python -m src.autostart status    # 查看
```

## 打包为 exe（免安装 Python，双击即用）

已配置好 `build.spec`（含路径处理、网页/图标资源打包、无控制台窗口）：

```powershell
pip install pyinstaller
pyinstaller build.spec
```

产物在 `dist/喝水提醒/` 文件夹，内含 `喝水提醒.exe`。把**整个文件夹**压缩后即可分发到任意 Windows，对方解压双击 exe 即可运行，**无需安装 Python**。

- `config.yaml` 和 `data/` 会自动在 **exe 同级目录**生成（首次运行写出一份默认配置，不含任何密钥），可直接编辑。
- 若想把现有配置/记录迁移到 exe 版，把当前目录的 `config.yaml` 和 `data/` 文件夹拷到 exe 旁边即可。
- 打包入口是根目录的 `run.py`（源码运行仍用 `python -m src.main`）。

## 目录结构

```
config.example.yaml  配置模板（复制为 config.yaml 使用）
config.yaml          个人配置（gitignore，含密钥）
requirements.txt
src/
  main.py            入口：主线程跑小面板，托盘/Web/调度在后台线程
  config.py          配置加载与点路径访问
  storage.py         SQLite 记录与统计（加锁，多线程安全）
  reminder.py        核心服务：自适应调度、目标、报告、缓存
  notifier.py        通知与多渠道推送
  panel.py           右下角悬浮小面板（Tkinter）
  tray.py            系统托盘与右键菜单
  weather.py         天气（可选）
  autostart.py       开机自启
  shortcut.py        生成启动器与桌面快捷方式
  icon.py            水滴图标绘制
  web/
    server.py        Flask 控制面板后端与 REST API
    static/index.html 控制面板前端页面
  ai/
    client.py        OpenAI 兼容客户端（支持 chat / responses 两种协议）
    goal.py          智能目标计算
    report.py        日报/周报生成
data/
  water.db           喝水记录（自动生成，gitignore）
```

## 架构说明

单进程内三套并行协作，通过线程安全的命令队列通信：

- **主线程** → Tkinter 小面板事件循环（GUI 必须在主线程）
- **后台线程** → 系统托盘 + Flask 网页面板
- **调度线程** → APScheduler 触发提醒与报告

核心枢纽是 `AppService`（`reminder.py`），把配置/存储/通知/AI 串起来供托盘和网页调用。SQLite 单连接被多线程共享，所有读写都用一把可重入锁串行化。
