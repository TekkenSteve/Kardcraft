# Kardcraft Desktop - Windows Build Guide

用于生成 Windows 安装包（MSI / NSIS）和便携版 EXE。

## 构建方式

- 原生 Windows 构建（推荐）：可产出 MSI + NSIS + EXE
- macOS/Linux 交叉构建：通常只适合便携 EXE

## Native Windows Build

### Prerequisites

- Windows 10/11 x64
- Node.js 18+
- Rust（rustup）
- Visual Studio Build Tools（含 `Desktop development with C++`）
- WebView2 Runtime

### 构建命令

```powershell
npm install

# 全量（MSI + NSIS）
npm run tauri:build

# 单独类型
npm run tauri:build -- --bundles msi
npm run tauri:build -- --bundles nsis
```

### 产物目录

`src-tauri\\target\\release\\bundle\\`

- `msi\\kardcraft-desktop_0.1.0_x64_en-US.msi`
- `nsis\\kardcraft-desktop_0.1.0_x64-setup.exe`
- `..\\release\\kardcraft-desktop.exe`（便携版）

## 发布前检查

```powershell
# SHA256
CertUtil -hashfile kardcraft-desktop_0.1.0_x64_en-US.msi SHA256

# 签名验证
Get-AuthenticodeSignature kardcraft-desktop_0.1.0_x64_en-US.msi
```

建议在干净的 Windows 10/11 环境验证安装、卸载、启动。

## 常见问题

### `MSVC not found`

安装 Visual Studio Build Tools，并勾选 `Desktop development with C++`。

### `WebView2 Runtime is not installed`

安装 WebView2 Runtime：
`https://go.microsoft.com/fwlink/p/?LinkId=2124703`

### `NSIS compiler not found`

```powershell
choco install nsis
```

### `WiX Toolset not found`

```powershell
choco install wixtoolset
```

## 可选：签名命令

```powershell
signtool sign /f certificate.pfx /p password /t http://timestamp.digicert.com `
  kardcraft-desktop_0.1.0_x64_en-US.msi
```

未签名安装包出现 SmartScreen 警告属于预期。
