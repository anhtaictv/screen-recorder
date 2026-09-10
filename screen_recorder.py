"""Quay màn hình offline, xuất MP4 kèm mic tuỳ chọn.
Deps: opencv-python, mss, numpy; ghi mic cần thêm sounddevice, imageio-ffmpeg (thiếu thì tự quay video câm)."""
import sys
import os
import json
import time
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from datetime import datetime

import cv2
import numpy as np
import mss

try:
    import sounddevice as sd
    import wave
except Exception:
    sd = None  # thiếu lib hoặc không có driver audio -> tắt tính năng ghi mic, video vẫn quay câm bình thường

try:
    import imageio_ffmpeg
except Exception:
    imageio_ffmpeg = None  # thiếu lib -> không ghép được audio vào video, giữ nguyên video câm


def _app_base_dir():
    """Thư mục chứa exe khi đã đóng gói (PyInstaller), hoặc chứa script khi chạy từ mã nguồn.
    __file__ khi frozen trỏ vào thư mục tạm _MEIPASS sẽ bị xoá sau khi thoát app -> không dùng được."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # khớp tọa độ kéo chọn vùng với pixel vật lý
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# Khi đóng gói bằng PyInstaller, openh264-2.5.0-win64.dll được giải nén vào thư mục tạm _MEIPASS
# lúc chạy -> cần thêm thư mục đó vào đường dẫn tìm DLL thì OpenCV mới load được để encode H.264.
if getattr(sys, "frozen", False):
    try:
        os.add_dll_directory(sys._MEIPASS)
    except Exception:
        pass

DEFAULT_FPS = 30  # trần fps mặc định; GUI cho chọn lại (15/24/30/60)

try:
    import keyboard  # hotkey toàn cục F9; thiếu lib hoặc môi trường chặn hook bàn phím (RDP/VM) -> bỏ qua
except Exception:
    keyboard = None

try:
    import pystray
    from PIL import Image, ImageDraw  # icon khay hệ thống; thiếu 1 trong 2 lib -> tắt tính năng tray
except Exception:
    pystray = None

CONFIG_PATH = os.path.join(_app_base_dir(), "config.json")


def _load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except Exception:
        pass  # ponytail: lưu cấu hình là tiện ích phụ, lỗi ghi (đầy đĩa, mất quyền...) không nên chặn app


def list_monitors():
    """Danh sách các màn hình vật lý (bỏ index 0 của mss = vùng gộp toàn bộ màn hình ảo)."""
    with mss.MSS() as sct:
        return list(sct.monitors[1:])


def _bbox_to_region(bbox):
    """bbox kiểu PIL (x0,y0,x1,y1) -> dict vùng chụp của mss. None = toàn màn hình chính."""
    if bbox is None:
        mon = list_monitors()[0]
        return {"left": mon["left"], "top": mon["top"], "width": mon["width"], "height": mon["height"]}
    x0, y0, x1, y1 = bbox
    return {"left": int(x0), "top": int(y0), "width": int(x1 - x0), "height": int(y1 - y0)}


def _mss_capture_loop(region, frame_queue: queue.Queue, stop_event: threading.Event):
    """Backend GDI (mss) — luôn chạy được trên mọi máy Windows, nhưng chậm hơn DXGI."""
    with mss.MSS() as sct:
        while not stop_event.is_set():
            frame = cv2.cvtColor(np.array(sct.grab(region)), cv2.COLOR_BGRA2BGR)
            try:
                frame_queue.put(frame, timeout=0.5)
            except queue.Full:
                pass  # ponytail: rớt khung khi thread ghi chậm hơn, chấp nhận để không chặn producer


def _dxcam_capture_loop(region, frame_queue: queue.Queue, stop_event: threading.Event):
    """Backend DXGI Desktop Duplication (dxcam) — nhanh hơn GDI nhiều lần, nhưng cần driver GPU hỗ trợ."""
    import dxcam
    left, top, w, h = region["left"], region["top"], region["width"], region["height"]
    cam = dxcam.create(output_idx=0, output_color="BGR")
    try:
        cam.start(region=(left, top, left + w, top + h), target_fps=0, video_mode=True)
        while not stop_event.is_set():
            frame = cam.get_latest_frame()
            try:
                frame_queue.put(frame, timeout=0.5)
            except queue.Full:
                pass
    finally:
        cam.stop()
        cam.release()


def _start_capture(region):
    """Khởi động pipeline capture một lần duy nhất, dùng xuyên suốt cho cả đo fps lẫn ghi thật (tránh phí
    khởi tạo lại driver nhiều lần). Tự dò: thử DXGI (dxcam, nhanh hơn hẳn) trước, không lên hình kịp trong
    0.6s (thiếu lib, driver/GPU không hỗ trợ, bị chặn bởi VM/RDP...) thì rơi về GDI (mss, luôn chạy được).
    Trả về (backend_name, thread, stop_event, queue, frame_đầu_tiên)."""
    q = queue.Queue(maxsize=8)
    stop = threading.Event()
    failed = []

    def dx_runner():
        try:
            _dxcam_capture_loop(region, q, stop)
        except Exception as e:
            failed.append(e)

    t = threading.Thread(target=dx_runner, daemon=True)
    t.start()
    try:
        first = q.get(timeout=2.5)  # dxcam có độ trễ khởi động nguội driver GPU lần đầu (~1-1.5s), chỉ trả giá 1 lần
        if not failed:
            return "DXGI/GPU", t, stop, q, first
    except queue.Empty:
        pass
    stop.set()
    t.join(timeout=1.0)

    q2 = queue.Queue(maxsize=8)
    stop2 = threading.Event()
    t2 = threading.Thread(target=_mss_capture_loop, args=(region, q2, stop2), daemon=True)
    t2.start()
    first2 = q2.get(timeout=3)
    return "GDI", t2, stop2, q2, first2


def _record_audio_loop(wav_path, stop_event, pause_event, status_holder, samplerate=44100, channels=1):
    """Ghi mic ra WAV liên tục trong luồng riêng. Khi pause_event bật thì bỏ qua mẫu thu được (không ghi)
    để khớp với video: video cũng không ghi khung mới lúc pause -> hai file cùng độ dài thời gian thực."""
    wf = wave.open(wav_path, "wb")
    wf.setnchannels(channels)
    wf.setsampwidth(2)  # int16
    wf.setframerate(samplerate)

    def callback(indata, frames, time_info, status):
        if pause_event is None or not pause_event.is_set():
            wf.writeframes(indata.tobytes())

    try:
        with sd.InputStream(samplerate=samplerate, channels=channels, dtype="int16", callback=callback):
            stop_event.wait()
    except Exception as e:
        status_holder.append(e)  # vd không có mic -> báo lỗi ra ngoài, video vẫn giữ nguyên
    finally:
        wf.close()


def _mux_audio_video(video_path, wav_path, out_path):
    """Ghép video câm + audio WAV thành file cuối bằng ffmpeg (binary kèm theo gói imageio-ffmpeg,
    không cần cài ffmpeg riêng). Container AVI không chuẩn hoá tốt AAC -> dùng mp3 cho AVI."""
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    audio_codec = "mp3" if out_path.lower().endswith(".avi") else "aac"
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.run(
        [
            ffmpeg_exe, "-y", "-i", video_path, "-i", wav_path,
            "-c:v", "copy", "-c:a", audio_codec, "-shortest", out_path,
        ],
        check=True, capture_output=True, creationflags=creationflags,
    )


def _open_writer(out_path, fps, w, h, fourccs=("avc1", "mp4v")):
    """Thử lần lượt các codec trong fourccs (vd avc1=H.264 nén nhẹ hơn mp4v ~6-7 lần nhưng cần openh264
    DLL); codec cuối cùng luôn là mp4v (luôn có sẵn trong OpenCV) nên writer trả về không bao giờ None."""
    for fourcc in fourccs:
        writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*fourcc), fps, (w, h))
        if writer.isOpened():
            return writer
        writer.release()
    return cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))


def record(
    stop_event: threading.Event, out_path: str, status_cb=None, bbox=None,
    fps=DEFAULT_FPS, scale=1.0, fourccs=("avc1", "mp4v"), pause_event: threading.Event = None,
    record_audio=True,
):
    """Ghi thẳng 1 lần vào file cuối cùng, đúng nhịp thời gian thực (interval cố định theo fps):
    lặp lại khung mới nhất nếu máy chưa kịp chụp khung mới, giống mọi phần mềm quay màn hình thật.
    Nhờ ghi đúng nhịp thời gian thực, số khung/fps luôn tự khớp thời lượng thực — không cần đo
    trước hay mã hoá lại (remux) sau khi quay xong, nên bấm Stop là lưu xong ngay lập tức.
    scale: tỉ lệ thu nhỏ khung hình trước khi ghi (vd 0.75) để giảm dung lượng file, 1.0 = giữ nguyên.
    pause_event: khi set() thì ngừng ghi khung mới (video đứng hình) mà không dừng capture, resume tự
    khớp lại nhịp thời gian thực (không bị dồn khung để bù lại đoạn tạm dừng).
    record_audio: có ghi thêm mic không (cần sounddevice + imageio-ffmpeg, thiếu 1 trong 2 thì tự tắt)."""
    region = _bbox_to_region(bbox)
    backend_name, cap_thread, cap_stop, q, first = _start_capture(region)
    if status_cb:
        status_cb(f"Backend: {backend_name}")
    h, w = first.shape[:2]
    out_w, out_h = (int(w * scale), int(h * scale)) if scale != 1.0 else (w, h)

    use_audio = record_audio and sd is not None and imageio_ffmpeg is not None
    video_path = out_path
    wav_path = None
    audio_thread = None
    audio_stop = audio_errors = None
    if use_audio:
        video_path = out_path + ".video.tmp" + os.path.splitext(out_path)[1]
        wav_path = out_path + ".audio.tmp.wav"
        audio_stop = threading.Event()
        audio_errors = []
        audio_thread = threading.Thread(
            target=_record_audio_loop, args=(wav_path, audio_stop, pause_event, audio_errors), daemon=True,
        )
        audio_thread.start()

    interval = 1.0 / fps
    frames = 0
    latest = first
    writer = _open_writer(video_path, fps, out_w, out_h, fourccs)
    start = time.time()
    next_due = start
    try:
        while not stop_event.is_set():
            if pause_event is not None and pause_event.is_set():
                next_due = time.time() + interval  # tránh dồn khung khi resume
                time.sleep(0.05)
                continue
            try:
                while True:  # rút cạn hàng đợi, chỉ giữ khung mới nhất
                    latest = q.get_nowait()
            except queue.Empty:
                pass
            now = time.time()
            if now < next_due:
                time.sleep(min(next_due - now, 0.01))
                continue
            frame = cv2.resize(latest, (out_w, out_h)) if scale != 1.0 else latest
            writer.write(frame)
            frames += 1
            next_due += interval
            if status_cb:
                status_cb(f"[{backend_name}] Recording... {frames} frames ({frames/fps:.0f}s)")
    finally:
        writer.release()
        cap_stop.set()
        cap_thread.join(timeout=1)
        if audio_thread is not None:
            audio_stop.set()
            audio_thread.join(timeout=2)

    if use_audio:
        if audio_errors:
            if status_cb:
                status_cb(f"Không ghi được mic ({audio_errors[0]}), lưu video câm.")
            os.replace(video_path, out_path)
        else:
            try:
                if status_cb:
                    status_cb("Đang ghép âm thanh...")
                _mux_audio_video(video_path, wav_path, out_path)
                os.remove(video_path)
            except Exception as e:
                if status_cb:
                    status_cb(f"Ghép âm thanh lỗi ({e}), lưu video câm.")
                os.replace(video_path, out_path)  # không mất video đã quay được
            finally:
                try:
                    os.remove(wav_path)
                except OSError:
                    pass
    return frames, time.time() - start


class RegionSelector:
    """Overlay phủ đúng 1 màn hình (theo `monitor`), kéo chuột để vẽ khung vùng quay.
    Esc = huỷ (quay full màn hình đó). Dùng geometry thủ công thay vì -fullscreen vì -fullscreen
    trên Windows chỉ neo được vào primary monitor, không phủ đúng màn hình phụ được chọn."""

    def __init__(self, root, monitor):
        self.result = None
        self.start_xy = None
        self.rect = None
        self.monitor = monitor
        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.geometry(f"{monitor['width']}x{monitor['height']}+{monitor['left']}+{monitor['top']}")
        self.top.attributes("-alpha", 0.3)
        self.top.attributes("-topmost", True)
        self.top.configure(bg="black")
        self.canvas = tk.Canvas(self.top, cursor="cross", bg="gray", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.top.bind("<Escape>", self._on_cancel)
        tk.Label(
            self.top, text="Kéo chuột để chọn vùng quay  |  Esc = quay full màn hình này",
            fg="white", bg="black",
        ).place(relx=0.5, rely=0.02, anchor="n")
        self.top.focus_force()  # overrideredirect bỏ qua focus mặc định của window manager -> ép nhận phím Esc

    def _on_press(self, event):
        self.start_xy = (event.x_root, event.y_root)
        self.rect = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="red", width=2)

    def _on_drag(self, event):
        if self.rect is not None:
            x0, y0 = self.canvas.canvasx(0), self.canvas.canvasy(0)
            sx, sy = self.start_xy
            self.canvas.coords(self.rect, sx - x0, sy - y0, event.x, event.y)

    def _on_release(self, event):
        x0, y0 = self.start_xy
        x1, y1 = event.x_root, event.y_root
        self.result = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        self.top.destroy()

    def _on_cancel(self, _event):
        m = self.monitor
        self.result = (m["left"], m["top"], m["left"] + m["width"], m["top"] + m["height"])
        self.top.destroy()

    def get_region(self):
        self.top.wait_window()
        if self.result and (self.result[2] - self.result[0] >= 10) and (self.result[3] - self.result[1] >= 10):
            return self.result
        return None


FPS_OPTIONS = [15, 24, 30, 60]
SCALE_OPTIONS = {"100%": 1.0, "75%": 0.75, "50%": 0.5}
FORMAT_OPTIONS = {
    "MP4": (".mp4", ("avc1", "mp4v")),
    "MOV": (".mov", ("avc1", "mp4v")),
    "AVI": (".avi", ("XVID", "MJPG")),
}

# Dark theme (slate + teal accent, red for recording state).
BG = "#0F172A"
SURFACE = "#1E293B"
BORDER = "#334155"
TEXT = "#F1F5F9"
MUTED = "#94A3B8"
ACCENT = "#14B8A6"
ACCENT_HOVER = "#0D9488"
DANGER = "#EF4444"
DANGER_HOVER = "#DC2626"
PAUSE = "#F59E0B"
PAUSE_HOVER = "#D97706"
DISABLED_BG = "#1E293B"
DISABLED_FG = "#64748B"

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 14, "bold")
FONT_MONO = ("Consolas", 13, "bold")  # số liệu (timer) dùng font đều nét, tránh nhảy layout khi đổi số


def _mk_button(parent, text, command, base_bg, hover_bg, fg=TEXT):
    """Nút bấm màu phẳng tự vẽ (tk.Button, không phải ttk) — ttk.Button trên Windows theme mặc định
    bỏ qua màu nền tuỳ chỉnh, còn tk.Button thì tôn trọng bg/fg nên mới style được theo palette riêng."""
    btn = tk.Button(
        parent, text=text, command=command, bg=base_bg, fg=fg,
        activebackground=hover_bg, activeforeground=fg,
        relief="flat", bd=0, font=FONT_BOLD, cursor="hand2", padx=16, pady=10,
        disabledforeground=DISABLED_FG,
    )
    btn._base_bg, btn._hover_bg = base_bg, hover_bg
    btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg) if str(btn["state"]) != "disabled" else None)
    btn.bind("<Leave>", lambda e: btn.config(bg=base_bg) if str(btn["state"]) != "disabled" else None)
    return btn


def _btn_set_enabled(btn, enabled):
    if enabled:
        btn.config(state=tk.NORMAL, bg=btn._base_bg, cursor="hand2")
    else:
        btn.config(state=tk.DISABLED, bg=DISABLED_BG, cursor="arrow")


def _make_tray_image(hex_color):
    """Icon khay hệ thống: chấm tròn màu, vẽ bằng PIL thay vì cần file .ico riêng."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((6, 6, 58, 58), fill=hex_color)
    return img


