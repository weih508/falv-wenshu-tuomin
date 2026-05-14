# -*- coding: utf-8 -*-
"""
法律文书脱敏工具 - 文件处理模块
支持格式：PDF、图片(PNG/JPG/BMP/TIFF)、Word(.docx)、文本(.txt)
内置 RapidOCR 引擎（基于PaddleOCR ONNX模型），无需额外安装外部程序
"""

import os
import sys
import io
import tempfile
from typing import Tuple, Optional
from pathlib import Path

# 在导入onnxruntime之前设置多线程环境变量
_cpu_count = os.cpu_count() or 4
os.environ.setdefault('OMP_NUM_THREADS', str(_cpu_count))
os.environ.setdefault('ORT_THREADS', str(_cpu_count))

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    RapidOCR = None

try:
    from docx import Document
except ImportError:
    Document = None

try:
    import chardet
except ImportError:
    chardet = None


def get_resource_path(relative_path):
    """获取资源文件路径（兼容PyInstaller打包）"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', relative_path)


class OCREngine:
    """内置OCR引擎 - 基于RapidOCR(ONNX)，无需外部依赖"""

    _instance = None

    @classmethod
    def get_instance(cls):
        """单例模式，避免重复加载模型"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._ocr = None

    def _init_ocr(self):
        """延迟初始化OCR引擎（已优化速度）"""
        if self._ocr is None:
            if RapidOCR is None:
                raise ImportError(
                    "RapidOCR 未安装，请运行: pip install rapidocr-onnxruntime"
                )
            # 性能优化：
            # 1. 关闭文字方向分类（法律文书不会倒置），节省约30%时间
            # 2. 检测限制用max模式，避免小图被放大
            # 3. 设置ONNX Runtime多线程加速
            
            # Monkey-patch OrtInferSession以启用多线程
            self._patch_ort_threading()
            
            self._ocr = RapidOCR(
                use_angle_cls=False,        # 跳过方向分类模型，节省30%时间
            )

    @staticmethod
    def _patch_ort_threading():
        """修补ONNX Runtime会话选项，启用多线程"""
        try:
            from onnxruntime import SessionOptions, GraphOptimizationLevel, InferenceSession
            from rapidocr_onnxruntime.utils import OrtInferSession
            
            cpu_count = min(os.cpu_count() or 4, 8)  # 最多用8线程
            _orig_init = OrtInferSession.__init__
            
            def _fast_init(self, config):
                sess_opt = SessionOptions()
                sess_opt.log_severity_level = 4
                sess_opt.enable_cpu_mem_arena = True
                sess_opt.graph_optimization_level = GraphOptimizationLevel.ORT_ENABLE_ALL
                sess_opt.intra_op_num_threads = cpu_count
                sess_opt.inter_op_num_threads = cpu_count
                
                cpu_ep = 'CPUExecutionProvider'
                EP_list = [(cpu_ep, {'arena_extend_strategy': 'kSameAsRequested'})]
                
                self._verify_model(config['model_path'])
                self.session = InferenceSession(
                    config['model_path'],
                    sess_options=sess_opt,
                    providers=EP_list
                )
            
            OrtInferSession.__init__ = _fast_init
        except Exception:
            pass  # 如果patch失败，使用默认配置

    def _resize_if_large(self, image_input):
        """如果图片过大，缩小以加速OCR"""
        import numpy as np
        
        MAX_SIDE = 1200  # 最佳速度/精度平衡点
        
        if isinstance(image_input, str):
            # 文件路径，用PIL打开检查大小
            img = Image.open(image_input)
            w, h = img.size
            if max(w, h) > MAX_SIDE:
                ratio = MAX_SIDE / max(w, h)
                new_w, new_h = int(w * ratio), int(h * ratio)
                img = img.resize((new_w, new_h), Image.LANCZOS)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            return np.array(img)
        elif isinstance(image_input, np.ndarray):
            h, w = image_input.shape[:2]
            if max(w, h) > MAX_SIDE:
                ratio = MAX_SIDE / max(w, h)
                new_w, new_h = int(w * ratio), int(h * ratio)
                img = Image.fromarray(image_input)
                img = img.resize((new_w, new_h), Image.LANCZOS)
                return np.array(img)
            return image_input
        return image_input

    def recognize(self, image_input) -> str:
        """
        识别图片中的文字，保留原始排版格式
        
        Args:
            image_input: 图片文件路径(str)或numpy数组
            
        Returns:
            识别出的文本（保留段落间距和缩进）
        """
        self._init_ocr()
        
        # 缩小大图以加速
        image_input = self._resize_if_large(image_input)
        
        result, elapse = self._ocr(image_input)
        
        if not result:
            return ''
        
        # RapidOCR返回格式: [[box, text, confidence], ...]
        lines = []
        for item in result:
            if len(item) >= 3:
                box = item[0]       # 文字框坐标 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                text = item[1]      # 识别文本
                confidence = item[2]  # 置信度
                
                # 确保置信度为数值类型
                try:
                    conf_val = float(confidence)
                except (TypeError, ValueError):
                    conf_val = 1.0
                
                if conf_val > 0.3 and text.strip():
                    y_pos = float(box[0][1])
                    x_pos = float(box[0][0])
                    # 计算行高（用于判断段落间距）
                    line_height = float(box[3][1]) - float(box[0][1])
                    lines.append((y_pos, x_pos, text.strip(), line_height))
        
        if not lines:
            return ''
        
        # 按y坐标排序
        lines.sort(key=lambda x: (x[0], x[1]))
        
        # 将相近y坐标的文本合并为一行
        merged_lines = []  # [(y_pos, x_pos, text, line_height)]
        current_line = [lines[0]]
        y_threshold = 15  # y坐标差距小于15像素认为同一行
        
        for i in range(1, len(lines)):
            if abs(lines[i][0] - current_line[-1][0]) < y_threshold:
                current_line.append(lines[i])
            else:
                current_line.sort(key=lambda x: x[1])
                avg_y = sum(item[0] for item in current_line) / len(current_line)
                min_x = min(item[1] for item in current_line)
                avg_height = sum(item[3] for item in current_line) / len(current_line)
                merged_text = ' '.join(item[2] for item in current_line)
                merged_lines.append((avg_y, min_x, merged_text, avg_height))
                current_line = [lines[i]]
        
        # 处理最后一行
        current_line.sort(key=lambda x: x[1])
        avg_y = sum(item[0] for item in current_line) / len(current_line)
        min_x = min(item[1] for item in current_line)
        avg_height = sum(item[3] for item in current_line) / len(current_line)
        merged_text = ' '.join(item[2] for item in current_line)
        merged_lines.append((avg_y, min_x, merged_text, avg_height))
        
        if not merged_lines:
            return ''
        
        # 根据行间距还原段落格式
        # 计算基准左边距（大部分行的x起始位置）
        x_positions = [line[1] for line in merged_lines]
        base_x = min(x_positions) if x_positions else 0
        
        output_lines = []
        for i, (y, x, text, height) in enumerate(merged_lines):
            # 计算缩进（相对于基准左边距的空格数）
            indent = ''
            if x - base_x > 20:  # 超过20像素认为有缩进
                indent_chars = int((x - base_x) / 12)  # 大约12像素一个字符宽
                indent = '  ' * min(indent_chars, 8)  # 最多8级缩进
            
            # 判断是否需要额外空行（段落间距）
            if i > 0:
                prev_y = merged_lines[i-1][0]
                prev_height = merged_lines[i-1][3]
                gap = y - prev_y
                # 如果行间距大于1.8倍行高，认为是段落分隔
                if gap > prev_height * 1.8:
                    output_lines.append('')  # 插入空行表示段落分隔
            
            output_lines.append(indent + text)
        
        return '\n'.join(output_lines)

    def recognize_from_pil(self, pil_image) -> str:
        """
        从PIL Image对象识别文字
        
        Args:
            pil_image: PIL Image对象
            
        Returns:
            识别出的文本
        """
        import numpy as np
        
        if pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')
        
        img_array = np.array(pil_image)
        return self.recognize(img_array)


