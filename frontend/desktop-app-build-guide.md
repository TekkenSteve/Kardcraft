# Kardcraft Desktop - macOS Build Guide

用于构建和发布 macOS DMG（Tauri）。

## Prerequisites

- Node.js 18+
- Rust 1.70+
- Xcode Command Line Tools

```bash
npm install
npm run tauri --version
```

## 构建

```bash
# 开发
npm run tauri:dev

# 生产（推荐先清理）
rm -rf .next out src-tauri/target/release/bundle
npm run tauri:build
```

## 产物

- `.app`: `src-tauri/target/release/bundle/macos/kardcraft-desktop.app`
- `.dmg`: `src-tauri/target/release/bundle/dmg/kardcraft-desktop_0.1.0_universal.dmg`

## 发布前检查

```bash
# 校验值
cd src-tauri/target/release/bundle/dmg
shasum -a 256 kardcraft-desktop_0.1.0_universal.dmg

# 本地安装验证
open kardcraft-desktop_0.1.0_universal.dmg
```

建议至少验证：启动、API 连接、任务提交、流式更新。

## 常见问题

### `@tauri-apps/plugin-shell` 缺失

```bash
npm install @tauri-apps/plugin-shell
```

### 构建缓存导致旧代码

```bash
rm -rf .next out src-tauri/target/release/bundle node_modules/.cache
npm run tauri:build
```

### Rust 编译异常

```bash
rustup update stable
cd src-tauri && cargo clean && cd ..
npm run tauri:build
```

### universal 构建依赖缺失

```bash
rustup target add aarch64-apple-darwin x86_64-apple-darwin
```

## 可选：签名与公证

```bash
# 签名
codesign --deep --force --verify --verbose \
  --sign "Developer ID Application: Your Name" \
  src-tauri/target/release/bundle/macos/kardcraft-desktop.app

# 提交公证（示例）
xcrun notarytool submit kardcraft-desktop_0.1.0_universal.dmg \
  --apple-id your@email.com \
  --team-id TEAMID \
  --password app-specific-password
```
