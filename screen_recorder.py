"""Quay màn hình offline, xuất MP4 không tiếng. Deps: opencv-python, mss, numpy (mss cài qua `pip install mss`)."""
import sys
import os
import time
import queue
import threading
import tkinter as tk
from tkinter import filedialog
from datetime import datetime

import cv2
import numpy as np
import mss


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

MAX_FPS = 30  # trần fps mong muốn; fps thực dùng để ghi file được đo tự động (trần vật lý của máy có thể thấp hơn)


def _bbox_to_region(bbox):
    """bbox kiểu PIL (x0,y0,x1,y1) -> dict vùng chụp của mss. None = toàn màn hình chính."""
    if bbox is None:
        with mss.MSS() as sct:
            mon = sct.monitors[1]
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


def _open_writer(out_path, fps, w, h):
    """H.264 (avc1) nén nhẹ hơn mp4v ~6-7 lần cùng chất lượng/độ phân giải; cần openh264 DLL nên
    fallback về mp4v (luôn có sẵn trong OpenCV) nếu máy thiếu DLL đó."""
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"avc1"), fps, (w, h))
    if writer.isOpened():
        return writer
    writer.release()
    return cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))


def record(stop_event: threading.Event, out_path: str, status_cb=None, bbox=None):
    """Ghi thẳng 1 lần vào file cuối cùng, đúng nhịp thời gian thực (interval cố định theo MAX_FPS):
    lặp lại khung mới nhất nếu máy chưa kịp chụp khung mới, giống mọi phần mềm quay màn hình thật.
    Nhờ ghi đúng nhịp thời gian thực, số khung/MAX_FPS luôn tự khớp thời lượng thực — không cần đo
    trước hay mã hoá lại (remux) sau khi quay xong, nên bấm Stop là lưu xong ngay lập tức."""
    region = _bbox_to_region(bbox)
    backend_name, cap_thread, cap_stop, q, first = _start_capture(region)
    if status_cb:
        status_cb(f"Backend: {backend_name}")
    h, w = first.shape[:2]

    interval = 1.0 / MAX_FPS
    frames = 0
    latest = first
    writer = _open_writer(out_path, MAX_FPS, w, h)
    start = time.time()
    next_due = start
    try:
        while not stop_event.is_set():
            try:
                while True:  # rút cạn hàng đợi, chỉ giữ khung mới nhất
                    latest = q.get_nowait()
            except queue.Empty:
                pass
            now = time.time()
            if now < next_due:
                time.sleep(min(next_due - now, 0.01))
                continue
            writer.write(latest)
            frames += 1
            next_due += interval
            if status_cb:
                status_cb(f"[{backend_name}] Recording... {frames} frames ({frames/MAX_FPS:.0f}s)")
    finally:
        writer.release()
        cap_stop.set()
        cap_thread.join(timeout=1)
    return frames, time.time() - start


class RegionSelector:
    """Overlay toàn màn hình, kéo chuột để vẽ khung vùng quay. Esc = huỷ (quay full màn hình)."""

    def __init__(self, root):
        self.result = None
        self.start_xy = None
        self.rect = None
        self.top = tk.Toplevel(root)
        self.top.attributes("-fullscreen", True)
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
            self.top, text="Kéo chuột để chọn vùng quay  |  Esc = quay full màn hình",
            fg="white", bg="black",
        ).place(relx=0.5, rely=0.02, anchor="n")

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
        self.result = None
        self.top.destroy()

    def get_region(self):
        self.top.wait_window()
        if self.result and (self.result[2] - self.result[0] >= 10) and (self.result[3] - self.result[1] >= 10):
            return self.result
        return None


class App:
    def __init__(self, root):
        self.root = root
        root.title("Screen Recorder (offline, no audio)")
        self.stop_event = None
        self.thread = None

        self.status = tk.StringVar(value="Ready")
        tk.Label(root, textvariable=self.status, width=40).pack(padx=10, pady=10)

        self.start_btn = tk.Button(root, text="Start (chọn vùng)", width=20, command=self.start)
        self.start_btn.pack(pady=5)
        self.stop_btn = tk.Button(root, text="Stop", width=20, command=self.stop, state=tk.DISABLED)
        self.stop_btn.pack(pady=5)

    def start(self):
        default_dir = os.path.join(_app_base_dir(), "recordings")
        os.makedirs(default_dir, exist_ok=True)
        out_path = filedialog.asksaveasfilename(
            title="Chọn nơi lưu video",
            initialdir=default_dir,
            initialfile=datetime.now().strftime("record_%Y%m%d_%H%M%S.mp4"),
            defaultextension=".mp4",
            filetypes=[("Video MP4", "*.mp4")],
        )
        if not out_path:
            return  # người dùng bấm Cancel -> không quay
        self.out_path = out_path
        self.root.withdraw()  # ẩn cửa sổ chính để không lọt vào khung chọn/video
        self.root.after(150, lambda: self._pick_region_and_record(out_path))

    def _pick_region_and_record(self, out_path):
        selector = RegionSelector(self.root)
        bbox = selector.get_region()
        self.root.deiconify()

        self.status.set(f"Sẽ lưu vào: {out_path}")
        self.stop_event = threading.Event()
        # Tkinter chỉ an toàn khi thao tác từ 1 thread duy nhất (kể cả gọi after() từ thread khác cũng
        # có thể làm treo Tcl interpreter) -> thread nền chỉ ghi vào biến thường, thread chính tự poll.
        self._latest_status = ["Recording..."]
        self.thread = threading.Thread(
            target=record,
            args=(self.stop_event, out_path),
            kwargs={"status_cb": lambda s: self._latest_status.__setitem__(0, s), "bbox": bbox},
            daemon=True,
        )
        self.thread.start()
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self._poll_status()

    def _poll_status(self):
        if self.thread and self.thread.is_alive():
            self.status.set(self._latest_status[0])
            self.root.after(100, self._poll_status)

    def stop(self):
        if self.stop_event:
            self.stop_event.set()
        self.stop_btn.config(state=tk.DISABLED)
        self.status.set("Đang dừng...")
        self._wait_finish()

    def _wait_finish(self):
        if self.thread and self.thread.is_alive():
            self.root.after(100, self._wait_finish)
            return
        self.status.set(f"Đã lưu: {self.out_path}")
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)


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
    os.remove(tmp)
    print(f"selftest OK: {frames} frames in {elapsed:.1f}s")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        root = tk.Tk()
        App(root)
        root.mainloop()
