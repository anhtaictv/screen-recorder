# Screen Recorder

**v1.0.0**

Quay màn hình offline (không tiếng) trên Windows, GUI Tkinter. Chọn vùng quay bằng cách kéo chuột hoặc quay full màn hình, xuất thẳng ra file MP4.

## Tính năng

- Chọn vùng quay tuỳ ý (kéo chuột) hoặc `Esc` để quay full màn hình
- Tự dò backend chụp màn hình: ưu tiên **DXGI/GPU** (`dxcam`, nhanh) và tự rơi về **GDI** (`mss`, luôn chạy được) nếu máy không hỗ trợ
- Ghi đúng nhịp thời gian thực (30 FPS), không cần remux sau khi dừng → bấm Stop là lưu xong ngay
- Mã hoá H.264 (`avc1`), tự fallback `mp4v` nếu thiếu OpenH264 DLL
- Chọn nơi lưu file khi bắt đầu quay (hộp thoại Save As)

## Cài đặt & chạy từ source

```bash
pip install opencv-python mss numpy dxcam
python screen_recorder.py
```

`dxcam` là tuỳ chọn — thiếu vẫn chạy được, chỉ chậm hơn (GDI).

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
