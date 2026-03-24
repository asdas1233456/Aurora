# ADB 常用命令与移动测试经验

本文整理 Android 测试中常见的 ADB 命令、使用场景和排障经验。

## 1. 设备连接与状态查看

### 查看连接设备

```bash
adb devices
```

说明：

- 查看当前连接的模拟器或真机
- 状态常见为 `device`、`offline`、`unauthorized`

经验：

- 如果是 `unauthorized`，通常需要在手机上确认 USB 调试授权
- 如果是 `offline`，可以尝试重新插拔数据线或执行 `adb kill-server`

### 重启 ADB 服务

```bash
adb kill-server
adb start-server
```

使用场景：

- 设备连接异常
- 多设备切换异常
- ADB 卡住

## 2. 安装、卸载与应用信息

### 安装 APK

```bash
adb install app.apk
adb install -r app.apk
adb install -t app.apk
```

说明：

- `-r`：覆盖安装
- `-t`：允许安装测试包

经验：

- 自动化回归时通常使用 `-r`
- 如果是 debug 包且安装失败，先检查签名冲突和旧版本残留

### 卸载应用

```bash
adb uninstall 包名
adb uninstall -k 包名
```

说明：

- `-k`：保留数据和缓存目录

### 查看已安装包

```bash
adb shell pm list packages
adb shell pm list packages | grep 包名
```

## 3. 启动、停止与页面跳转

### 启动应用

```bash
adb shell am start -n 包名/Activity名
```

示例：

```bash
adb shell am start -n com.demo.app/.MainActivity
```

### 强制停止应用

```bash
adb shell am force-stop 包名
```

### 清除应用数据

```bash
adb shell pm clear 包名
```

经验：

- 做登录、首启、引导页测试时，经常需要 `pm clear`
- 回归前先清数据，能减少历史状态干扰

## 4. 日志与问题定位

### 查看实时日志

```bash
adb logcat
```

### 清空日志

```bash
adb logcat -c
```

### 按关键字过滤

```bash
adb logcat | findstr 包名
```

经验：

- 定位闪退问题时，优先关注：
  - `FATAL EXCEPTION`
  - `ANR`
  - `crash`
  - 目标包名
- 复现问题前先清空日志，便于缩小分析范围

## 5. 截图、录屏与取证

### 截图

```bash
adb shell screencap -p /sdcard/test.png
adb pull /sdcard/test.png
```

### 录屏

```bash
adb shell screenrecord /sdcard/test.mp4
adb pull /sdcard/test.mp4
```

经验：

- 提交 Bug 时，截图用于静态证据，录屏用于复现路径
- 自动化失败后，可结合截图和 logcat 一起分析

## 6. 文件操作

### 上传文件到设备

```bash
adb push local.txt /sdcard/
```

### 从设备拉取文件

```bash
adb pull /sdcard/test.txt
```

适用场景：

- 上传测试数据
- 拉取日志
- 拉取截图、录屏、导出文件

## 7. 网络与性能辅助命令

### 查看当前前台 Activity

```bash
adb shell dumpsys window | findstr mCurrentFocus
```

### 查看应用内存信息

```bash
adb shell dumpsys meminfo 包名
```

### 查看 CPU 信息

```bash
adb shell top
```

### 查看电量信息

```bash
adb shell dumpsys battery
```

经验：

- 性能测试不要只看单一指标
- 至少同时看：
  - CPU
  - 内存
  - 帧率
  - 电量
  - 启动时长

## 8. 常见排障经验

### 问题：设备不显示

排查步骤：

- 检查 USB 调试是否开启
- 检查驱动是否安装
- 重启 ADB 服务
- 更换数据线或 USB 口

### 问题：安装失败

常见原因：

- 签名不一致
- 存储空间不足
- 版本不兼容
- 测试包未允许安装

### 问题：脚本执行不稳定

可能原因：

- 设备性能不足
- 弹窗未处理
- 页面未加载完成
- 元素定位不稳定

## 9. 测试建议

- ADB 命令要和测试场景绑定，不要只背命令
- 关键命令要沉淀成脚本，提高回归效率
- 每次排障至少保留：
  - 复现步骤
  - logcat
  - 截图或录屏
  - 设备信息
