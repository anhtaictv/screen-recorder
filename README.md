# Screen Recorder

**v1.1.0**

Quay màn hình offline (không tiếng) trên Windows, GUI Tkinter. Chọn vùng quay bằng cách kéo chuột hoặc quay full màn hình, xuất thẳng ra file MP4.

## Tính năng

- Chọn vùng quay tuỳ ý (kéo chuột) hoặc `Esc` để quay full màn hình
- Tự dò backend chụp màn hình: ưu tiên **DXGI/GPU** (`dxcam`, nhanh) và tự rơi về **GDI** (`mss`, luôn chạy được) nếu máy không hỗ trợ
- Ghi đúng nhịp thời gian thực, không cần remux sau khi dừng → bấm Stop là lưu xong ngay
- Mã hoá H.264 (`avc1`), tự fallback `mp4v` nếu thiếu OpenH264 DLL
- Chọn nơi lưu file khi bắt đầu quay (hộp thoại Save As)
- Chọn **FPS** (15/24/30/60) và **chất lượng** (100%/75%/50% độ phân giải) ngay trong GUI
- Đồng hồ đếm giờ quay + chấm đỏ nhấp nháy khi đang ghi
- Nút **"Mở thư mục vừa lưu"** sau khi Stop
- Hotkey toàn cục **F9** để Start/Stop nhanh (cần lib `keyboard`, thiếu thì tự tắt tính năng này, nút bấm vẫn chạy bình thường)

## Cài đặt & chạy từ source

```bash
pip install opencv-python mss numpy dxcam keyboard
python screen_recorder.py
```

`dxcam` và `keyboard` là tuỳ chọn — thiếu vẫn chạy được (mất GPU-accel hoặc hotkey F9), không crash.

## Đóng gói thành exe

```bash
pyinstaller ScreenRecorder.spec
```

File `openh264-2.5.0-win64.dll` được đóng gói kèm để hỗ trợ mã hoá H.264.

## Self-test

```bash
python screen_recorder.py --selftest
```

Quay thử ~1s, kiểm tra file MP4 sinh ra hợp lệ.
