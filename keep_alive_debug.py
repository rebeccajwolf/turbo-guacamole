from flask import Flask, send_file, jsonify, render_template_string
import threading
import time
import random
import os
from pathlib import Path
from datetime import datetime
import logging
from io import BytesIO
import base64

app = Flask(__name__)

# HTML template for the screenshots viewer interface
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Screenshots Viewer</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .screenshots-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        .screenshot-card {
            background: white;
            border-radius: 8px;
            padding: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .screenshot-card img {
            width: 100%;
            height: 200px;
            object-fit: cover;
            border-radius: 4px;
            cursor: pointer;
        }
        .screenshot-info {
            margin-top: 10px;
            font-size: 14px;
            color: #666;
        }
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.8);
            z-index: 1000;
        }
        .modal-content {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            max-width: 90%;
            max-height: 90%;
        }
        .modal-content img {
            max-width: 100%;
            max-height: 90vh;
        }
        .close {
            position: absolute;
            top: 15px;
            right: 15px;
            color: white;
            font-size: 30px;
            cursor: pointer;
        }
        .refresh-btn {
            background: #4CAF50;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
        }
        .refresh-btn:hover {
            background: #45a049;
        }
        .no-screenshots {
            text-align: center;
            padding: 40px;
            color: #666;
        }
    </style>
</head>
<body>
    <h1>Screenshots Viewer</h1>
    <button class="refresh-btn" onclick="location.reload()">Refresh</button>
    
    <div class="screenshots-grid">
        {% if screenshots %}
            {% for screenshot in screenshots %}
                <div class="screenshot-card">
                    <img src="{{ screenshot.download_url }}" 
                         onclick="openModal('{{ screenshot.download_url }}')"
                         alt="{{ screenshot.name }}">
                    <div class="screenshot-info">
                        <div>Name: {{ screenshot.name }}</div>
                        <div>Time: {{ screenshot.timestamp }}</div>
                        <div>Size: {{ (screenshot.size / 1024)|round(1) }} KB</div>
                        <a href="{{ screenshot.download_url }}" download>Download</a>
                    </div>
                </div>
            {% endfor %}
        {% else %}
            <div class="no-screenshots">
                <h2>No screenshots available</h2>
                <p>Screenshots will appear here when taken</p>
            </div>
        {% endif %}
    </div>

    <div id="imageModal" class="modal" onclick="closeModal()">
        <span class="close">&times;</span>
        <div class="modal-content">
            <img id="modalImage" src="">
        </div>
    </div>

    <script>
        function openModal(imgUrl) {
            document.getElementById('imageModal').style.display = 'block';
            document.getElementById('modalImage').src = imgUrl;
        }

        function closeModal() {
            document.getElementById('imageModal').style.display = 'none';
        }

        // Close modal on escape key
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                closeModal();
            }
        });
    </script>
</body>
</html>
"""

def background_activity():
    """Simulate background activity without triggering container detection"""
    while True:
        time.sleep(random.uniform(30, 60))
        _ = sum(i * i for i in range(100))

@app.route('/')
def home():
    """Simple home route that confirms the app is running"""
    return "App is Running..."

@app.route('/screenshots')
def screenshots():
    """Display screenshots in a grid view"""
    try:
        screenshots_dir = Path(__file__).parent / "screenshots"
        if not screenshots_dir.exists():
            screenshots = []
        else:
            screenshots = []
            for file in screenshots_dir.glob("*.png"):
                screenshots.append({
                    "name": file.name,
                    "timestamp": datetime.fromtimestamp(file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "size": file.stat().st_size,
                    "download_url": f"/screenshots/download/{file.name}"
                })
            screenshots.sort(key=lambda x: x["timestamp"], reverse=True)
            
        return render_template_string(HTML_TEMPLATE, screenshots=screenshots)
        
    except Exception as e:
        logging.error(f"Error rendering screenshots page: {str(e)}")
        return "Error loading screenshots", 500

@app.route('/screenshots/download/<filename>')
def download_screenshot(filename):
    """Download a specific screenshot"""
    try:
        screenshots_dir = Path(__file__).parent / "screenshots"
        file_path = screenshots_dir / filename
        
        if not file_path.exists() or not file_path.is_file():
            return jsonify({"error": "Screenshot not found"}), 404
            
        return send_file(
            file_path,
            mimetype='image/png',
            as_attachment=False  # Changed to false to display in browser
        )
        
    except Exception as e:
        logging.error(f"Error downloading screenshot: {str(e)}")
        return jsonify({"error": "Failed to download screenshot"}), 500

def start_background_thread():
    thread = threading.Thread(target=background_activity, daemon=True)
    thread.start()

# Start background activity when the app starts
start_background_thread()

if __name__ == "__main__":
    app.config['ENV'] = 'production'
    app.config['PROPAGATE_EXCEPTIONS'] = False
    app.run()