# Screen Recorder

**v1.5.0**

Quay màn hình offline trên Windows, GUI Tkinter, kèm ghi âm mic tuỳ chọn. Chọn vùng quay bằng cách kéo chuột hoặc quay full màn hình, xuất thẳng ra file video có tiếng.

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
- Chọn **màn hình** khi máy có nhiều monitor (khung chọn vùng tự phủ đúng màn hình đã chọn, kể cả màn hình phụ)
- **Tạm dừng/Tiếp tục** khi đang quay (video đứng hình lúc tạm dừng, không bị dồn khung khi tiếp tục)
- **Nhớ cấu hình lần trước** (FPS/chất lượng/định dạng/màn hình/thư mục lưu) trong `config.json` cạnh app
- **Thu nhỏ xuống khay hệ thống** khi đang quay (nếu có lib `pystray`) — cửa sổ tự ẩn để không lọt vào video, click icon khay để hiện lại, menu chuột phải có "Dừng quay" và "Thoát"
- **Ghi âm micro** kèm video (checkbox trong GUI, mặc định bật) — thu song song với hình, tự khớp thời lượng qua nút Tạm dừng, ghép vào file cuối bằng ffmpeg kèm sẵn; thiếu lib thì tự tắt và quay video câm như cũ

## Cài đặt & chạy từ source

```bash
pip install opencv-python mss numpy dxcam keyboard pystray pillow sounddevice imageio-ffmpeg
python screen_recorder.py
```

`dxcam`, `keyboard`, `pystray`/`pillow`, `sounddevice`/`imageio-ffmpeg` đều là tuỳ chọn — thiếu vẫn chạy được (mất GPU-accel, hotkey F9, khay hệ thống, hoặc ghi mic), không crash.

## Đóng gói thành exe

```bash
pyinstaller ScreenRecorder.spec
```

File `openh264-2.5.0-win64.dll` được đóng gói kèm để hỗ trợ mã hoá H.264.

## Self-test

```bash
python screen_recorder.py --selftest
```

Quay thử ~1s, kiểm tra file MP4 sinh ra hợp lệ (có thêm kiểm tra stream audio khi mic khả dụng).

## Lịch sử cập nhật

### v1.5.0 — 2026-09-10
- Ghi âm micro song song với video, ghép vào file cuối bằng ffmpeg (kèm sẵn qua `imageio-ffmpeg`, không cần cài riêng).
- Checkbox "Ghi âm micro" trong GUI, nhớ lựa chọn vào config.
- Lỗi mic/ghép âm tự fallback về video câm, không mất bản quay.

### v1.4.0 — 2026-09-10
- Chọn màn hình khi có nhiều monitor, overlay chọn vùng phủ đúng màn hình đã chọn.
- Tạm dừng/Tiếp tục khi đang quay.
- Nhớ cấu hình lần trước (FPS/chất lượng/định dạng/màn hình/thư mục lưu).
- Thu nhỏ xuống khay hệ thống khi đang quay, menu tray Dừng quay/Thoát.

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
