# OBS Virtual Try-On

基于 OBS 直播的 AI 虚拟换装系统，支持实时直播画面换装。

## 功能特点

- **OBS 直播集成** - 连接 OBS WebSocket，获取实时直播画面
- **AI 虚拟换装** - 使用 IDM-VTON 模型进行高质量换装
- **拖拽上传** - 支持从图库拖拽或本地上传服装图片
- **实时预览** - 主画面显示换装结果，底部显示原始直播画面
- **简洁界面** - 三栏布局，操作简单直观

## 界面布局

```
┌─────────────────────────────────────────────────────────────┐
│  [LIVE]                              [密码] [连接]          │
├──────────┬──────────────────────────────┬───────────────────┤
│          │                              │                   │
│  服装    │       主画面                 │   换装控制        │
│  图库    │    (AI换装结果)              │                   │
│          │                              │   - 模式选择      │
│  [刷新]  │                              │   - 服装上传      │
│  [本地]  │                              │   - 提示词        │
│          │                              │   - 开始换装      │
│          ├──────────────────────────────┤                   │
│          │   [原始直播画面]  [音量]      │                   │
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
# Hugging Face Token（用于 AI 换装）
HUGGINGFACE_TOKEN=your_token_here

# Bing 搜索 API（可选，用于图片搜索）
BING_SEARCH_KEY=
```

**获取 Hugging Face Token：**
1. 访问 https://huggingface.co/settings/tokens
2. 登录并创建新 Token
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
3. 在网页顶部输入密码（如有），点击「连接」
4. LIVE 指示灯变为粉色表示连接成功

### 进行换装

1. **上传服装** - 从左侧图库选择或点击「本地」上传
2. **开始换装** - 点击右侧「开始换装」按钮
3. **等待结果** - AI 处理约需 30-60 秒
4. **查看效果** - 主画面显示换装结果，底部显示原始画面

### 提示词使用

在右侧提示词区域输入描述，帮助 AI 生成更好的效果：

```
beautiful realistic woman, detailed skin texture, lighting, high detail
```

可选标签：可爱少女、清纯、偶像、Vtuber、写实美女、写真

## 技术架构

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   浏览器界面     │ ←→  │   FastAPI 服务器  │ ←→  │   OBS Studio    │
│  (HTML/CSS/JS)  │     │   (Python)      │     │  (WebSocket)    │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                                 ↓
                        ┌─────────────────┐
                        │   IDM-VTON      │
                        │  (Hugging Face) │
                        └─────────────────┘
```

### 文件结构

```
test60/
├── server.py           # 后端服务器
├── requirements.txt    # Python 依赖
├── .env               # 环境变量配置
├── start.bat          # Windows 启动脚本
├── static/
│   ├── index.html     # 主页面
│   ├── style.css      # 样式表
│   └── app.js         # 前端逻辑
├── uploads/           # 上传的人物图片
├── clothing/          # 上传的服装图片
└── outputs/           # 生成的结果图片
```

### API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 获取服务器状态 |
| POST | `/api/obs/connect` | 连接 OBS |
| POST | `/api/obs/disconnect` | 断开 OBS |
| POST | `/api/clothing/upload` | 上传服装图片 |
| POST | `/api/generate` | 生成换装结果 |
| GET | `/api/search/images` | 搜索图片 |
| WS | `/ws` | WebSocket 实时通信 |

## 配置说明

### OBS WebSocket

- 默认端口：4455
- 启用方式：OBS > 工具 > WebSocket 服务器设置
- 密码设置：可选，建议设置密码保护

### AI 模型

- 模型：IDM-VTON
- 来源：Hugging Face Spaces
- 处理时间：约 30-60 秒
- 图片尺寸：建议 768x1024 以内

## 常见问题

### Q: 连接 OBS 失败？

A: 检查以下项目：
- OBS 是否正在运行
- WebSocket 是否已启用
- 端口是否为 4455
- 密码是否正确

### Q: AI 换装失败？

A: 可能原因：
- 未配置 Hugging Face Token
- 网络无法访问 Hugging Face（需要 VPN）
- IDM-VTON 模型暂时不可用

### Q: 画面没有填满？

A: 刷新页面，确保浏览器窗口最大化

### Q: LIVE 指示灯不亮？

A: 需要先连接 OBS，连接成功后 LIVE 会变为粉色

## 依赖项

- Python 3.9+
- FastAPI
- uvicorn
- Pillow
- gradio_client
- websockets
- obsws-python（可选）

## 许可证

MIT License

## 相关链接

- [IDM-VTON 模型](https://huggingface.co/spaces/yisol/IDM-VTON)
- [Hugging Face Token](https://huggingface.co/settings/tokens)
- [OBS Studio](https://obsproject.com/)
- [OBS WebSocket](https://github.com/obsproject/obs-websocket)
