# OBS Virtual Try-On

基于 OBS 直播的 AI 虚拟换装系统，使用 Lucy VTON (Decart) 实现实时直播画面换装。

## 功能特点

- **实时换装** - 基于 WebRTC 的实时视频流处理，30fps 低延迟换装
- **OBS 直播集成** - 连接 OBS WebSocket，获取实时直播画面并输出虚拟摄像头
- **Lucy VTON 云端推理** - 使用 Decart 平台的 Lucy VTON 模型，无需本地 GPU
- **拖拽上传** - 支持从图库拖拽或本地上传服装图片
- **实时预览** - 主画面显示换装结果，底部显示原始直播画面
- **提示词定制** - 支持自定义提示词和快速标签选择

## 界面布局

```
┌─────────────────────────────────────────────────────────────┐
│  [LIVE]                              [AI 生成]              │
├──────────┬──────────────────────────────┬───────────────────┤
│          │                              │                   │
│  服装    │       主画面                 │   Lucy实时        │
│  图库    │    (AI换装结果)              │   美少女直播      │
│          │                              │                   │
│  [本地]  │                              │   STEP 1: 相机    │
│          │                              │   STEP 2: 模式    │
│          │                              │   STEP 3: 开始    │
│          ├──────────────────────────────┤                   │
│          │   [原始直播画面]              │   提示词/标签     │
└──────────┴──────────────────────────────┴───────────────────┘
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

编辑 `.env` 文件：

```env
# Decart API Key（必需，用于 Lucy VTON）
LUCY_API_KEY=dct_your_key_here

# OBS WebSocket 配置（可选）
OBS_HOST=localhost
OBS_PORT=4455
OBS_PASSWORD=

# 代理设置（可选）
HTTP_PROXY=
HTTPS_PROXY=
```

**获取 Decart API Key：**
1. 访问 https://platform.decart.ai
2. 注册并创建 API Key（格式：`dct_xxxxx`）
3. 复制到 `.env` 文件

### 3. 启动服务器

```bash
# Windows
start.bat

# 或手动启动
python server.py
```

### 4. 打开浏览器

访问 http://localhost:8443

## 使用方法

### 连接 OBS

1. 打开 OBS Studio
2. 启用 WebSocket：**工具 > WebSocket 服务器设置** > 勾选「启用」
3. 页面会自动连接 OBS（默认密码：`a123456789`）
4. LIVE 指示灯变为粉色表示连接成功

### 实时换装

1. **确认相机** - STEP 1 点击「确认相机」，选择 OBS 虚拟摄像头
2. **选择模式** - STEP 2 保持默认「服装试穿/换装 (lucy-vton-3)」
3. **上传服装** - 从左侧图库选择或拖拽上传服装图片
4. **开始换装** - STEP 3 点击「开始换装」按钮
5. **实时效果** - 主画面实时显示换装结果，支持中途更换服装

### 提示词使用

提示词用于描述换装效果，默认已填入推荐内容。可选快速标签：

- 可爱少女、清纯、偶像
- 虚拟主播、写实美女、写真

## 技术架构

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   浏览器界面     │ ←→  │   FastAPI 服务器  │ ←→  │   OBS Studio    │
│  (HTML/CSS/JS)  │     │   (Python)      │     │  (WebSocket)    │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                        ┌────────┴────────┐
                        │   Lucy VTON     │
                        │  (Decart 云端)  │
                        │   WebRTC 实时   │
                        └─────────────────┘
```

### 工作模式

| 模式 | 说明 | 延迟 |
|------|------|------|
| **WebRTC 实时**（默认） | 通过 WebRTC 持续推送帧，实时返回换装结果 | ~30fps 实时 |
| **REST 批量** | 单帧请求处理，适合调试 | ~50-60 秒/帧 |

### 文件结构

```
test60/
├── server.py           # FastAPI 后端服务器
├── lucy_api.py         # Lucy REST API 客户端（批量模式）
├── lucy_realtime.py    # Lucy WebRTC 实时客户端
├── requirements.txt    # Python 依赖
├── .env               # 环境变量配置
├── start.bat          # Windows 启动脚本
├── static/
│   ├── index.html     # 主页面
│   ├── style.css      # 样式表
│   └── app.js         # 前端逻辑
├── uploads/           # 临时上传文件
├── clothing/          # 服装图库
└── outputs/           # 生成的结果图片
```

### API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 获取服务器状态 |
| POST | `/api/obs/connect` | 连接 OBS |
| POST | `/api/obs/disconnect` | 断开 OBS |
| GET | `/api/obs/screenshot` | 获取 OBS 截图 |
| POST | `/api/clothing/upload` | 上传服装图片 |
| GET | `/api/clothing/list` | 获取服装列表 |
| DELETE | `/api/clothing/{filename}` | 删除服装图片 |
| GET | `/api/lucy/config` | 获取 Lucy API 配置 |
| POST | `/api/lucy/process` | 单帧换装处理（REST） |
| GET | `/api/stream` | SSE 流式结果推送 |
| WS | `/ws` | WebSocket 状态通信 |
| WS | `/ws/vton` | WebSocket 实时换装流 |

## 配置说明

### OBS WebSocket

- 默认端口：4455
- 启用方式：OBS > 工具 > WebSocket 服务器设置
- 默认密码：`a123456789`（可在页面修改）

### Lucy VTON

- 平台：Decart (https://platform.decart.ai)
- 模型：lucy-vton-latest
- 分辨率：1088x624 @ 30fps
- 计费：2 credits/秒 (720p)

## 常见问题

### Q: 连接 OBS 失败？

A: 检查以下项目：
- OBS 是否正在运行
- WebSocket 是否已启用（工具 > WebSocket 服务器设置）
- 端口是否为 4455
- 密码是否正确

### Q: 实时换装没有反应？

A: 可能原因：
- 未配置 `LUCY_API_KEY` 或 Key 无效
- 网络无法访问 Decart API（可能需要代理）
- 未上传服装图片
- OBS 未连接或虚拟摄像头未启动

### Q: 画面卡顿或延迟高？

A: 优化建议：
- 检查网络连接质量
- 确认代理设置正确（如使用代理）
- 降低 OBS 输出分辨率

### Q: LIVE 指示灯不亮？

A: 需要先连接 OBS，连接成功后 LIVE 会变为粉色。页面加载时会自动尝试连接。

## 依赖项

- Python 3.9+
- FastAPI + uvicorn
- Pillow, numpy
- websockets, pydantic
- python-dotenv, requests
- decart[realtime]（Lucy VTON SDK）

## 许可证

MIT License

## 相关链接

- [Decart 平台](https://platform.decart.ai)
- [Lucy VTON 文档](https://platform.decart.ai)
- [OBS Studio](https://obsproject.com/)
- [OBS WebSocket](https://github.com/obsproject/obs-websocket)
