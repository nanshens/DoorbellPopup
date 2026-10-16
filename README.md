# 门铃视频弹窗：内嵌播放版

Home Assistant MQTT 门铃事件触发本程序的置顶视频窗口。使用 PySide6 Qt Multimedia / FFmpeg 内嵌解码，不再调用 PotPlayer，也不需要单独安装 VLC。

## 源码测试

先从托盘退出旧程序，再运行 `run.bat`（首次安装 requirements.txt），或者在已安装依赖的 Python 环境运行 `python app.py`。

保留项目目录的 settings.db。旧配置中的视频地址、MQTT、位置、显示时间仍可读取；原播放器路径和预检测字段会被忽略，新静音选项默认关闭。手动测试使用当前表单，不自动保存；“保存并连接”保存配置并连接 MQTT。

## 播放行为

- 触发立即显示视频窗口，第一帧到达后开始显示倒计时。
- 默认连接或连续无画面超时 8 秒，重试间隔 2 秒，首次上线最长等待 45 秒。
- 重复触发延长当前显示或等待时间，不创建多个窗口。
- 连接错误、流结束或长时间无视频帧时重连。重连不重置已有显示截止时间。
- 关闭视频窗口或点击“停止弹窗”会释放视频连接。待命不连接摄像头。
- 可选择静音；定时重连默认关闭。
- 窗口尺寸与位置使用 Qt 逻辑像素，高 DPI 下与旧版物理像素的实际尺寸可能不同。
- 关闭设置窗口缩到托盘；托盘“退出”结束程序。

摄像头仍需由已有 Home Assistant 自动化唤醒。实际出图延迟取决于摄像头、网络及关键帧，内嵌不保证立即出图。实际 RTSP 兼容性需用户现场验证。

## MQTT

沿用现有 broker、账号、topic。Home Assistant 动作示例：

```yaml
- action: mqtt.publish
  data:
    topic: home/doorbell/ring
    payload: ring
    qos: 1
    retain: false
```

忽略 retained 消息，内容精确匹配，重连后自动重新订阅。

## 配置

settings.db 与 doorbell.log 保存在源码目录，未来打包后保存在 EXE 目录。RTSP 地址与 MQTT 密码使用 Windows 当前用户 DPAPI 加密，换用户或电脑需要重新填写。应用日志不记录地址或密码；第三方视频后端在源码运行的终端可能打印媒体诊断，请勿直接分享含凭据的终端输出。

当前用户登录自启动通过 Windows Run 注册表项设置，在“保存并连接”后生效。目录移动后重新保存。每用户只允许一个运行实例。

## 验证和后续打包

运行 `python -m unittest discover -s tests -v` 验证行为。`python app.py --self-check` 使用项目自带的无隐私测试视频验证真实解码、界面和加密，不连接 MQTT 或摄像头。

已按用户要求打包内嵌播放版 EXE：dist/DoorbellPopup.exe，打包自检通过。后续可使用 build.bat 重新打包。退出旧程序后，将 EXE 放到原 settings.db 所在目录即可沿用配置；自启动需在 EXE 中重新保存。

组件文档：https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QMediaPlayer.html
