#!/usr/bin/env python3
"""
render.py  口播视频 + SRT字幕 + timeline.json  →  带包装动画的竖屏成片

用法:
  python render.py timeline.json                  渲染成片
  python render.py timeline.json --preview        540x960 快速预览
  python render.py timeline.json --stills events  导出每个包装元素出现时的画面PNG(检查用)
  python render.py timeline.json --stills 1.5,8   导出指定秒数的画面

timeline.json 写法见 references/timeline_schema.md
依赖: ffmpeg, numpy, opencv-python, pillow
"""
import argparse, json, os, re, subprocess, sys, wave, tempfile, shutil
import numpy as np
import cv2
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rv_common as C
import rv_layers as L
from rv_common import clamp, ease_in_out, log

TOP_TYPES = {"title", "badges", "tool", "pip", "bigtext"}   # 共用顶部信息区，互斥
SR = 48000


# ======================================================================= SRT
def parse_srt(path):
    if not path or not os.path.exists(path):
        return []
    raw = open(path, encoding="utf-8-sig").read().replace("\r", "")
    cues = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        for i, l in enumerate(lines):
            m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", l)
            if m:
                g = [int(x) for x in m.groups()]
                s = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                e = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                text = "".join(lines[i + 1:]).strip()
                if text:
                    cues.append({"start": s, "end": e, "text": text})
                break
    return cues


def caption_segments(cues, max_chars):
    """每条字幕拆成短句，按字数比例分配时间"""
    segs = []
    for c in cues:
        parts = L.split_caption(c["text"], max_chars)
        total = sum(len(p) for p in parts)
        t = c["start"]
        for p in parts:
            d = (c["end"] - c["start"]) * len(p) / total
            segs.append({"start": t, "end": t + d, "text": p})
            t += d
    return segs


# ======================================================================= 时间线解析
def resolve_events(events, cues, duration):
    """支持用 cue 关键词定位开始时间；顶部元素没写 end 时自动持续到下一个顶部元素"""
    out = []
    cursor = 0.0
    for i, ev in enumerate(events):
        ev = dict(ev)
        if "start" not in ev and "at" in ev:
            ev["start"] = ev["at"]
        if "start" not in ev and ev.get("cue"):
            kw = ev["cue"]
            hit = next((c for c in cues if kw in c["text"] and c["end"] > cursor), None)
            if hit is None:
                hit = next((c for c in cues if kw in c["text"]), None)
            if hit is None:
                log(f"[warn] 字幕里找不到关键词「{kw}」，事件 #{i} 跳过"); continue
            # 关键词在这句字幕中的大概位置
            frac = hit["text"].find(kw) / max(1, len(hit["text"]))
            ev["start"] = hit["start"] + (hit["end"] - hit["start"]) * frac + ev.get("offset", 0)
        if "start" not in ev:
            log(f"[warn] 事件 #{i} 没有 start/cue，跳过"); continue
        if "until" in ev and "end" not in ev:
            hit = next((c for c in cues if ev["until"] in c["text"] and c["start"] > ev["start"]), None)
            if hit:
                ev["end"] = hit["start"]
        if "dur" in ev and "end" not in ev:
            ev["end"] = ev["start"] + ev["dur"]
        cursor = ev["start"]
        out.append(ev)
    # 顶部区自动结束
    tops = sorted([e for e in out if e["type"] in TOP_TYPES], key=lambda e: e["start"])
    for a, b in zip(tops, tops[1:] + [None]):
        if "end" not in a:
            a["end"] = (b["start"] if b else duration)
        elif b and a["end"] > b["start"]:
            a["end"] = b["start"]
    for e in out:
        e.setdefault("end", e["start"] + 0.2)
        e["end"] = min(e["end"], duration)
    return out


