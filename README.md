# 门铃视频弹窗（Windows）

Home Assistant 发出 MQTT 门铃事件 → 等待 RTSP 可解码 → 打开独立 PotPlayer 置顶窗口 → 默认 60 秒后关闭。支持重复触发延长、系统托盘、Windows 当前用户登录自启动、SQLite 保存配置。

## 1. 首次使用

1. 安装 **Windows 10/11 x64、Python 3.13 x64（含 Python Launcher）和 PotPlayer**。先确认 RTSP 地址可以在 PotPlayer 手动播放。
2. 把整个项目解压到当前用户可写的目录，例如 `文档\DoorbellPopup`。不要放在 `Program Files`、只读磁盘或压缩包里直接运行。不需要管理员权限。
3. 双击 `run.bat`，首次运行会联网安装依赖。填写视频地址、PotPlayer exe、尺寸和位置。点击“手动测试”可测试当前表单，**不自动保存**。
4. 填写 MQTT broker、端口、账号密码、topic。默认 topic 是 `home/doorbell/ring`，精确匹配内容是 `ring`。
5. 点击“保存并连接”，等待状态显示“已连接并订阅”。在现有 Home Assistant 门铃自动化里加入第 3 节的动作。
6. 关闭窗口会缩到托盘。双击蓝色 D 图标打开设置；托盘菜单可测试、停止弹窗或退出。

已有的门铃触发实体不在本项目里猜测或硬编码。沿用你已经验证成功的 Home Assistant 触发条件即可。

## 2. 自己编译 EXE

双击 `build.bat`。脚本会创建项目内的 `.venv`，安装 `requirements.txt`，运行回归测试，然后执行 PyInstaller。需要互联网下载依赖；不需要全局安装 PyInstaller。

输出：`dist\DoorbellPopup.exe`。将 EXE 复制到最终的可写目录，再运行并保存配置。EXE 内含 Python、Qt 和 FFmpeg 检测工具；目标电脑不需要 Python，但仍需要安装 PotPlayer。

打包脚本还会运行 EXE 的离线自检（`--self-check`），结果写入 `dist\self-check.json`，检查打包后的 GUI、SQLite/DPAPI 和内置 FFmpeg 解码。此自检不连接门铃或 MQTT，不改变自启动。

命令行等价操作（在项目目录执行）：

```bat
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name DoorbellPopup --collect-all imageio_ffmpeg app.py
```

单文件 EXE 启动时会将依赖解压到临时目录，所以首次启动可能稍慢；**配置和日志不会存到临时解压目录**。源码运行时存到 `app.py` 所在目录，打包后存到 EXE 所在目录。

若使用 Python 3.11/3.12，可以手动创建对应版本的 `.venv` 后再运行脚本；推荐并验证的目标是 3.13 x64。其他架构不在本交付的验证范围。

## 3. Home Assistant

在你现有的、已经能识别门铃的自动化里，加入这个动作（同时提供 `home_assistant.yaml`）：

```yaml
- action: mqtt.publish
  data:
    topic: home/doorbell/ring
    payload: ring
    qos: 1
    retain: false
```

这是**动作列表片段，不是完整自动化**。界面的单个动作 YAML 编辑器如要求对象，可去掉第一行前面的 `- ` 并调整缩进。Home Assistant 必须已配置 MQTT 集成，连接与本应用相同的 broker。也可在开发者工具的动作页面调用 `mqtt.publish` 测试。

不要用保留消息发送门铃事件；程序会忽略订阅时收到的 retained 消息。QoS 1 可能重复投递，本程序会延长现有窗口，不叠加多个窗口。门铃事件不是离线任务：电脑离线期间的事件不会在重连后排队弹出。

## 4. 视频上线、重试与显示计时

- 门铃触发后使用内置 FFmpeg 通过 RTSP over TCP 解码一帧。默认每次最多 8 秒、间隔 2 秒、总等待 45 秒；无有效帧就重试。等待期间没有常驻视频连接。
- 成功后结束检测连接，再用 PotPlayer `/new` 打开视频。在识别到播放器窗口后开始默认 60 秒的计时。**可解码检测不等于能确认 PotPlayer 已呈现第一帧**，播放器自身缓冲时间也计入显示时间。
- 重复触发将截止时间延长到“本次触发后至少 N 秒”。尚未出现窗口时，延长视频上线等待期限。不会创建多个弹窗。
- PotPlayer 意外退出或 12 秒内没有出现可管理窗口时，重新检测和启动；已有显示截止时间不重置。
- 若播放器进程还在但画面卡住，外部程序不能可靠判断其实际播放状态。可设置“定时重新打开播放器”为 20 秒等，周期性关闭本应用的播放器并重新检测。此方式会中断正常画面，默认关闭。需要立即重开时，用“停止弹窗”后“手动测试”。
- 摄像头需要由 Home Assistant / SwitchBot 先唤醒。本应用只等待流就绪，**不会调用 SwitchBot 云端唤醒接口**。若设备限制单客户端连接，检测连接释放后设备可能需要时间；应在现场验证重连行为。
- 显示窗口以物理像素配置，包含标题栏/边框；支持负数坐标和副屏。“放到主屏幕右下角”可找回屏幕外的窗口。播放器最小尺寸和皮肤可能影响实际大小。
- 请将 PotPlayer 设置为窗口模式启动，禁用全屏启动。程序每 200ms 对自己启动的 PotPlayer 窗口恢复位置、尺寸与置顶，不抢键盘焦点。

