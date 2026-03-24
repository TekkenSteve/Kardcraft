# Kardcraft Desktop App

Kardcraft 桌面端（Next.js + Tauri），支持 macOS、Windows、iOS。

## Quick Start

```bash
npm install
npm run tauri:dev
npm run tauri:build
```

默认产物（macOS universal DMG）：
`src-tauri/target/release/bundle/dmg/kardcraft-desktop_0.1.0_universal.dmg`

## Prerequisites

- Node.js 18+
- Rust 1.70+
- Xcode Command Line Tools（macOS/iOS）

## 常用命令

```bash
# 清理后重建
rm -rf .next out src-tauri/target/release/bundle && npm run tauri:build

# 查看 macOS DMG 校验
shasum -a 256 src-tauri/target/release/bundle/dmg/kardcraft-desktop_0.1.0_universal.dmg

# 仅构建单架构（macOS）
npm run tauri:build -- --target aarch64-apple-darwin
npm run tauri:build -- --target x86_64-apple-darwin
```

## 平台说明

- macOS: universal（二进制同时支持 ARM64 + x86_64）
- iOS: 见 [desktop-app-ios-build.md](desktop-app-ios-build.md)
- Windows: 见 [desktop-app-windows-build.md](desktop-app-windows-build.md)

## 常见问题

### 缺少 `@tauri-apps/plugin-shell`

```bash
npm install @tauri-apps/plugin-shell
```

### macOS universal 构建失败

先确认 Rust targets 已安装：

```bash
rustup target add aarch64-apple-darwin x86_64-apple-darwin
rustup target list --installed
```

### `runStatus` 类型报错

合法值只有：`"idle" | "running" | "completed" | "failed"`，不要判断 `"error"`。

## 技术栈

- Next.js 16
- Tauri 2.x
- React 19 + Tailwind + Shadcn/ui
- Redux Toolkit

## 环境变量

```bash
cp .env.local.example .env.local
```

`.env.local` 示例：

```bash
NEXT_PUBLIC_API_BASE_PATH=
NEXT_PUBLIC_AUTH_BASE_PATH=/auth
```