# ======================================================================= 精灵准备
class Prepared:
    def __init__(self, ev, base_dir):
        self.ev = ev
        self.t = ev["type"]
        self.sprites = []
        self.anim = ev.get("anim")
        if self.t == "title":
            self.sprites = [L.to_np(L.sprite_title(ev, base_dir))]
            self.anim = self.anim or "rise"
        elif self.t == "tool":
            self.sprites = [L.to_np(L.sprite_tool(ev, base_dir))]
            self.anim = self.anim or "pop"
        elif self.t == "bigtext":
            self.sprites = [L.to_np(L.sprite_bigtext(ev, base_dir))]
            self.anim = self.anim or "pop"
        elif self.t == "badges":
            self.sprites = [L.to_np(L.sprite_badge(it, base_dir)) for it in ev.get("items", [])]
            self.anim = self.anim or "slide"
        elif self.t == "pip":
            self.anim = self.anim or "rise"
            self._prep_pip(ev, base_dir)

    def _prep_pip(self, ev, base_dir):
        bw, bh = L.pip_frame_box(ev)
        self.box = (bw, bh)
        self.cap = None
        self.img = None
        src = ev.get("video") or ev.get("image")
        p = None
        if src:
            p = src if os.path.isabs(src) else os.path.join(base_dir, src)
            if not os.path.exists(p):
                log(f"[warn] 找不到画中画素材 {p}，用占位图"); p = None
        if p and ev.get("video"):
            self.cap = cv2.VideoCapture(p)
            self.cap_fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        elif p:
            im = Image.open(p).convert("RGB")
            scale = bw / im.width
            self.img = np.array(im.resize((bw, max(bh, int(im.height * scale))), Image.LANCZOS))
            if self.img.shape[0] > bh and not ev.get("scroll", True):
                y0 = (self.img.shape[0] - bh) // 2
                self.img = self.img[y0:y0 + bh]
        else:
            self.img = np.array(L.placeholder_shot(bw, bh, ev.get("placeholder", "截图/录屏素材")))
        # 边框模板(只用来算尺寸与标签)
        self._last_key, self._last = None, None

    def pip_sprite(self, t):
        ev = self.ev
        bw, bh = self.box
        lt = t - ev["start"]
        dur = max(0.01, ev["end"] - ev["start"])
        if self.cap is not None:
            n = int(lt * self.cap_fps)
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, n)
            ok, fr = self.cap.read()
            if not ok:
                fr = np.zeros((bh, bw, 3), np.uint8)
            fr = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
            content = cover(fr, bw, bh)
        else:
            img = self.img
            if img.shape[0] > bh:   # 长截图：从上往下滚动
                p = ease_in_out(clamp((lt - 0.4) / max(0.1, dur - 0.8)))
                y = int((img.shape[0] - bh) * p)
                content = img[y:y + bh]
            else:                   # 普通图：慢推 (Ken Burns)
                z = 1.0 + 0.06 * clamp(lt / dur)
                content = cover(img, bw, bh, z)
        return L.to_np(L.pip_decorate(Image.fromarray(content), ev))


def cover(img, w, h, zoom=1.0):
    ih, iw = img.shape[:2]
    s = max(w / iw, h / ih) * zoom
    nw, nh = int(iw * s + 0.5), int(ih * s + 0.5)
    r = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    x, y = (nw - w) // 2, (nh - h) // 2
    return r[y:y + h, x:x + w]


# ======================================================================= 镜头运动
def zoom_at(t, zooms):
    """zoom 事件: {"type":"zoom","start":..,"end":..,"scale":1.15,"mode":"punch|push"}"""
    z = 1.0
    for e in zooms:
        if e["start"] <= t < e["end"]:
            sc = e.get("scale", 1.15)
            if e.get("mode", "punch") == "push":
                z = 1.0 + (sc - 1.0) * ease_in_out((t - e["start"]) / max(0.01, e["end"] - e["start"]))
            else:
                z = sc
    return z


