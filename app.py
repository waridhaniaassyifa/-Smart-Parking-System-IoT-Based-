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
socketio = SocketIO(app, cors_allowed_origins="*", 
                   ping_timeout=60, ping_interval=25,
                   max_http_buffer_size=10000000)
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
active_camera_id = None
camera_lock = False
placeholder_frame = None

def init_placeholder():
    global placeholder_frame
    if placeholder_frame is None:
        temp = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(temp, "Waiting for mobile...", (150, 240), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        _, buffer = cv2.imencode('.jpg', temp)
        placeholder_frame = buffer.tobytes()

def get_camera():
    global cap, camera_url, DEFAULT_WEBCAM_INDEX
    if cap is None or not cap.isOpened():
        max_retries = 3
        retry_delay = 1  # detik
        
        for attempt in range(max_retries):
            try:
                if camera_url:  # IP Camera
                    print(f"Connecting to IP camera: {camera_url} (attempt {attempt + 1}/{max_retries})")
                    
                    # Tambah timeout dan buffer untuk IP camera
                    cap = cv2.VideoCapture(camera_url, cv2.CAP_FFMPEG)
                    
                    # Set properties untuk IP camera
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 3)
                    cap.set(cv2.CAP_PROP_FPS, 30)
                    
                else:  # webcam / DroidCam
                    print(f"Connecting to webcam index: {DEFAULT_WEBCAM_INDEX} (attempt {attempt + 1}/{max_retries})")
                    cap = cv2.VideoCapture(DEFAULT_WEBCAM_INDEX)
                
                # Test apakah kamera benar-benar bisa dibaca
                if cap.isOpened():
                    ret, test_frame = cap.read()
                    if ret and test_frame is not None:
                        # Set properties untuk performa
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        cap.set(cv2.CAP_PROP_FPS, 30)
                        
                        print(f"✓ Camera opened successfully! Frame shape: {test_frame.shape}")
                        return cap
                    else:
                        print(f"✗ Camera opened but cannot read frame")
                        cap.release()
                        cap = None
                else:
                    print(f"✗ Camera failed to open")
                    cap = None
                
                # Retry dengan delay
                if attempt < max_retries - 1:
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    
            except Exception as e:
                print(f"✗ Error opening camera: {str(e)}")
                if cap:
                    cap.release()
                cap = None
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
        
        # Jika semua retry gagal
        print(f"ERROR: Failed to open camera after {max_retries} attempts")
        print(f"Camera URL: {camera_url}, Webcam Index: {DEFAULT_WEBCAM_INDEX}")
        return None
    
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
    global cap, camera_url, DEFAULT_WEBCAM_INDEX, background_frame, camera_lock
    data = request.get_json()
    ip = data.get("ip")
    idx = data.get("index")

    print(f"Setting camera - IP: {ip}, Index: {idx}")

    # Lock to prevent race conditions
    camera_lock = True
    
    try:
        # Release current camera
        if cap is not None:
            cap.release()
            cap = None
            time.sleep(0.5)

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
        if cam and cam.isOpened():
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
    finally:
        camera_lock = False

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
    """Mobile camera page - hanya bisa diakses via tunnel"""
    if token not in mobile_tokens:
        return "Invalid or expired token", 403
    
    # Cek apakah menggunakan tunnel (bukan localhost/IP lokal)
    host = request.host.lower()
    if 'localhost' in host or '127.0.0.1' in host or host.startswith('192.168.') or host.startswith('10.'):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Tunnel Required</title>
            <style>
                body {
                    margin: 0;
                    padding: 20px;
                    font-family: Arial, sans-serif;
                    background: #000;
                    color: #fff;
                    text-align: center;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    min-height: 100vh;
                }
                .container {
                    max-width: 500px;
                    padding: 30px;
                    background: #1a1a1a;
                    border-radius: 10px;
                }
                h2 { color: #ef4444; }
                code {
                    background: #333;
                    padding: 2px 8px;
                    border-radius: 4px;
                    color: #4ade80;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h2>⚠️ Cloudflare Tunnel Required</h2>
                <p>Mobile camera hanya bisa diakses melalui Cloudflare Tunnel.</p>
                <br>
                <p><strong>Cara menggunakan:</strong></p>
                <ol style="text-align: left;">
                    <li>Jalankan: <code>cloudflared tunnel --url http://localhost:5000</code></li>
                    <li>Set URL public di Settings</li>
                    <li>Generate ulang QR code</li>
                    <li>Scan QR dengan HP Anda</li>
                </ol>
            </div>
        </body>
        </html>
        """, 403
    
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
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + placeholder_frame + b'\r\n')
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
        threshold = 0.05  # 5% change threshold (lebih sensitif)
        results[slot["id"]] = "occupied" if change_ratio > threshold else "empty"

    return results

@app.route("/video")
def video():
    def generate():
        global camera_lock
        
        # Wait if camera is being switched
        retry = 0
        while camera_lock and retry < 50:
            time.sleep(0.1)
            retry += 1

        cam = get_camera()
        consecutive_failures = 0
        max_failures = 30  # Kurangi dari 60 ke 30 untuk reconnect lebih cepat
        reconnect_attempts = 0
        max_reconnect = 999
        frame_skip = 0  # Counter untuk skip frame jika IP camera lambat
        
        while True:
            if cam is None or not cam.isOpened():
                print(f"Camera disconnected. Reconnect attempt {reconnect_attempts + 1}/{max_reconnect}")
                time.sleep(2)
                cam = get_camera()
                reconnect_attempts += 1
                consecutive_failures = 0
                frame_skip = 0
                continue
            
            try:
                # Untuk IP camera, skip frame jika buffer penuh
                if camera_url and frame_skip > 0:
                    cam.grab()  # Skip frame tanpa decode
                    frame_skip -= 1
                    continue
                
                ret, frame = cam.read()
                
                if not ret or frame is None:
                    consecutive_failures += 1
                    print(f"Failed to read frame (attempt {consecutive_failures}/{max_failures})")
                    
                    if consecutive_failures >= max_failures:
                        print("Too many failures, releasing camera...")
                        if cam is not None:
                            cam.release()
                        cam = None
                        consecutive_failures = 0
                        frame_skip = 0
                    else:
                        time.sleep(0.1)
                    continue
                
                # Reset counters jika berhasil
                consecutive_failures = 0
                reconnect_attempts = 0
                
                # Untuk IP camera, set skip untuk frame berikutnya (reduce lag)
                if camera_url:
                    frame_skip = 2  # Skip 2 frame berikutnya
                
                # Resize jika frame terlalu besar (untuk IP camera HD)
                height, width = frame.shape[:2]
                if width > 1280:
                    scale = 1280 / width
                    frame = cv2.resize(frame, None, fx=scale, fy=scale)
                
                time.sleep(0.033)  # ~30 FPS
                    
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                       
            except Exception as e:
                print(f"Error in video stream: {str(e)}")
                consecutive_failures += 1
                time.sleep(0.1)
                   
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
    
    init_placeholder()
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