class FileHandler:
    """文件处理器 - 支持多种格式的文本提取"""

    SUPPORTED_EXTENSIONS = {
        'pdf': ['.pdf'],
        'image': ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif'],
        'word': ['.docx', '.doc'],
        'text': ['.txt', '.csv', '.log', '.md']
    }

    def __init__(self):
        """初始化文件处理器（OCR引擎内置，无需配置）"""
        self._ocr_engine = None

    @property
    def ocr_engine(self):
        """延迟加载OCR引擎"""
        if self._ocr_engine is None:
            self._ocr_engine = OCREngine.get_instance()
        return self._ocr_engine

    @classmethod
    def get_file_type(cls, filename: str) -> Optional[str]:
        """根据文件扩展名判断文件类型"""
        ext = Path(filename).suffix.lower()
        for file_type, extensions in cls.SUPPORTED_EXTENSIONS.items():
            if ext in extensions:
                return file_type
        return None

    @classmethod
    def is_supported(cls, filename: str) -> bool:
        """检查文件是否支持"""
        return cls.get_file_type(filename) is not None

    def extract_text(self, file_path: str) -> Tuple[str, str]:
        """
        从文件中提取文本
        
        Args:
            file_path: 文件路径
            
        Returns:
            (提取的文本, 文件类型)
        """
        file_type = self.get_file_type(file_path)
        if file_type is None:
            raise ValueError(f"不支持的文件格式: {Path(file_path).suffix}")

        if file_type == 'pdf':
            return self._extract_from_pdf(file_path), 'pdf'
        elif file_type == 'image':
            return self._extract_from_image(file_path), 'image'
        elif file_type == 'word':
            return self._extract_from_word(file_path), 'word'
        elif file_type == 'text':
            return self._extract_from_text(file_path), 'text'
        else:
            raise ValueError(f"不支持的文件类型: {file_type}")

    def extract_text_from_bytes(self, file_bytes: bytes, filename: str) -> Tuple[str, str]:
        """
        从文件字节流中提取文本
        """
        file_type = self.get_file_type(filename)
        if file_type is None:
            raise ValueError(f"不支持的文件格式: {Path(filename).suffix}")

        suffix = Path(filename).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            text, ftype = self.extract_text(tmp_path)
            return text, ftype
        finally:
            os.unlink(tmp_path)

    def _extract_from_pdf(self, file_path: str) -> str:
        """从PDF文件提取文本"""
        if fitz is None:
            raise ImportError("请安装 PyMuPDF: pip install pymupdf")

        text_parts = []
        doc = fitz.open(file_path)

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = page.get_text("text")

            # 如果页面文本为空或极少，尝试OCR识别（可能是扫描件）
            if not page_text.strip() or len(page_text.strip()) < 10:
                try:
                    import numpy as np
                    # 直接渲染为适合OCR的大小，无需过大
                    mat = fitz.Matrix(1.2, 1.2)
                    pix = page.get_pixmap(matrix=mat)
                    img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                        pix.height, pix.width, pix.n
                    )
                    # 如果有alpha通道，转为RGB
                    if pix.n == 4:
                        img_array = img_array[:, :, :3]
                    ocr_text = self.ocr_engine.recognize(img_array)
                    if ocr_text.strip():
                        page_text = ocr_text
                except Exception:
                    pass

            if page_text.strip():
                text_parts.append(f"--- 第 {page_num + 1} 页 ---\n{page_text}")

        doc.close()
        return '\n\n'.join(text_parts)

    def _extract_from_image(self, file_path: str) -> str:
        """从图片文件提取文本（内置OCR）"""
        if Image is None:
            raise ImportError("请安装 Pillow: pip install Pillow")

        return self.ocr_engine.recognize(file_path)

    def _extract_from_word(self, file_path: str) -> str:
        """从Word文件提取文本（保留段落格式）"""
        if Document is None:
            raise ImportError("请安装 python-docx: pip install python-docx")

        doc = Document(file_path)
        text_parts = []

        # 保留所有段落，包括空行（段落间距）
        for para in doc.paragraphs:
            text_parts.append(para.text)

        # 表格内容追加在后面
        for table in doc.tables:
            for row in table.rows:
                row_text = ' | '.join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    text_parts.append(row_text)

        return '\n'.join(text_parts)

    def _extract_from_text(self, file_path: str) -> str:
        """从纯文本文件提取文本"""
        with open(file_path, 'rb') as f:
            raw_data = f.read()

        if chardet:
            detected = chardet.detect(raw_data)
            encoding = detected.get('encoding', 'utf-8')
        else:
            encoding = 'utf-8'

        try:
            return raw_data.decode(encoding)
        except (UnicodeDecodeError, TypeError):
            return raw_data.decode('utf-8', errors='replace')