def apply_zoom(frame, z, center):
    if abs(z - 1.0) < 0.002:
        return frame
    h, w = frame.shape[:2]
    cw, ch = w / z, h / z
    cx = clamp(center[0] * w, cw / 2, w - cw / 2)
    cy = clamp(center[1] * h, ch / 2, h - ch / 2)
    M = np.float32([[z, 0, w / 2 - z * cx], [0, z, h / 2 - z * cy]])
    return cv2.warpAffine(frame, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def auto_punch_events(cues, cfg, duration):
    """每隔N句字幕在 1.0 和 scale 之间切换景别，模拟双机位"""
    if not cfg:
        return []
    n, sc = cfg.get("every_cues", 2), cfg.get("scale", 1.12)
    out = []
    for i in range(0, len(cues), n):
        if (i // n) % 2 == 1:
            end = cues[min(i + n, len(cues)) - 1]["end"]
            out.append({"type": "zoom", "start": cues[i]["start"], "end": end, "scale": sc, "mode": "punch"})
    return out


# ======================================================================= 音效 (程序合成，无版权问题)
def synth_sfx(kind, sr=SR):
    rng = np.random.default_rng(7)
    if kind == "whoosh":
        d = 0.42; n = int(sr * d); t = np.arange(n) / sr
        noise = rng.standard_normal(n)
        out = np.zeros(n); lp = 0.0
        for i in range(n):          # 截止频率随时间扫动的一阶低通
            fc = 300 + 5000 * np.sin(np.pi * t[i] / d) ** 2
            a = 1 - np.exp(-2 * np.pi * fc / sr)
            lp += a * (noise[i] - lp); out[i] = lp
        env = np.sin(np.pi * t / d) ** 1.5
        y = out * env
    elif kind == "pop":
        d = 0.16; n = int(sr * d); t = np.arange(n) / sr
        f = 900 * np.exp(-t * 18) + 250
        y = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 30)
    elif kind == "ding":
        d = 0.9; n = int(sr * d); t = np.arange(n) / sr
        y = (np.sin(2 * np.pi * 1318 * t) + 0.5 * np.sin(2 * np.pi * 2637 * t)) * np.exp(-t * 5)
    elif kind == "click":
        d = 0.05; n = int(sr * d); t = np.arange(n) / sr
        y = rng.standard_normal(n) * np.exp(-t * 120)
    else:
        return None
    return (y / (np.abs(y).max() + 1e-9) * 0.9).astype(np.float32)


DEFAULT_SFX = {"title": "whoosh", "tool": "pop", "badges": "click", "pip": "whoosh", "bigtext": "ding"}


def build_sfx_track(events, duration, base_dir, path):
    n = int(duration * SR) + SR
    track = np.zeros(n, np.float32)
    cache = {}
    for e in events:
        if e["type"] == "sfx":
            kind = e.get("sound", "pop")
        else:
            kind = e.get("sfx", DEFAULT_SFX.get(e["type"]))
        if not kind or kind == "none":
            continue
        if kind not in cache:
            if os.path.exists(os.path.join(base_dir, kind)):   # 自定义音效文件
                cache[kind] = load_audio(os.path.join(base_dir, kind))
            else:
                cache[kind] = synth_sfx(kind)
        s = cache[kind]
        if s is None:
            continue
        lead = 0.12 if kind == "whoosh" else 0.0     # whoosh 提前一点，峰值对上画面
        i0 = max(0, int((e["start"] - lead) * SR))
        seg = s[: max(0, min(len(s), n - i0))]
        track[i0:i0 + len(seg)] += seg * e.get("volume", 1.0)
    track = np.clip(track, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((track * 32767).astype(np.int16).tobytes())


def load_audio(p):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.float32).copy()


# ======================================================================= 主流程
def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                          "-of", "json", path], capture_output=True, text=True).stdout
    j = json.loads(out)
    has_audio = any(s.get("codec_type") == "audio" for s in j.get("streams", []))
    return float(j["format"]["duration"]), has_audio