## 5. 配置、安全与权限

目录内运行后产生 `settings.db`、`doorbell.log`（约 1 MB 轮转，最多 3 份备份）。目录不可写、数据库损坏或无法解密时会明确报错，不静默切换目录、不自动覆盖旧配置。

MQTT 密码和**整个 RTSP URL**均经过 Windows DPAPI 当前用户加密后存入 SQLite；普通配置不是加密数据库。换 Windows 用户或电脑通常无法解密，必须重新输入。程序不把 URL、MQTT 消息内容、密码、底层异常或完整命令行写入日志。

DPAPI 保护的是落盘数据，不能防止同一登录用户、管理员或恶意软件读取运行时内存；RTSP URL 必须传给 FFmpeg/PotPlayer，因此可能从进程命令行看到。PotPlayer 自己的历史记录、播放列表或配置也可能记录视频地址；如需避免，请在 PotPlayer 中关闭相关历史记录。使用专用只读视频账号和仅有订阅权限的 MQTT 账号。

MQTT 可启用 TLS，支持系统信任库或自定义 CA 文件，始终验证证书和主机名。未启用 TLS 的 MQTT 账号密码会通过网络明文传送；建议受信局域网或启用 TLS。RTSP 本身的传输加密取决于设备支持；密码中的特殊字符应在 URL 中进行百分号编码。

自启动通过 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 的 `DoorbellPopup` 项实现，仅当前用户登录后运行，不是系统服务。勾选后点“保存并连接”。EXE 移动后需要重新保存，源码自启动依赖原 `.venv`。禁用时取消勾选并保存；卸载前先禁用，再退出并删除文件夹。Windows 启动应用管理或组织策略也可能禁用它。

程序使用每用户单实例锁。同一用户从另一份目录再次启动，会提示去托盘打开已有实例。

## 6. 不影响已有 PotPlayer 的设计

仅接受 `PotPlayerMini.exe` / `PotPlayerMini64.exe`。启动时传 `/new`，只枚举该次 `Popen` 进程的窗口，不接管其他实例。关闭时使用该 `Popen` 保存的 Windows 原始进程句柄，**不按进程名批量结束、不执行 taskkill**。不追踪或猜测重定向后的其他进程。

计时结束采用终止本应用专用实例，保证关闭失败弹框也不会无限驻留。此实例中的播放列表变更可能不会保存。请不要把门铃专用窗口改作手动播放其他视频；其生命周期仍由本应用控制。若播放器使用管理员权限而本应用没有权限，窗口操作可能失败，请让两者都以普通用户运行。

## 7. 验收与排障

1. 先开一个普通 PotPlayer 播放视频，然后手动测试门铃。确认出现独立窗口，尺寸、位置、置顶正确；时间到后原视频不受影响。
2. 设置显示 10 秒，第 7 秒再发送 `ring`，确认窗口继续到约第 17 秒。
3. 视频未上线时触发，确认状态等待；使设备上线后应出现窗口。一直离线则等待超时后停止。
4. 断开并恢复 broker，确认重新连接并订阅；用错误 payload 和 retained 消息确认不会误触发。
5. 退出并重启确认配置恢复。勾选自启动并保存，注销后登录确认托盘启动。
6. 测试 TLS、自定义 CA、不同显示器缩放比例和非默认 PotPlayer 皮肤。

若 MQTT 已连接但没有弹窗，检查订阅权限、topic、精确匹配内容、retain 标记和摄像头是否被唤醒。若视频等待超时，检查账号、地址、网络、TCP RTSP 支持以及单次检测时间是否太短。

自动化测试覆盖 DPAPI/SQLite 往返与明文检查、重复触发、超时、有效帧判断、只关闭拥有的进程句柄及 MQTT 消息过滤。真实门铃、broker、RTSP 设备与登录自启动仍须按上述步骤现场验收；不宣称已在你的设备上完成端到端测试。

## 参考与依赖

- [Paho MQTT Python 官方文档](https://eclipse.dev/paho/clients/python/docs/)
- [Home Assistant mqtt.publish](https://www.home-assistant.io/actions/mqtt.publish/)
- [Microsoft DPAPI 说明](https://learn.microsoft.com/en-us/windows/win32/SecCrypto/example-c-program-using-cryptprotectdata)
- [ImageIO FFmpeg](https://github.com/imageio/imageio-ffmpeg)
- [PyInstaller 参数](https://pyinstaller.org/en/stable/usage.html)
- PotPlayer `/new`、参数顺序依据本机安装目录随附的 `CmdLine64.txt` 英文段核对。

依赖版本固定于 requirements.txt。FFmpeg 随 imageio-ffmpeg wheel 提供；PySide6、FFmpeg 等第三方组件保留各自许可。若向公众分发打包文件，应同时处理这些组件适用的许可、声明和源码提供要求。