class PDFRedactor:
    """PDF脱敏输出器 - 生成脱敏后的PDF"""

    @staticmethod
    def create_redacted_pdf(original_path: str, redacted_text: str, output_path: str):
        """创建脱敏后的PDF文件"""
        if fitz is None:
            raise ImportError("请安装 PyMuPDF: pip install pymupdf")

        doc = fitz.open()
        pages = redacted_text.split('--- 第')
        
        for page_content in pages:
            if not page_content.strip():
                continue
            
            lines = page_content.split('\n')
            if lines and '页 ---' in lines[0]:
                lines = lines[1:]
            
            content = '\n'.join(lines).strip()
            if not content:
                continue
            
            page = doc.new_page(width=595, height=842)
            text_writer = fitz.TextWriter(page.rect)
            font = fitz.Font("china-s")
            
            y_pos = 50
            for line in content.split('\n'):
                if y_pos > 790:
                    page = doc.new_page(width=595, height=842)
                    text_writer = fitz.TextWriter(page.rect)
                    y_pos = 50
                
                try:
                    text_writer.append((50, y_pos), line, font=font, fontsize=11)
                except Exception:
                    text_writer.append((50, y_pos), line.encode('ascii', 'replace').decode(), fontsize=11)
                y_pos += 18
            
            text_writer.write_text(page)
        
        doc.save(output_path)
        doc.close()