class Renderer:
    def __init__(self, tl_path, preview=False):
        self.tl_path = os.path.abspath(tl_path)
        self.base = os.path.dirname(self.tl_path)
        self.tl = json.load(open(self.tl_path, encoding="utf-8"))
        C.init(self.tl.get("style"), preview)
        self.src = self._p(self.tl["video"])
        self.duration, self.has_audio = probe(self.src)
        if self.tl.get("trim"):
            self.t0, t1 = self.tl["trim"]
            self.duration = min(self.duration, t1) - self.t0
        else:
            self.t0 = 0.0
        self.cues = parse_srt(self._p(self.tl.get("srt")) if self.tl.get("srt") else None)
        if self.t0:
            self.cues = [dict(c, start=c["start"] - self.t0, end=c["end"] - self.t0) for c in self.cues if c["end"] > self.t0]
        evs = resolve_events(self.tl.get("events", []), self.cues, self.duration)
        self.events = evs
        self.zooms = [e for e in evs if e["type"] == "zoom"] + auto_punch_events(self.cues, C.STYLE.get("auto_punch"), self.duration)
        self.flashes = [e for e in evs if e["type"] == "flash"]
        self.layers = [Prepared(e, self.base) for e in evs if e["type"] in TOP_TYPES]
        cs = C.STYLE["caption"]
        self.caps = caption_segments(self.cues, cs["max_chars"]) if cs.get("enabled", True) else []
        kws = self.tl.get("highlight", [])
        for seg in self.caps:
            seg["spr"] = L.to_np(L.sprite_caption(seg["text"], kws))
        log(f"[info] 素材 {self.duration:.1f}s，字幕 {len(self.cues)} 句，包装元素 {len(self.layers)} 个，输出 {C.W}x{C.H}")

    def _p(self, p):
        return p if os.path.isabs(p) else os.path.join(self.base, p)

    # ---------------------------------------------------------------- 单帧
    def compose(self, frame, t):
        frame = apply_zoom(frame, zoom_at(t, self.zooms), C.STYLE["zoom_center"])
        frame = np.ascontiguousarray(frame)
        top_cy = C.STYLE["top_y"] * C.H
        for ly in self.layers:
            ev = ly.ev
            st = L.anim_state(ly.t, t, ev["start"], ev["end"], ly.anim)
            if st is None:
                continue
            s, a, dx, dy = st
            cy = top_cy + ev.get("y_offset", 0) * C.H
            if ly.t == "badges":
                gap = int(14 * C.U)
                total = sum(sp.shape[0] for sp in ly.sprites) + gap * (len(ly.sprites) - 1)
                y = cy - total / 2
                for k, sp in enumerate(ly.sprites):    # 逐个错峰滑入
                    stk = L.anim_state("badges", t, ev["start"] + k * ev.get("stagger", 0.35), ev["end"], ly.anim)
                    if stk:
                        s2, a2, dx2, dy2 = stk
                        L.blit(frame, sp, C.W / 2 + dx2, y + sp.shape[0] / 2 + dy2, s2, a2)
                    y += sp.shape[0] + gap
            elif ly.t == "pip":
                L.blit(frame, ly.pip_sprite(t), C.W / 2 + dx, cy + dy + ev.get("label_shift", 0), s, a)
            else:
                L.blit(frame, ly.sprites[0], C.W / 2 + dx, cy + dy, s, a)
        # 字幕
        cs = C.STYLE["caption"]
        for seg in self.caps:
            if seg["start"] <= t < seg["end"]:
                k = clamp((t - seg["start"]) / 0.12)
                L.blit(frame, seg["spr"], C.W / 2, cs["y"] * C.H, 0.85 + 0.15 * L.ease_out_back(k), 1.0)
                break
        # 闪白转场
        for e in self.flashes:
            d = e.get("dur", 0.25)
            if e["start"] <= t < e["start"] + d:
                a = 1 - (t - e["start"]) / d
                col = np.array(C.hex2rgb(e.get("color", "#FFFFFF"))[:3], np.float32)
                frame[:] = (frame * (1 - a) + col * a).astype(np.uint8)
        return frame

    # ---------------------------------------------------------------- 读帧
    def reader(self, fps):
        vf = f"scale={C.W}:{C.H}:force_original_aspect_ratio=increase,crop={C.W}:{C.H},fps={fps}"
        cmd = ["ffmpeg", "-v", "error", "-ss", str(self.t0), "-t", str(self.duration), "-i", self.src,
               "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        fs = C.W * C.H * 3
        while True:
            b = p.stdout.read(fs)
            if len(b) < fs:
                break
            yield np.frombuffer(b, np.uint8).reshape(C.H, C.W, 3).copy()
        p.wait()

    def stills(self, times, outdir):
        os.makedirs(outdir, exist_ok=True)
        files = []
        for t in times:
            t = clamp(t, 0, self.duration - 0.05)
            cmd = ["ffmpeg", "-v", "error", "-ss", str(self.t0 + t), "-i", self.src, "-frames:v", "1",
                   "-vf", f"scale={C.W}:{C.H}:force_original_aspect_ratio=increase,crop={C.W}:{C.H}",
                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
            b = subprocess.run(cmd, capture_output=True).stdout
            fr = np.frombuffer(b[:C.W * C.H * 3], np.uint8).reshape(C.H, C.W, 3).copy()
            out = self.compose(fr, t)
            fn = os.path.join(outdir, f"still_{t:06.2f}s.png")
            Image.fromarray(out).save(fn); files.append(fn)
        return files

    def render(self, out_path):
        fps = C.FPS
        tmpd = tempfile.mkdtemp(prefix="rv_")
        silent = os.path.join(tmpd, "video.mp4")
        sfx = os.path.join(tmpd, "sfx.wav")
        enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                "-s", f"{C.W}x{C.H}", "-r", str(fps), "-i", "-",
                                "-c:v", "libx264", "-preset", C.STYLE["preset"], "-crf", str(C.STYLE["crf"]),
                                "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
        total = int(self.duration * fps)
        for i, fr in enumerate(self.reader(fps)):
            enc.stdin.write(self.compose(fr, i / fps).tobytes())
            if i % (fps * 5) == 0:
                log(f"  渲染 {i / fps:5.1f}s / {self.duration:.1f}s")
        enc.stdin.close(); enc.wait()
        build_sfx_track(self.events, self.duration, self.base, sfx)
        self.mux(silent, sfx, out_path)
        shutil.rmtree(tmpd, ignore_errors=True)
        log(f"[done] {out_path}")

    def mux(self, video, sfx, out_path):
        st = C.STYLE
        inputs = ["-i", video, "-i", sfx]
        parts, mix = [], []
        idx = 2
        if self.has_audio:
            inputs += ["-ss", str(self.t0), "-t", str(self.duration), "-i", self.src]
            parts.append(f"[{idx}:a]aresample={SR},aformat=channel_layouts=stereo,asplit=2[voice][vkey]")
            mix.append("[voice]"); voice_idx = idx; idx += 1
        parts.append(f"[1:a]aformat=channel_layouts=stereo,volume={st['sfx_volume']}[sfx]"); mix.append("[sfx]")
        if st.get("bgm"):
            inputs += ["-stream_loop", "-1", "-i", self._p(st["bgm"])]
            parts.append(f"[{idx}:a]aresample={SR},aformat=channel_layouts=stereo,volume={st['bgm_volume']},"
                         f"atrim=0:{self.duration},afade=t=out:st={max(0, self.duration - 1.5)}:d=1.5[bgm0]")
            if self.has_audio:  # 人声出现时自动压低BGM
                parts.append(f"[bgm0][vkey]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400:makeup=1[bgm]")
            else:
                parts.append("[bgm0]anull[bgm]")
            mix.append("[bgm]"); idx += 1
        elif self.has_audio:
            parts.append("[vkey]anullsink")
        parts.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:normalize=0,alimiter=limit=0.95[aout]")
        cmd = ["ffmpeg", "-v", "error", "-y"] + inputs + ["-filter_complex", ";".join(parts),
               "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               "-t", str(self.duration), "-movflags", "+faststart", out_path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            log(r.stderr); raise SystemExit("音频合成失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("timeline")
    ap.add_argument("-o", "--out")
    ap.add_argument("--preview", action="store_true", help="半分辨率快速预览")
    ap.add_argument("--stills", help="'events' 或逗号分隔秒数")
    a = ap.parse_args()
    r = Renderer(a.timeline, a.preview)
    base = os.path.splitext(a.out or os.path.join(r.base, r.tl.get("output", "output.mp4")))[0]
    if a.stills:
        if a.stills == "events":
            times = sorted({round(min(e["start"] + 0.6, (e["start"] + e["end"]) / 2), 2) for e in r.events if e["type"] in TOP_TYPES})
        else:
            times = [float(x) for x in a.stills.split(",")]
        for f in r.stills(times, base + "_stills"):
            print(f)
        return
    out = base + ("_preview.mp4" if a.preview else ".mp4")
    r.render(out)
    print(out)


if __name__ == "__main__":
    main()
