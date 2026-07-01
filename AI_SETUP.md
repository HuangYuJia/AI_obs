# AI 换装配置指南

## 获取 Hugging Face Token

1. 访问 https://huggingface.co/settings/tokens
2. 登录或注册账号
3. 点击 "New token" 创建新 token
4. 选择 "Read" 权限即可
5. 复制生成的 token

## 配置 Token

编辑 `.env` 文件，将 `your_token_here` 替换为你的 token：

```
HUGGINGFACE_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxx
```

## 可用的 AI 模型

### IDM-VTON (推荐)
- **地址**: https://huggingface.co/yisol/IDM-VTON
- **效果**: 高质量虚拟试穿，支持姿势变形
- **速度**: 约 10-30 秒
- **限制**: 需要清晰的全身人物照片

### 其他可选模型
- **OOTDiffusion**: https://huggingface.co/levihsu/OOTDiffusion
- **Kolors Virtual Try-On**: https://huggingface.co/Kwai-Kolors/Kolors-Virtual-Try-On

## 使用提示

1. **人物图片要求**:
   - 清晰的全身照片
   - 背景简洁
   - 正面站立姿势效果最佳

2. **服装图片要求**:
   - 平铺或模特穿着的服装图片
   - 背景干净
   - 单件服装效果最佳

3. **效果优化**:
   - 使用相似体型的人物和服装
   - 避免复杂背景
   - 图片分辨率建议 512x512 以上

## 无 Token 模式

如果不配置 token，系统会使用简单的图片叠加效果（非 AI 生成）。
