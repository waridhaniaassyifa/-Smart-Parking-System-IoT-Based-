from flask import Flask, render_template, Response, jsonify, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from io import BytesIO
import numpy as np
import secrets
import qrcode
import base64
import time
import cv2
import socket
import requests
from threading import Thread

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# variable global untuk mobile camera
mobile_frames = {}  # Store frames from mobile: {token: frame_data}
mobile_tokens = {}  # Store active tokens: {token: timestamp}

# Global variables
cap = None
camera_url = None
DEFAULT_WEBCAM_INDEX = 0
background_frame = None
slots = []
PUBLIC_URL = None
LOCAL_IP = None

def get_camera():
    global cap, camera_url, DEFAULT_WEBCAM_INDEX
    if cap is None or not cap.isOpened():
        if camera_url:  # IP Camera
            print(f"Connecting to IP camera: {camera_url}")
            cap = cv2.VideoCapture(camera_url)
            # Set buffer size to reduce latency for IP cameras
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        else:  # webcam / DroidCam
            print(f"Connecting to webcam index: {DEFAULT_WEBCAM_INDEX}")
            cap = cv2.VideoCapture(DEFAULT_WEBCAM_INDEX)
        
        # JANGAN fallback ke index 0 otomatis - biarkan gagal dengan jelas
        if not cap.isOpened():
            print(f"ERROR: Kamera di index {DEFAULT_WEBCAM_INDEX} tidak tersedia!")
            print(f"Tip: Pastikan DroidCam Client berjalan dan kabel USB stabil")
            return None
        
        # Set camera properties for better performance
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        print(f"Camera opened successfully!")
    
    return cap

def get_local_ip():
    """Dapatkan IP lokal komputer"""
    try:
        # Buat socket dummy untuk mendapatkan IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except:
        return "127.0.0.1"

def detect_cloudflare_tunnel():
    """Deteksi apakah cloudflared sedang berjalan"""
    global PUBLIC_URL
    try:
        # Cloudflare tunnel metrics biasanya di port 41397
        response = requests.get("http://127.0.0.1:41397/metrics", timeout=2)
        if response.status_code == 200:
            # Parse URL dari metrics (simplified)
            metrics_text = response.text
            if "cloudflared" in metrics_text:
                print("✓ Cloudflare tunnel detected!")
                return True
    except:
        pass
    return False

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/set_camera", methods=["POST"])
def set_camera():
    global cap, camera_url, DEFAULT_WEBCAM_INDEX, background_frame
    data = request.get_json()
    ip = data.get("ip")
    idx = data.get("index")

    print(f"Setting camera - IP: {ip}, Index: {idx}")

    # Release current camera
    if cap is not None:
        cap.release()
        cap = None
        time.sleep(0.5)  # Give time for camera to release

    # Set new camera
    camera_url = ip if ip else None
    if idx is not None and not ip:
        try:
            DEFAULT_WEBCAM_INDEX = int(idx)
        except:
            DEFAULT_WEBCAM_INDEX = 0

    # Reset background when camera changes
    background_frame = None
    
    # Initialize new camera
    cam = get_camera()
    if cam.isOpened():
        # Test read to ensure camera works
        ret, frame = cam.read()
        if ret:
            print(f"Camera test successful! Frame shape: {frame.shape}")
            return jsonify({
                "status": "ok", 
                "camera": camera_url or f"webcam {DEFAULT_WEBCAM_INDEX}",
                "resolution": f"{frame.shape[1]}x{frame.shape[0]}"
            })
        else:
            print("Camera opened but cannot read frame")
            return jsonify({
                "status": "error", 
                "message": "Camera opened but cannot read frame"
            }), 400
    else:
        return jsonify({
            "status": "error", 
            "message": "Failed to open camera"
        }), 400

@app.route("/generate_mobile_link", methods=["POST"])
def generate_mobile_link():
    """Generate unique link for mobile camera"""
    global LOCAL_IP, PUBLIC_URL
    
    token = secrets.token_urlsafe(16)
    mobile_tokens[token] = time.time()
    
    # Deteksi mode: lokal atau online
    if PUBLIC_URL:
        mobile_url = f"{PUBLIC_URL}/mobile/{token}"
        mode = "online (Cloudflare)"
    else:
        if not LOCAL_IP:
            LOCAL_IP = get_local_ip()
        mobile_url = f"http://{LOCAL_IP}:5000/mobile/{token}"
        mode = "local network"
    
    print(f"Generated mobile link ({mode}): {mobile_url}")
    
    # Generate QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(mobile_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode()
    
    return jsonify({
        "status": "ok",
        "token": token,
        "url": mobile_url,
        "mode": mode,
        "qr_code": f"data:image/png;base64,{qr_base64}"
    })

