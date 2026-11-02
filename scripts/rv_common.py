#!/usr/bin/env python3
"""rv_common: 全局配置、字体、绘图小工具 (被 render.py 引用)"""
import os, sys, copy, math, hashlib
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# --------------------------------------------------------------------------- 配置
DEFAULT_STYLE = {
    "width": 1080, "height": 1920, "fps": 30,
    "cream": "#F8EDC9",          # 标题/工具名 奶油色
    "accent": "#FFD54A",         # 强调色(字幕高亮、大数字)
    "top_y": 0.19,               # 顶部信息区中心(占画面高度比例)，避开人脸
    "caption": {
        "size": 64, "y": 0.66, "color": "#FFFFFF", "stroke": "#000000",
        "stroke_width": 7, "highlight": "#FFD54A", "max_chars": 12, "font": "sans",
        "enabled": True
    },
    "zoom_center": [0.5, 0.40],  # 推镜中心(人脸大概位置)
    "auto_punch": None,          # 例 {"every_cues": 2, "scale": 1.12} 每隔N句字幕切一次景别
    "sfx_volume": 0.55,
    "bgm": None, "bgm_volume": 0.10, "bgm_duck": 0.55,
    "crf": 20, "preset": "medium",
    "fonts": {}                  # 覆盖字体 {"sans": "/path/a.ttf", "serif": "/path/b.ttc"}
}

FONT_CANDIDATES = {
    "sans": [("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
             ("/System/Library/Fonts/PingFang.ttc", 0),
             ("C:/Windows/Fonts/msyhbd.ttc", 0)],
    "sans_regular": [("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
                     ("/System/Library/Fonts/PingFang.ttc", 0),
                     ("C:/Windows/Fonts/msyh.ttc", 0)],
    "serif": [("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", 2),
              ("/System/Library/Fonts/Supplemental/Songti.ttc", 0),
              ("C:/Windows/Fonts/simsun.ttc", 0)],
}

STYLE = {}
W = H = FPS = 0
U = 1.0  # 尺寸缩放单位 (W/1080)
_font_cache = {}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def font(kind, size):
    size = max(8, int(round(size * U)))
    key = (kind, size)
    if key in _font_cache:
        return _font_cache[key]
    f = None
    custom = STYLE.get("fonts", {}).get(kind)
    cands = ([(custom, 0)] if custom else []) + FONT_CANDIDATES.get(kind, FONT_CANDIDATES["sans"])
    for path, idx in cands:
        if path and os.path.exists(path):
            try:
                f = ImageFont.truetype(path, size, index=idx)
                break
            except Exception:
                continue
    if f is None:
        log(f"[warn] 找不到字体 {kind}，使用默认字体(中文可能显示为方块)")
        f = ImageFont.load_default()
    _font_cache[key] = f
    return f


def hex2rgb(h, a=255):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def init(style_over, preview=False):
    global STYLE, W, H, FPS, U
    STYLE = deep_merge(DEFAULT_STYLE, style_over)
    W, H, FPS = STYLE["width"], STYLE["height"], STYLE["fps"]
    if preview:
        W, H = W // 2, H // 2
    W -= W % 2; H -= H % 2
    U = W / 1080.0
    _font_cache.clear()
    return STYLE


# ---------------------------------------------------------------- 缓动函数
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out_cubic(x):
    x = clamp(x); return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = clamp(x); return x * x * (3 - 2 * x)


def ease_out_back(x, s=1.9):
    x = clamp(x); x -= 1
    return 1 + (s + 1) * x ** 3 + s * x ** 2


# ---------------------------------------------------------------- 绘图小工具
def text_size(draw, txt, f, stroke=0):
    b = draw.textbbox((0, 0), txt, font=f, stroke_width=stroke)
    return b[2] - b[0], b[3] - b[1], b


def shadowed(img, radius=18, offset=(0, 10), opacity=110):
    """给RGBA图加柔和投影，返回更大的画布"""
    pad = int(radius * 2.5)
    w, h = img.size
    canvas = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    alpha = img.split()[3].point(lambda a: a * opacity // 255)
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0)); sh.putalpha(alpha)
    canvas.paste(sh, (pad + offset[0], pad + offset[1]), sh)
    canvas = canvas.filter(ImageFilter.GaussianBlur(radius))
    canvas.alpha_composite(img, (pad, pad))
    return canvas


def rounded_mask(size, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], r, fill=255)
    return m


def color_from_text(t):
    """无图标时，根据名字生成稳定的品牌色"""
    hsh = int(hashlib.md5(t.encode("utf-8")).hexdigest()[:6], 16)
    import colorsys
    r, g, b = colorsys.hls_to_rgb((hsh % 360) / 360.0, 0.55, 0.65)
    return "#%02X%02X%02X" % (int(r * 255), int(g * 255), int(b * 255))
