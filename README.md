# 法律文书脱敏工具

一款面向律师和法律工作者的文书脱敏审查工具，支持自动检测并脱敏法律文书中的敏感信息。

## 功能特性

- **多格式支持**：PDF、图片（PNG/JPG/BMP/TIFF）、Word (.docx)、纯文本
- **11类敏感信息检测**：姓名、身份证号、手机号、银行卡号、地址、公司名称、日期、金额、邮箱、案号、律师执业证号
- **内置离线OCR**：基于 RapidOCR + ONNX Runtime，无需联网即可识别图片和扫描PDF
- **智能验证**：身份证校验位验证、银行卡Luhn校验、姓氏库匹配、已知实体传播
- **选择性脱敏**：可勾选/取消勾选具体检测项，灵活控制脱敏范围
- **多种导出格式**：Markdown、PDF、Word（保留原格式）
- **免安装使用**：打包为独立EXE，双击即用

## 使用方式

### 直接运行源码

```bash
pip install flask pymupdf python-docx rapidocr-onnxruntime chardet pillow opencv-python-headless
python app.py
```

浏览器自动打开 `http://127.0.0.1:5000`

### 打包为EXE

```bash
pip install pyinstaller==6.20.0
python -m PyInstaller --clean --noconfirm build_exe.spec
```

生成文件在 `dist/法律文书脱敏工具/` 目录下，双击 `法律文书脱敏工具.exe` 运行。

## 项目结构

```
├── app.py                  # Flask主程序
├── build_exe.spec          # PyInstaller打包配置
├── desensitizer/
│   ├── __init__.py
│   ├── detector.py         # 敏感信息检测引擎
│   └── file_handler.py     # 文件解析 + OCR引擎
├── templates/
│   └── index.html          # Web界面
└── static/                 # 静态资源
```

## 技术栈

- 后端：Flask + PyMuPDF + python-docx
- OCR：RapidOCR (ONNX Runtime)
- 前端：原生HTML/CSS/JS（单页应用）
- 打包：PyInstaller（单文件夹模式）

## License

MIT
