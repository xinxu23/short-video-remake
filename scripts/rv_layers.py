"""rv_layers: 每种包装元素(标题/数据徽章/工具卡/画中画/大字/字幕)的精灵图生成与入场动画"""
import os, math
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageOps
import rv_common as C
from rv_common import font, hex2rgb, text_size, shadowed, rounded_mask, ease_out_back, ease_out_cubic, clamp

IN_DUR = 0.28    # 入场动画时长(秒)
OUT_DUR = 0.18   # 出场动画时长(秒)


# ======================================================================= 精灵图
def _load_img(path, base_dir):
    if not path:
        return None
    p = path if os.path.isabs(path) else os.path.join(base_dir, path)
    if not os.path.exists(p):
        C.log(f"[warn] 找不到图片 {p}，用占位图代替")
        return None
    return Image.open(p).convert("RGBA")


def _cream_text(lines, sizes, kind="serif", color=None, line_gap=0.02):
    """多行居中文字 + 柔和投影，返回RGBA"""
    color = hex2rgb(color or C.STYLE["cream"])
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    rows = []
    for txt, sz in zip(lines, sizes):
        f = font(kind, sz)
        w, h, b = text_size(tmp, txt, f)
        rows.append((txt, f, w, h, b))
    gap = int(C.H * line_gap)
    tw = max(r[2] for r in rows) + 30
    th = sum(r[3] for r in rows) + gap * (len(rows) - 1) + 30
    img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 10
    sw = max(1, int(C.STYLE.get("text_stroke", 3) * C.U))
    stroke = hex2rgb(C.STYLE.get("text_stroke_color", "#3B2A1E"), 210)
    for txt, f, w, h, b in rows:
        d.text(((tw - w) // 2 - b[0], y - b[1]), txt, font=f, fill=color, stroke_width=sw, stroke_fill=stroke)
        y += h + gap
    return shadowed(img, radius=int(12 * C.U), offset=(0, int(5 * C.U)), opacity=200)


def sprite_title(ev, base_dir):
    lines = ev.get("lines") or [ev.get("text", "")]
    sizes = ev.get("sizes") or [96] * len(lines)
    img = _cream_text(lines, sizes, ev.get("font", "serif"), ev.get("color"))
    if ev.get("sub"):
        sub = _cream_text([ev["sub"]], [ev.get("sub_size", 34)], "sans_regular", ev.get("color"))
        w = max(img.width, sub.width)
        out = Image.new("RGBA", (w, img.height + sub.height - int(30 * C.U)), (0, 0, 0, 0))
        out.alpha_composite(img, ((w - img.width) // 2, 0))
        out.alpha_composite(sub, ((w - sub.width) // 2, img.height - int(30 * C.U)))
        img = out
    return img


def _avatar(item, base_dir, size):
    im = _load_img(item.get("avatar"), base_dir)
    if im is None:
        im = Image.new("RGBA", (size, size), hex2rgb(item.get("color") or C.color_from_text(item.get("name", "?"))))
        d = ImageDraw.Draw(im)
        ch = (item.get("initial") or item.get("name", "?")[:1])
        f = font("sans", size * 0.5 / C.U)
        w, h, b = text_size(d, ch, f)
        d.text(((size - w) / 2 - b[0], (size - h) / 2 - b[1]), ch, font=f, fill=(255, 255, 255, 255))
    im = ImageOps.fit(im, (size, size))
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).ellipse([0, 0, size - 1, size - 1], fill=255)
    im.putalpha(Image.fromarray(np.minimum(np.array(im.split()[3]), np.array(m))))
    return im


def sprite_badge(item, base_dir):
    """单个数据徽章：深色圆角卡 + 圆头像 + 小字名称 + 大字数值"""
    u = C.U
    av = int(84 * u)
    f_name, f_val = font("sans_regular", 26), font("sans", 50)
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    nw, nh, nb = text_size(tmp, item.get("name", ""), f_name)
    vw, vh, vb = text_size(tmp, item.get("value", ""), f_val)
    pad = int(22 * u)
    w = pad + av + pad + max(nw, vw) + pad * 2
    h = max(av, nh + vh + int(10 * u)) + pad * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], int(14 * u), fill=hex2rgb(item.get("bg", "#111111"), 235))
    img.alpha_composite(_avatar(item, base_dir, av), (pad, (h - av) // 2))
    tx = pad * 2 + av
    ty = (h - (nh + vh + int(10 * u))) // 2
    d.text((tx - nb[0], ty - nb[1]), item.get("name", ""), font=f_name, fill=(230, 230, 230, 255))
    d.text((tx - vb[0], ty + nh + int(10 * u) - vb[1]), item.get("value", ""), font=f_val, fill=(255, 255, 255, 255))
    return shadowed(img, radius=int(14 * u), opacity=120)


def _icon(ev, base_dir, size):
    im = _load_img(ev.get("icon"), base_dir)
    r = int(size * 0.225)
    if im is None:
        col = ev.get("color") or C.color_from_text(ev.get("name", "?"))
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        top, bot = np.array(hex2rgb(col)[:3]), np.array(hex2rgb(col)[:3]) * 0.72
        for y in range(size):  # 竖向渐变
            c = tuple(int(v) for v in top + (bot - top) * y / size) + (255,)
            d.line([(0, y), (size, y)], fill=c)
        ch = ev.get("initial") or ev.get("name", "?")[:1]
        f = font("sans", size * 0.52 / C.U)
        w, h, b = text_size(d, ch, f)
        d.text(((size - w) / 2 - b[0], (size - h) / 2 - b[1]), ch, font=f, fill=(255, 255, 255, 255))
    else:
        im = ImageOps.fit(im, (size, size))
    a = np.minimum(np.array(im.split()[3]), np.array(rounded_mask((size, size), r)))
    im.putalpha(Image.fromarray(a))
    return im


def sprite_tool(ev, base_dir):
    """工具卡：App图标 + 下方衬线奶油色名称"""
    u = C.U
    size = int(ev.get("icon_size", 150) * u)
    icon = _icon(ev, base_dir, size)
    name = _cream_text([ev.get("name", "")], [ev.get("size", 66)], ev.get("font", "serif"), ev.get("color"))
    parts = [shadowed(icon, radius=int(12 * u), opacity=100), name]
    if ev.get("desc"):
        parts.append(_cream_text([ev["desc"]], [32], "sans_regular", "#FFFFFF"))
    w = max(p.width for p in parts)
    gap = -int(40 * u)
    h = sum(p.height for p in parts) + gap * (len(parts) - 1)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    y = 0
    for p in parts:
        out.alpha_composite(p, ((w - p.width) // 2, y)); y += p.height + gap
    return out


def sprite_bigtext(ev, base_dir):
    return _cream_text([ev.get("text", "")], [ev.get("size", 120)], ev.get("font", "serif"),
                       ev.get("color") or C.STYLE["cream"])


def pip_frame_box(ev):
    """画中画的内容尺寸(不含边框)"""
    u = C.U
    w = int(ev.get("width", 0.62) * C.W)
    h = int(w * ev.get("aspect", 0.62))
    return w, h


def pip_decorate(content, ev):
    """白色描边 + 投影 + 可选标签"""
    u = C.U
    bd = int(ev.get("border", 6) * u)
    w, h = content.size
    card = Image.new("RGBA", (w + bd * 2, h + bd * 2), hex2rgb(ev.get("border_color", "#FFFFFF")))
    card.paste(content.convert("RGB"), (bd, bd))
    card = shadowed(card, radius=int(18 * u), opacity=120)
    if ev.get("label"):
        lab = _cream_text([ev["label"]], [ev.get("label_size", 50)], ev.get("label_font", "serif"), ev.get("label_color"))
        out = Image.new("RGBA", (max(card.width, lab.width), card.height + lab.height - int(70 * u)), (0, 0, 0, 0))
        out.alpha_composite(card, ((out.width - card.width) // 2, 0))
        out.alpha_composite(lab, ((out.width - lab.width) // 2, card.height - int(70 * u)))
        return out
    return card


def placeholder_shot(w, h, text):
    im = Image.new("RGB", (w, h), (236, 236, 240))
    d = ImageDraw.Draw(im)
    for i in range(0, w + h, int(36 * C.U)):
        d.line([(i, 0), (i - h, h)], fill=(224, 224, 230), width=int(10 * C.U))
    f = font("sans", 40)
    tw, th, b = text_size(d, text, f)
    d.text(((w - tw) / 2 - b[0], (h - th) / 2 - b[1]), text, font=f, fill=(120, 120, 130))
    return im


# ======================================================================= 动画
def anim_state(kind, t, start, end, style="pop"):
    """返回 (scale, alpha, dx, dy)；dx,dy 是像素偏移"""
    if t < start or t > end:
        return None
    a_in = clamp((t - start) / IN_DUR)
    a_out = clamp((end - t) / OUT_DUR)
    s, alpha, dx, dy = 1.0, 1.0, 0.0, 0.0
    if style == "pop":            # 弹出 (工具卡、大字)
        s = 0.35 + 0.65 * ease_out_back(a_in)
        alpha = clamp(a_in * 3)
    elif style == "rise":         # 上浮淡入 (画中画、标题)
        dy = (1 - ease_out_cubic(a_in)) * 70 * C.U
        alpha = ease_out_cubic(a_in)
        s = 0.94 + 0.06 * ease_out_cubic(a_in)
    elif style == "slide":        # 从左滑入 (数据徽章)
        dx = -(1 - ease_out_cubic(a_in)) * 160 * C.U
        alpha = ease_out_cubic(a_in)
    elif style == "cut":
        pass
    alpha *= ease_out_cubic(a_out)
    s *= 0.92 + 0.08 * a_out
    return s, alpha, dx, dy


def blit(frame, spr, cx, cy, scale=1.0, alpha=1.0):
    """把 RGBA 精灵(np.uint8 HxWx4)以中心点(cx,cy)合成到 frame(HxWx3 uint8) 上"""
    if alpha <= 0.003:
        return
    if abs(scale - 1.0) > 0.004:
        h0, w0 = spr.shape[:2]
        nw, nh = max(1, int(w0 * scale)), max(1, int(h0 * scale))
        spr = cv2.resize(spr, (nw, nh), interpolation=cv2.INTER_LINEAR if scale > 1 else cv2.INTER_AREA)
    h, w = spr.shape[:2]
    x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
    fx0, fy0 = max(0, x0), max(0, y0)
    fx1, fy1 = min(frame.shape[1], x0 + w), min(frame.shape[0], y0 + h)
    if fx1 <= fx0 or fy1 <= fy0:
        return
    s = spr[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0]
    a = s[:, :, 3:4].astype(np.uint16)
    if alpha < 0.999:
        a = (a * int(alpha * 256)) >> 8
    dst = frame[fy0:fy1, fx0:fx1]
    dst[:] = ((s[:, :, :3].astype(np.uint16) * a + dst.astype(np.uint16) * (255 - a)) // 255).astype(np.uint8)


def to_np(img):
    return np.array(img.convert("RGBA"))


# ======================================================================= 字幕
def split_caption(text, max_chars):
    """把一句字幕切成不超过 max_chars 的若干小段(优先在标点处断)"""
    text = text.strip()
    parts, buf = [], ""
    for ch in text:
        buf += ch
        if ch in "，。！？、；,.!?;" and len(buf) >= 3:
            parts.append(buf); buf = ""
        elif len(buf) >= max_chars:
            parts.append(buf); buf = ""
    if buf:
        parts.append(buf)
    clean = []
    for p in parts:
        p = p.strip().rstrip("，。、；,.;")
        if p:
            clean.append(p)
    return clean or [text]


def sprite_caption(text, keywords):
    cs = C.STYLE["caption"]
    f = font(cs.get("font", "sans"), cs["size"])
    sw = int(cs["stroke_width"] * C.U)
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    tw, th, b = text_size(tmp, text, f, sw)
    img = Image.new("RGBA", (tw + sw * 4, th + sw * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 标记高亮字符
    hl = [False] * len(text)
    for kw in keywords or []:
        i = text.find(kw)
        while kw and i >= 0:
            for j in range(i, i + len(kw)):
                hl[j] = True
            i = text.find(kw, i + len(kw))
    x = sw * 2 - b[0]
    y = sw * 2 - b[1]
    # 第一遍画描边，第二遍画字，避免后一个字的描边盖住前一个字
    xs = []
    for ch in text:
        xs.append(x)
        x += d.textlength(ch, font=f)
    for ch, cx in zip(text, xs):
        d.text((cx, y), ch, font=f, fill=hex2rgb(cs["stroke"]), stroke_width=sw, stroke_fill=hex2rgb(cs["stroke"]))
    for i, (ch, cx) in enumerate(zip(text, xs)):
        col = hex2rgb(cs["highlight"] if hl[i] else cs["color"])
        d.text((cx, y), ch, font=f, fill=col)
    return img.crop(img.getbbox()) if img.getbbox() else img
