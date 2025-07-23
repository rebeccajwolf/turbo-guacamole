from flask import Flask
import threading
import time
import random
import psutil
import os
from datetime import datetime
import subprocess

app = Flask(__name__)

def get_system_info():
    """Get current system information for logging"""
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    # Get process information with name and PID
    process_info = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            process_info.append({
                'pid': proc.info['pid'],
                'name': proc.info['name'],
                'cpu': proc.info['cpu_percent'],
                'memory': proc.info['memory_percent']
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    
    return {
        'memory_used_percent': memory.percent,
        'cpu_percent': psutil.cpu_percent(interval=0.1),
        'disk_used_percent': disk.percent,
        'processes': process_info
    }

def simulate_activity():
    """Creates a small amount of system activity to prevent idle detection"""
    # Create a small file in /tmp
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    with open(f"/tmp/activity_{timestamp}.txt", "w") as f:
        f.write(f"Activity timestamp: {timestamp}\n")
    
    # Read it back
    with open(f"/tmp/activity_{timestamp}.txt", "r") as f:
        content = f.read()
    
    # Remove older activity files to keep things clean
    for file in os.listdir("/tmp"):
        if file.startswith("activity_") and file.endswith(".txt"):
            file_path = os.path.join("/tmp", file)
            file_time = os.path.getmtime(file_path)
            if time.time() - file_time > 3600:  # Older than 1 hour
                os.remove(file_path)
    
    # Small CPU activity
    _ = sum(i * i for i in range(1000))

def check_browser_processes():
    """Check for browser processes and their resource usage"""
    browser_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
        try:
            proc_name = proc.info['name'].lower()
            if 'chrome' in proc_name or 'chromium' in proc_name:
                browser_processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'memory_mb': round(proc.info['memory_info'].rss / (1024 * 1024), 2),
                    'cpu_percent': proc.info['cpu_percent']
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    
    return browser_processes

def weston_health_check():
    """Check if Weston is running properly and restart if needed"""
    weston_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            if 'weston' in proc.info['name'].lower():
                weston_processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'cpu': proc.info['cpu_percent'],
                    'memory': proc.info['memory_percent']
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    if not weston_processes:
        try:
            # Setup environment
            runtime_dir = os.environ.get('XDG_RUNTIME_DIR', '/tmp/runtime-user')
            wayland_display = os.environ.get('WAYLAND_DISPLAY', 'wayland-1')
            
            # Ensure runtime directory exists with correct permissions
            os.makedirs(runtime_dir, exist_ok=True)
            os.chmod(runtime_dir, 0o700)
            
            # Start Weston
            with open(os.devnull, 'w') as devnull:
                subprocess.Popen(
                    [
                        '/usr/bin/weston',
                        '--backend=headless-backend.so',
                        '--width=1920',
                        '--height=1080'
                    ],
                    stdout=devnull,
                    stderr=devnull,
                    env=os.environ.copy()
                )
            
            # Wait for Weston to start
            socket_path = os.path.join(runtime_dir, wayland_display)
            start_time = time.time()
            while not os.path.exists(socket_path) and time.time() - start_time < 10:
                time.sleep(0.5)
                
            return True
        except Exception as e:
            return False
    
    return weston_processes

def background_activity():
    """Enhanced background activity to prevent container sleep"""
    while True:
        try:
            # Random sleep between 30-90 seconds
            sleep_time = random.uniform(30, 90)
            time.sleep(sleep_time)
            
            # System activity
            simulate_activity()
            
            # Check browser processes
            browser_info = check_browser_processes()
            
            # Check Weston health
            weston_info = weston_health_check()
            
            # Get system info
            sys_info = get_system_info()
            
            # Log activity (without flooding logs)
            if random.random() < 0.1:  # Only log 10% of the time
                with open("/tmp/keepalive_log.txt", "a") as f:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"{timestamp} - Keep alive active.\n")
                    f.write("System Processes:\n")
                    for proc in sys_info['processes']:
                        f.write(f"  {proc['name']} (PID: {proc['pid']}) - CPU: {proc['cpu']}%, MEM: {round(proc['memory'], 2)}%\n")
                    f.write("Browser Processes:\n")
                    for proc in browser_info:
                        f.write(f"  {proc['name']} (PID: {proc['pid']}) - MEM: {proc['memory_mb']}MB, CPU: {proc['cpu_percent']}%\n")
                    if isinstance(weston_info, list):
                        f.write("Weston Processes:\n")
                        for proc in weston_info:
                            f.write(f"  {proc['name']} (PID: {proc['pid']}) - CPU: {proc['cpu']}%, MEM: {round(proc['memory'], 2)}%\n")
                    else:
                        f.write("Weston Status: Not Running\n")
                    f.write("\n")
        except Exception as e:
            # If any error occurs, wait a bit and continue
            time.sleep(10)

@app.route('/')
def home():
    """Status endpoint with system information"""
    sys_info = get_system_info()
    browser_info = check_browser_processes()
    weston_info = weston_health_check()
    
    return f"""
    <html>
    <head>
        <title>Huggingface Space Status</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            .status {{ padding: 20px; border-radius: 5px; background-color: #f5f5f5; margin-bottom: 20px; }}
            .status h2 {{ margin-top: 0; color: #333; }}
            .metrics {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }}
            .metric {{ background-color: #fff; padding: 15px; border-radius: 5px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            .metric h3 {{ margin: 0; font-size: 16px; color: #666; }}
            .metric p {{ margin: 5px 0 0; font-size: 24px; font-weight: bold; color: #333; }}
            .process-list {{ margin-top: 20px; }}
            .process-item {{ background-color: #fff; padding: 10px; margin: 5px 0; border-radius: 3px; display: flex; justify-content: space-between; }}
            .process-name {{ font-weight: bold; }}
            .process-details {{ color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Application Status Monitor</h1>
            <div class="status">
                <h2>System Status</h2>
                <div class="metrics">
                    <div class="metric">
                        <h3>Memory Usage</h3>
                        <p>{sys_info['memory_used_percent']}%</p>
                    </div>
                    <div class="metric">
                        <h3>CPU Usage</h3>
                        <p>{sys_info['cpu_percent']}%</p>
                    </div>
                    <div class="metric">
                        <h3>Disk Usage</h3>
                        <p>{sys_info['disk_used_percent']}%</p>
                    </div>
                </div>
                
                <div class="process-list">
                    <h3>Running Processes</h3>
                    {
                        ''.join([
                            f'<div class="process-item"><span class="process-name">{p["name"]}</span>'
                            f'<span class="process-details">PID: {p["pid"]} | CPU: {p["cpu"]}% | MEM: {round(p["memory"], 2)}%</span></div>'
                            for p in sys_info['processes']
                        ])
                    }
                </div>
            </div>
            
            <div class="status">
                <h2>Browser Status</h2>
                <div class="process-list">
                    {
                        ''.join([
                            f'<div class="process-item"><span class="process-name">{p["name"]}</span>'
                            f'<span class="process-details">PID: {p["pid"]} | MEM: {p["memory_mb"]}MB | CPU: {p["cpu_percent"]}%</span></div>'
                            for p in browser_info
                        ])
                    }
                </div>
            </div>
            
            <div class="status">
                <h2>Weston Status</h2>
                <div class="process-list">
                    {
                        ''.join([
                            f'<div class="process-item"><span class="process-name">{p["name"]}</span>'
                            f'<span class="process-details">PID: {p["pid"]} | CPU: {p["cpu"]}% | MEM: {round(p["memory"], 2)}%</span></div>'
                            for p in weston_info
                        ]) if isinstance(weston_info, list) else '<div class="process-item">Weston is not running</div>'
                    }
                </div>
            </div>
            
            <p>Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    </body>
    </html>
    """

def start_background_thread():
    thread = threading.Thread(target=background_activity, daemon=True)
    thread.start()

# Start background activity when the app starts
start_background_thread()

if __name__ == "__main__":
    app.config['ENV'] = 'production'
    app.config['PROPAGATE_EXCEPTIONS'] = False
    app.run(host='0.0.0.0', port=7860)