class App:
    def __init__(self, root):
        self.root = root
        root.title("Screen Recorder")
        root.configure(bg=BG)
        root.resizable(False, False)
        self.stop_event = None
        self.pause_event = None
        self.thread = None
        self.out_path = None
        self.tray_icon = None
        self._blink_on = False
        self._paused_total = 0.0
        self._pause_started = None

        self.cfg = _load_config()
        self.monitors = list_monitors()

        style = ttk.Style()
        style.theme_use("clam")  # theme 'clam' là theme duy nhất tôn trọng màu nền tuỳ chỉnh cho Combobox trên Windows
        style.configure(
            "Dark.TCombobox", fieldbackground=SURFACE, background=SURFACE, foreground=TEXT,
            arrowcolor=TEXT, bordercolor=BORDER, lightcolor=SURFACE, darkcolor=SURFACE, padding=4,
        )
        style.map("Dark.TCombobox", fieldbackground=[("readonly", SURFACE)], foreground=[("readonly", TEXT)])
        root.option_add("*TCombobox*Listbox.background", SURFACE)
        root.option_add("*TCombobox*Listbox.foreground", TEXT)
        root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)

        container = tk.Frame(root, bg=BG)
        container.pack(padx=20, pady=18)

        tk.Label(container, text="Screen Recorder", font=FONT_TITLE, fg=TEXT, bg=BG).pack(anchor="w")
        tk.Label(
            container, text="Quay màn hình offline · kèm mic tuỳ chọn", font=FONT, fg=MUTED, bg=BG,
        ).pack(anchor="w", pady=(0, 14))

        card = tk.Frame(container, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x", pady=(0, 14))
        card_pad = tk.Frame(card, bg=SURFACE)
        card_pad.pack(fill="x", padx=16, pady=14)

        rec_row = tk.Frame(card_pad, bg=SURFACE)
        rec_row.pack(fill="x")
        self.rec_dot = tk.Canvas(rec_row, width=12, height=12, bg=SURFACE, highlightthickness=0)
        self._rec_dot_id = self.rec_dot.create_oval(2, 2, 10, 10, fill=SURFACE, outline="")
        self.rec_dot.pack(side=tk.LEFT)
        self.timer_var = tk.StringVar(value="00:00")
        tk.Label(rec_row, textvariable=self.timer_var, font=FONT_MONO, fg=TEXT, bg=SURFACE).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        if keyboard is not None:
            tk.Label(rec_row, text="F9 · Start / Stop", font=FONT, fg=MUTED, bg=SURFACE).pack(side=tk.RIGHT)

        self.status = tk.StringVar(value="Ready")
        tk.Label(
            card_pad, textvariable=self.status, font=FONT, fg=MUTED, bg=SURFACE,
            wraplength=280, justify="left", anchor="w",
        ).pack(fill="x", pady=(8, 0))

        mon_row = tk.Frame(container, bg=BG)
        mon_row.pack(fill="x", pady=(0, 10))
        tk.Label(mon_row, text="Màn hình", font=FONT, fg=MUTED, bg=BG).pack(anchor="w")
        mon_labels = [f"Màn hình {i+1} ({m['width']}x{m['height']})" for i, m in enumerate(self.monitors)]
        self.monitor_combo = ttk.Combobox(
            mon_row, values=mon_labels, state="readonly", width=26, style="Dark.TCombobox",
        )
        saved_mon = self.cfg.get("monitor_index", 0)
        self.monitor_combo.current(saved_mon if 0 <= saved_mon < len(mon_labels) else 0)
        self.monitor_combo.pack(anchor="w", pady=(2, 0))

        opts = tk.Frame(container, bg=BG)
        opts.pack(fill="x", pady=(0, 14))
        tk.Label(opts, text="FPS", font=FONT, fg=MUTED, bg=BG).grid(row=0, column=0, sticky="w")
        saved_fps = str(self.cfg.get("fps", DEFAULT_FPS))
        self.fps_var = tk.StringVar(value=saved_fps if int(saved_fps) in FPS_OPTIONS else str(DEFAULT_FPS))
        ttk.Combobox(
            opts, textvariable=self.fps_var, values=[str(v) for v in FPS_OPTIONS],
            state="readonly", width=6, style="Dark.TCombobox",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        tk.Label(opts, text="Chất lượng", font=FONT, fg=MUTED, bg=BG).grid(row=0, column=1, sticky="w", padx=(20, 0))
        saved_scale = self.cfg.get("quality", "100%")
        self.scale_var = tk.StringVar(value=saved_scale if saved_scale in SCALE_OPTIONS else "100%")
        ttk.Combobox(
            opts, textvariable=self.scale_var, values=list(SCALE_OPTIONS.keys()),
            state="readonly", width=6, style="Dark.TCombobox",
        ).grid(row=1, column=1, sticky="w", padx=(20, 0), pady=(2, 0))
        tk.Label(opts, text="Định dạng", font=FONT, fg=MUTED, bg=BG).grid(row=0, column=2, sticky="w", padx=(20, 0))
        saved_fmt = self.cfg.get("format", "MP4")
        self.format_var = tk.StringVar(value=saved_fmt if saved_fmt in FORMAT_OPTIONS else "MP4")
        ttk.Combobox(
            opts, textvariable=self.format_var, values=list(FORMAT_OPTIONS.keys()),
            state="readonly", width=6, style="Dark.TCombobox",
        ).grid(row=1, column=2, sticky="w", padx=(20, 0), pady=(2, 0))

        mic_available = sd is not None and imageio_ffmpeg is not None
        self.mic_var = tk.BooleanVar(value=self.cfg.get("record_mic", True) if mic_available else False)
        mic_cb = tk.Checkbutton(
            container, text="Ghi âm micro" if mic_available else "Ghi âm micro (thiếu thư viện, không dùng được)",
            variable=self.mic_var, font=FONT, fg=TEXT, bg=BG, selectcolor=SURFACE,
            activebackground=BG, activeforeground=TEXT, highlightthickness=0,
        )
        mic_cb.pack(anchor="w", pady=(0, 14))
        if not mic_available:
            mic_cb.config(state=tk.DISABLED)

        btns = tk.Frame(container, bg=BG)
        btns.pack(fill="x")
        self.start_btn = _mk_button(btns, "Start (chọn vùng)", self.start, ACCENT, ACCENT_HOVER)
        self.start_btn.pack(fill="x", pady=(0, 8))
        self.pause_btn = _mk_button(btns, "Tạm dừng", self.toggle_pause, PAUSE, PAUSE_HOVER)
        self.pause_btn.pack(fill="x", pady=(0, 8))
        _btn_set_enabled(self.pause_btn, False)
        self.stop_btn = _mk_button(btns, "Stop", self.stop, DANGER, DANGER_HOVER)
        self.stop_btn.pack(fill="x", pady=(0, 8))
        _btn_set_enabled(self.stop_btn, False)
        self.open_folder_btn = _mk_button(btns, "Mở thư mục vừa lưu", self.open_folder, SURFACE, BORDER)
        self.open_folder_btn.pack(fill="x")
        _btn_set_enabled(self.open_folder_btn, False)

        self._center_window()

        if keyboard is not None:
            try:
                keyboard.add_hotkey("f9", lambda: self.root.after(0, self.toggle_record))
            except Exception:
                pass  # ponytail: hook bàn phím có thể bị chặn (RDP/VM/quyền) -> im lặng bỏ qua, nút bấm vẫn chạy

        if pystray is not None:
            self._setup_tray()

    def _setup_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Hiện cửa sổ", lambda: self.root.after(0, self._show_window), default=True),
            pystray.MenuItem("Dừng quay", lambda: self.root.after(0, self.stop)),
            pystray.MenuItem("Thoát", lambda: self.root.after(0, self._quit_app)),
        )
        self.tray_icon = pystray.Icon("screen_recorder", _make_tray_image(ACCENT), "Screen Recorder", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()

    def _quit_app(self):
        if self.thread and self.thread.is_alive():
            self.stop()
            self.root.after(100, self._quit_app)  # đợi ghi xong hẳn rồi mới thoát, tránh file video hỏng
            return
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()

    def _center_window(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"+{x}+{y}")

    def toggle_record(self):
        if str(self.stop_btn["state"]) == tk.NORMAL:
            self.stop()
        else:
            self.start()

    def start(self):
        default_dir = self.cfg.get("save_dir") or os.path.join(_app_base_dir(), "recordings")
        try:
            os.makedirs(default_dir, exist_ok=True)
        except OSError:
            default_dir = os.path.join(_app_base_dir(), "recordings")  # vd thư mục cũ nằm ở ổ USB đã rút
            os.makedirs(default_dir, exist_ok=True)
        fmt = self.format_var.get()
        ext, _ = FORMAT_OPTIONS[fmt]
        out_path = filedialog.asksaveasfilename(
            title="Chọn nơi lưu video",
            initialdir=default_dir,
            initialfile=datetime.now().strftime(f"record_%Y%m%d_%H%M%S{ext}"),
            defaultextension=ext,
            filetypes=[(f"Video {fmt}", f"*{ext}")],
        )
        if not out_path:
            return  # người dùng bấm Cancel -> không quay
        self.out_path = out_path
        self.cfg.update({
            "fps": int(self.fps_var.get()),
            "quality": self.scale_var.get(),
            "format": fmt,
            "save_dir": os.path.dirname(out_path),
            "monitor_index": self.monitor_combo.current(),
            "record_mic": self.mic_var.get(),
        })
        _save_config(self.cfg)
        _btn_set_enabled(self.open_folder_btn, False)
        self.root.withdraw()  # ẩn cửa sổ chính để không lọt vào khung chọn/video
        self.root.after(150, lambda: self._pick_region_and_record(out_path))

    def _pick_region_and_record(self, out_path):
        monitor = self.monitors[self.monitor_combo.current()]
        selector = RegionSelector(self.root, monitor)
        bbox = selector.get_region()
        self.root.deiconify()

        self.status.set(f"Sẽ lưu vào: {out_path}")
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self._rec_start = time.time()
        self._paused_total = 0.0
        self._pause_started = None
        _btn_set_enabled(self.pause_btn, True)
        self.pause_btn.config(text="Tạm dừng")
        # Tkinter chỉ an toàn khi thao tác từ 1 thread duy nhất (kể cả gọi after() từ thread khác cũng
        # có thể làm treo Tcl interpreter) -> thread nền chỉ ghi vào biến thường, thread chính tự poll.
        self._latest_status = ["Recording..."]
        self.thread = threading.Thread(
            target=record,
            args=(self.stop_event, out_path),
            kwargs={
                "status_cb": lambda s: self._latest_status.__setitem__(0, s),
                "bbox": bbox,
                "fps": int(self.fps_var.get()),
                "scale": SCALE_OPTIONS[self.scale_var.get()],
                "fourccs": FORMAT_OPTIONS[self.format_var.get()][1],
                "pause_event": self.pause_event,
                "record_audio": self.mic_var.get(),
            },
            daemon=True,
        )
        self.thread.start()
        _btn_set_enabled(self.start_btn, False)
        _btn_set_enabled(self.stop_btn, True)
        if self.tray_icon is not None:
            self.root.withdraw()  # đang quay -> ẩn xuống khay, tránh chính cửa sổ app lọt vào video
        self._poll_status()

    def toggle_pause(self):
        if not (self.thread and self.thread.is_alive()):
            return
        if self.pause_event.is_set():
            self._paused_total += time.time() - self._pause_started
            self._pause_started = None
            self.pause_event.clear()
            self.pause_btn.config(text="Tạm dừng")
        else:
            self._pause_started = time.time()
            self.pause_event.set()
            self.pause_btn.config(text="Tiếp tục")

    def _poll_status(self):
        if self.thread and self.thread.is_alive():
            self.status.set(self._latest_status[0])
            paused = self.pause_event.is_set()
            live_pause = (time.time() - self._pause_started) if paused else 0.0
            elapsed = int(time.time() - self._rec_start - self._paused_total - live_pause)
            self.timer_var.set(f"{elapsed // 60:02d}:{elapsed % 60:02d}")
            if paused:
                self.rec_dot.itemconfig(self._rec_dot_id, fill=PAUSE)
            else:
                self._blink_on = not self._blink_on
                self.rec_dot.itemconfig(self._rec_dot_id, fill=DANGER if self._blink_on else SURFACE)
            self.root.after(500, self._poll_status)

    def stop(self):
        if not (self.thread and self.thread.is_alive()):
            return  # no-op an toàn khi bấm Stop từ tray lúc không quay
        self.stop_event.set()
        _btn_set_enabled(self.stop_btn, False)
        _btn_set_enabled(self.pause_btn, False)
        self.status.set("Đang dừng...")
        self._wait_finish()

    def _wait_finish(self):
        if self.thread and self.thread.is_alive():
            self.root.after(100, self._wait_finish)
            return
        self._show_window()
        self.rec_dot.itemconfig(self._rec_dot_id, fill=SURFACE)
        self.status.set(f"Đã lưu: {self.out_path}")
        _btn_set_enabled(self.start_btn, True)
        _btn_set_enabled(self.stop_btn, False)
        _btn_set_enabled(self.pause_btn, False)
        _btn_set_enabled(self.open_folder_btn, True)

    def open_folder(self):
        if self.out_path:
            os.startfile(os.path.dirname(self.out_path))


def selftest():
    """python screen_recorder.py --selftest -> record ~1s, assert valid mp4 written."""
    tmp = "selftest_out.mp4"
    ev = threading.Event()
    t = threading.Timer(4.0, ev.set)
    t.start()
    frames, elapsed = record(ev, tmp)
    assert frames > 0, "no frames captured"
    assert os.path.exists(tmp) and os.path.getsize(tmp) > 0, "mp4 not written"
    cap = cv2.VideoCapture(tmp)
    ok, _ = cap.read()
    cap.release()
    assert ok, "written mp4 is not readable"
    if sd is not None and imageio_ffmpeg is not None:
        info = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-i", tmp], capture_output=True, text=True,
        ).stderr
        assert "Audio:" in info, f"no audio stream muxed into output:\n{info}"
    os.remove(tmp)
    print(f"selftest OK: {frames} frames in {elapsed:.1f}s")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        root = tk.Tk()
        App(root)
        root.mainloop()