@app.route("/mobile/<token>")
def mobile_camera(token):
    """Mobile camera page"""
    if token not in mobile_tokens:
        return "Invalid or expired token", 403
    
    return render_template("mobile.html", token=token)

@app.route("/mobile_video/<token>")
def mobile_video(token):
    """Stream dari mobile camera"""
    def generate():
        while True:
            if token in mobile_frames:
                frame_data = mobile_frames[token]
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')
            else:
                # Kirim placeholder jika belum ada frame
                placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(placeholder, "Waiting for mobile...", (150, 240), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                _, buffer = cv2.imencode('.jpg', placeholder)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(0.1)
    
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/reset_background", methods=["POST"])
def reset_background():
    global background_frame
    cam = get_camera()
    ret, frame = cam.read()
    
    if ret:
        background_frame = frame.copy()
        print(f"Background reset! Frame shape: {frame.shape}")
        return jsonify({
            "status": "ok",
            "message": "Background reset berhasil! Sekarang frame ini akan jadi referensi kosong."
        })
    else:
        return jsonify({
            "status": "error",
            "message": "Gagal mengambil frame untuk background"
        }), 400

@app.route("/update_slots", methods=["POST"])
def update_slots():
    global slots
    data = request.get_json()
    slots = data.get("slots", [])
    print(f"Updated slots: {len(slots)} slots received")
    return jsonify({"status": "ok", "slots_count": len(slots)})

def detect_parking_status(frame):
    """
    Deteksi berdasarkan perbedaan dengan background
    - empty (merah): sama seperti background
    - occupied (hijau): berbeda dari background
    """
    global background_frame, slots
    
    results = {}
    
    if frame is None or background_frame is None or len(slots) == 0:
        for slot in slots:
            results[slot["id"]] = "empty"
        return results

    for slot in slots:
        # Get ROI coordinates with bounds checking
        x, y, w, h = slot["x"], slot["y"], slot["w"], slot["h"]
        
        y1 = max(0, int(y))
        y2 = min(frame.shape[0], int(y + h))
        x1 = max(0, int(x))
        x2 = min(frame.shape[1], int(x + w))
        
        if y2 <= y1 or x2 <= x1:
            results[slot["id"]] = "empty"
            continue
            
        # Extract ROI from current frame and background
        roi_current = frame[y1:y2, x1:x2]
        roi_background = background_frame[y1:y2, x1:x2]
        
        if roi_current.size == 0 or roi_background.size == 0:
            results[slot["id"]] = "empty"
            continue
        
        # Calculate difference between current frame and background
        diff = cv2.absdiff(roi_background, roi_current)
        diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        
        # Apply threshold to get binary image
        _, thresh = cv2.threshold(diff_gray, 30, 255, cv2.THRESH_BINARY)
        
        # Calculate change ratio
        change_pixels = np.sum(thresh > 0)
        total_pixels = thresh.size
        change_ratio = change_pixels / total_pixels if total_pixels > 0 else 0
        
        # Determine status based on change ratio
        threshold = 0.05  # 5% change threshold
        results[slot["id"]] = "occupied" if change_ratio > threshold else "empty"

    return results

@app.route("/video")
def video():
    def generate():
        cam = get_camera()
        consecutive_failures = 0
        max_failures = 30
        reconnect_attempts = 0
        max_reconnect = 5
        
        while True:
            if cam is None or not cam.isOpened():
                if reconnect_attempts >= max_reconnect:
                    # UBAH INI: Jangan break, kirim placeholder image
                    print("Max reconnect attempts reached. Sending placeholder...")
                    
                    # Buat frame hitam dengan teks error
                    placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                    cv2.putText(placeholder, "Camera Disconnected", (150, 240), 
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                    _, buffer = cv2.imencode('.jpg', placeholder)
                    
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                    
                    # Reset dan coba lagi setelah delay
                    time.sleep(5)
                    reconnect_attempts = 0
                    cam = get_camera()
                    continue
                
                print(f"Camera disconnected. Reconnect attempt {reconnect_attempts + 1}/{max_reconnect}")
                time.sleep(2)
                cam = get_camera()
                reconnect_attempts += 1
                consecutive_failures = 0
                continue
            
            ret, frame = cam.read()
            if not ret:
                consecutive_failures += 1
                print(f"Failed to read frame (attempt {consecutive_failures}/{max_failures})")
                
                if consecutive_failures >= max_failures:
                    print("Too many failures, releasing camera...")
                    if cam is not None:  # TAMBAHKAN pengecekan
                        cam.release()
                    cam = None
                    consecutive_failures = 0
                else:
                    time.sleep(0.1)
                continue
            
            consecutive_failures = 0
            reconnect_attempts = 0
                
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                   
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/status")
def status():
    cam = get_camera()
    ret, frame = cam.read()
    
    if not ret:
        # Return empty status if can't read frame
        return jsonify({slot["id"]: "empty" for slot in slots})
    
    # Detect parking status
    detection_results = detect_parking_status(frame)
    
    return jsonify(detection_results)

@app.route("/debug")
def debug():
    """Debug endpoint to check system status"""
    global background_frame, slots, cap
    
    cam_opened = cap is not None and cap.isOpened()
    frame_readable = False
    frame_shape = None
    
    if cam_opened:
        ret, frame = cap.read()
        if ret:
            frame_readable = True
            frame_shape = frame.shape
    
    debug_info = {
        "background_set": background_frame is not None,
        "slots_count": len(slots),
        "camera_opened": cam_opened,
        "camera_url": camera_url,
        "webcam_index": DEFAULT_WEBCAM_INDEX,
        "frame_readable": frame_readable,
        "frame_shape": frame_shape
    }
    
    return jsonify(debug_info)

@app.route("/test_camera", methods=["GET"])
def test_camera():
    """Test endpoint untuk cek semua kamera yang tersedia"""
    available_cameras = []
    
    # Test webcam indices 0-5
    for i in range(6):
        test_cap = cv2.VideoCapture(i)
        if test_cap.isOpened():
            ret, frame = test_cap.read()
            if ret:
                available_cameras.append({
                    "index": i,
                    "type": "webcam",
                    "resolution": f"{frame.shape[1]}x{frame.shape[0]}"
                })
            test_cap.release()
    
    return jsonify({
        "available_cameras": available_cameras,
        "total": len(available_cameras)
    })

@socketio.on('mobile_frame')
def handle_mobile_frame(data):
    """Receive frame from mobile"""
    token = data.get('token')
    frame_base64 = data.get('frame')
    
    if token in mobile_tokens:
        # Decode base64 to bytes
        frame_bytes = base64.b64decode(frame_base64.split(',')[1])
        mobile_frames[token] = frame_bytes
        emit('frame_received', {'status': 'ok'})

@app.route("/set_public_url", methods=["POST"])
def set_public_url():
    """Set public URL dari cloudflare tunnel"""
    global PUBLIC_URL
    data = request.get_json()
    url = data.get("url", "").strip()
    
    if url:
        # Pastikan URL tidak berakhir dengan slash
        PUBLIC_URL = url.rstrip('/')
        print(f"✓ Public URL set to: {PUBLIC_URL}")
        return jsonify({"status": "ok", "url": PUBLIC_URL})
    else:
        PUBLIC_URL = None
        print("✓ Public URL cleared (using local IP)")
        return jsonify({"status": "ok", "message": "Using local IP"})

if __name__ == "__main__":
    print("=" * 50)
    print("Smart Parking System Backend Starting...")
    print("=" * 50)
    
    # Deteksi IP lokal
    LOCAL_IP = get_local_ip()
    print(f"Local IP: {LOCAL_IP}")
    
    # Cek cloudflare tunnel
    if detect_cloudflare_tunnel():
        print("⚠ Cloudflare tunnel detected!")
        print("Set public URL via: POST /set_public_url")
    
    print("Testing available cameras...")
    
    # Test available cameras on startup
    for i in range(3):
        test_cap = cv2.VideoCapture(i)
        if test_cap.isOpened():
            ret, _ = test_cap.read()
            if ret:
                print(f"✓ Camera {i} available")
            else:
                print(f"✗ Camera {i} opened but cannot read")
            test_cap.release()
        else:
            print(f"✗ Camera {i} not available")
    
    print("=" * 50)
    print(f"Server running on:")
    print(f"  Local:    http://localhost:5000")
    print(f"  Network:  http://{LOCAL_IP}:5000")
    print("=" * 50)
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)