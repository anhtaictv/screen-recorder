# Screen Recorder

**v1.3.0**

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
- Chọn **định dạng xuất** (MP4/MOV/AVI) ngay trong GUI

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

## Lịch sử cập nhật

### v1.3.0 — 2026-09-10
- Chọn định dạng xuất video: MP4/MOV (H.264, fallback mp4v) hoặc AVI (XVID, fallback MJPG) ngay trong GUI.

### v1.2.0 — 2026-09-10
- Thiết kế lại giao diện: dark theme (slate + accent teal), nút bấm custom có hover, dropdown FPS/chất lượng theo theme tối, timer font đều nét, cửa sổ tự canh giữa màn hình.

### v1.1.0 — 2026-09-10
- Đồng hồ đếm giờ quay + chấm đỏ nhấp nháy khi đang ghi
- Nút "Mở thư mục vừa lưu" sau khi Stop
- Hotkey toàn cục F9 để Start/Stop
- Chọn FPS (15/24/30/60) và chất lượng (100%/75%/50%) ngay trong GUI

### v1.0.0 — 2026-09-10
- Bản đầu: quay màn hình/vùng chọn, tự dò backend DXGI/GDI, xuất MP4 H.264 (fallback mp4v), chọn nơi lưu file khi bắt đầu quay.
