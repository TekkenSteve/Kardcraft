# Kardcraft Desktop - iOS Build Guide

用于 iOS 模拟器和真机构建（Tauri 2.x）。

## Quick Start

### 模拟器（无需开发者账号）

```bash
npm run tauri ios build -- --target aarch64-sim
open -a Simulator
```

### 真机（需 Apple ID / 开发者签名）

```bash
# 一次性准备
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
xcodebuild -downloadPlatform iOS

# 构建
npm run tauri ios build -- --target aarch64

# 安装到设备
xcrun devicectl list devices
xcrun devicectl device install app --device DEVICE_ID \
  ~/Library/Developer/Xcode/DerivedData/app-*/Build/Products/release-iphoneos/kardcraft-desktop.app
```

首次安装后需在 iPhone 上信任开发者证书：
`Settings > General > VPN & Device Management`。

## Prerequisites

- macOS + Xcode
- Node.js 18+
- Rust 1.70+
- CocoaPods

推荐检查：

```bash
xcode-select -p
rustup target list | rg ios
```

## 常用命令

```bash
# iOS 开发模式（热更新）
npm run tauri ios dev

# 重建图标并重新打包
npm run tauri icon src-tauri/icons/icon.png
npm run tauri ios build -- --target aarch64

# 清理并重建 iOS 工程
rm -rf src-tauri/gen/apple ~/Library/Developer/Xcode/DerivedData/app-*
npm run tauri ios init
npm run tauri ios build -- --target aarch64-sim
```

## 产物位置

- Simulator: `~/Library/Developer/Xcode/DerivedData/app-*/Build/Products/release-iphonesimulator/kardcraft-desktop.app`
- Device: `~/Library/Developer/Xcode/DerivedData/app-*/Build/Products/release-iphoneos/kardcraft-desktop.app`

## 常见问题

### `iOS platform not installed`

```bash
xcodebuild -downloadPlatform iOS
```

### `simctl` 找不到

```bash
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
```

### 签名证书问题（真机构建）

在 Xcode 登录 Apple ID，并启用 `Automatically manage signing`。

### `PhaseScriptExecution failed`

避免用 Xcode 的 Run 按钮安装；改用命令行 `tauri ios build` + `devicectl`。
