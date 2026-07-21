"""视觉工具：YOLO11 物体检测 + EasyOCR 文字识别 + 加权焦点计算。

移植自桌面平行实现的 pics/yolo_detector.py，为接入多智能体图做了三点精进：
1. 去掉标注绘图（智能体只需结构化结果，不需要画框图；前端演示需要时再单独加）；
2. 所有重依赖（cv2 / numpy / ultralytics / easyocr）改为带守卫的惰性导入——
   没装视觉依赖时 import 本模块不会报错，`vision_available()` 返回 False，
   上层 vision_agent 据此自动降级（对应 ADR-008 降级阶梯）；
3. 模型只加载一次（模块级缓存），避免每张图重复加载。

装依赖：pip install -r requirements-vision.txt
首次运行会自动下载 YOLO 权重（~5MB）与 OCR 语言模型（~100MB）。
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Optional

try:  # 基础图像栈：缺了就整体降级
    import cv2
    import numpy as np
    _CV_OK = True
except Exception:  # pragma: no cover - 取决于环境是否装了 opencv
    _CV_OK = False

# COCO 80 类里与"商品/带货"较相关的类别，命中可作为导购场景的弱信号
_COMMERCIAL_HINT_CLASSES = {
    "bottle", "cup", "handbag", "backpack", "cell phone", "laptop",
    "book", "clock", "vase", "wine glass", "tie", "suitcase",
}

_MODELS = {"nano": "yolo11n.pt", "small": "yolo11s.pt", "medium": "yolo11m.pt",
           "large": "yolo11l.pt", "xlarge": "yolo11x.pt"}


def vision_available() -> bool:
    """视觉核心依赖（opencv + ultralytics）是否就绪。OCR 单独可选。"""
    if not _CV_OK:
        return False
    import importlib.util
    return importlib.util.find_spec("ultralytics") is not None


def _cuda() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


class _Detector:
    """YOLO11 物体检测 + 加权焦点。"""

    def __init__(self, model_size: str = "nano", conf: float = 0.25,
                 iou: float = 0.7, max_det: int = 300, imgsz: int = 640,
                 device: Optional[str] = None):
        from ultralytics import YOLO  # 惰性导入
        self.model_size = model_size
        self.conf, self.iou, self.max_det, self.imgsz = conf, iou, max_det, imgsz
        self.device = device or ("cuda" if _cuda() else "cpu")
        self.model = YOLO(_MODELS.get(model_size, "yolo11n.pt"))
        self.class_names = self.model.names

    def detect(self, image_path: str) -> list[dict]:
        results = self.model(image_path, conf=self.conf, iou=self.iou,
                             max_det=self.max_det, imgsz=self.imgsz,
                             device=self.device, verbose=False)
        out: list[dict] = []
        for r in results:
            for box in (r.boxes or []):
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                cls = int(box.cls[0])
                out.append({
                    "bbox": [x1, y1, x2, y2],
                    "confidence": round(float(box.conf[0]), 3),
                    "class_id": cls,
                    "class_name": self.class_names.get(cls, f"class_{cls}"),
                    "center": [(x1 + x2) // 2, (y1 + y2) // 2],
                })
        return out

    def focus(self, image_path: str, detections: list[dict]) -> dict:
        img = cv2.imread(str(image_path))
        if img is None:
            return {}
        h, w = img.shape[:2]
        if not detections:
            return {"focus_point": [w // 2, h // 2], "confidence": 0.0,
                    "method": "center_fallback", "num_objects": 0}
        # 焦点 = 各框中心按 置信度×√面积 加权平均
        wx = wy = tw = 0.0
        for d in detections:
            x1, y1, x2, y2 = d["bbox"]
            weight = d["confidence"] * float(np.sqrt(max((x2 - x1) * (y2 - y1), 1)))
            wx += d["center"][0] * weight
            wy += d["center"][1] * weight
            tw += weight
        fx, fy = (int(wx / tw), int(wy / tw)) if tw > 0 else (w // 2, h // 2)
        avg = float(np.mean([d["confidence"] for d in detections]))
        return {"focus_point": [fx, fy], "confidence": round(avg, 3),
                "method": "weighted_center", "num_objects": len(detections)}


class _OCR:
    """EasyOCR 中英文识别。"""

    def __init__(self, languages: Optional[list[str]] = None):
        import easyocr  # 惰性导入
        self.reader = easyocr.Reader(languages or ["ch_sim", "en"], gpu=_cuda())

    def recognize(self, image_path: str) -> list[dict]:
        img = cv2.imread(str(image_path))
        if img is None:
            return []
        # 转 RGB 并直接传 ndarray，规避 easyocr 内部 shape 解包 bug
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        out: list[dict] = []
        for bbox, text, conf in self.reader.readtext(img_rgb):
            pts = np.array(bbox, dtype=np.int32)
            x, y, bw, bh = cv2.boundingRect(pts)
            out.append({"text": text, "confidence": round(float(conf), 3),
                        "bbox": [int(x), int(y), int(x + bw), int(y + bh)]})
        return out


class ImageAnalyzer:
    """整合物体检测 + OCR + 焦点，产出结构化结果字典。"""

    def __init__(self, model_size: str = "nano", enable_ocr: bool = True,
                 conf: float = 0.25, device: Optional[str] = None):
        if not vision_available():
            raise RuntimeError("视觉依赖未安装：pip install -r requirements-vision.txt")
        self.detector = _Detector(model_size=model_size, conf=conf, device=device)
        self.ocr = None
        if enable_ocr:
            try:
                self.ocr = _OCR()
            except Exception:
                self.ocr = None  # easyocr 缺失/加载失败 → 只做物体检测

    def _resize_if_needed(self, image_path: Path, max_w: int = 1920, max_h: int = 1080) -> Path:
        img = cv2.imread(str(image_path))
        if img is None:
            return image_path
        h, w = img.shape[:2]
        if w <= max_w and h <= max_h:
            return image_path
        scale = min(max_w / w, max_h / h)
        resized = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        tmp_dir = image_path.parent / ".resized"
        tmp_dir.mkdir(exist_ok=True)
        tmp = tmp_dir / image_path.name
        cv2.imwrite(str(tmp), resized)
        return tmp

    def analyze(self, image_path: str) -> dict[str, Any]:
        p = Path(image_path)
        if not p.exists():
            raise FileNotFoundError(f"图片不存在: {p}")
        p = self._resize_if_needed(p)
        detections = self.detector.detect(str(p))
        focus = self.detector.focus(str(p), detections)
        texts = self.ocr.recognize(str(p)) if self.ocr else []
        return {
            "image_name": p.name,
            "model": f"YOLO11{self.detector.model_size}",
            "objects": detections,
            "focus": focus,
            "texts": texts,
        }


# ── 模块级缓存：模型只加载一次 ────────────────────────────────────────
_CACHE: dict[tuple, ImageAnalyzer] = {}


def get_analyzer(model_size: str = "nano", enable_ocr: bool = True) -> ImageAnalyzer:
    key = (model_size, enable_ocr)
    if key not in _CACHE:
        _CACHE[key] = ImageAnalyzer(model_size=model_size, enable_ocr=enable_ocr)
    return _CACHE[key]


def analyze_image(image_path: str, model_size: str = "nano", enable_ocr: bool = True) -> dict[str, Any]:
    """便捷入口：分析单张图片，返回 {objects, focus, texts, ...}。"""
    return get_analyzer(model_size, enable_ocr).analyze(image_path)


def commercial_objects(objects: list[dict]) -> list[str]:
    """挑出与带货相关的物体类别（去重保序），作为导购场景弱信号。"""
    seen, out = set(), []
    for o in objects:
        name = o.get("class_name", "")
        if name in _COMMERCIAL_HINT_CLASSES and name not in seen:
            seen.add(name)
            out.append(name)
    return out
