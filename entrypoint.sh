#!/bin/bash

cleanup() {
	echo "Cleaning up..."
	pkill -f weston
	exit 0
}

trap cleanup EXIT

# DNS BYPASS: Set up custom DNS resolution at runtime (with fallbacks for read-only systems)
echo "Setting up DNS bypass..."

# Try to modify resolv.conf, fallback to environment variables if read-only
if [ -w /etc/resolv.conf ]; then
    echo "nameserver 8.8.8.8" > /etc/resolv.conf
    echo "nameserver 8.8.4.4" >> /etc/resolv.conf
    echo "nameserver 1.1.1.1" >> /etc/resolv.conf
    echo "nameserver 1.0.0.1" >> /etc/resolv.conf
    echo "DNS configuration updated in /etc/resolv.conf"
else
    echo "Warning: /etc/resolv.conf is read-only, using alternative DNS methods"
    # Set environment variables for DNS resolution
    export RESOLV_CONF_OVERRIDE="nameserver 8.8.8.8\nnameserver 8.8.4.4\nnameserver 1.1.1.1\nnameserver 1.0.0.1"
fi

# Try to add hosts entries, with fallback for read-only systems
if [ -w /etc/hosts ]; then
    echo "# DNS bypass for blocked domains" >> /etc/hosts
    echo "204.79.197.200 rewards.bing.com" >> /etc/hosts
    echo "204.79.197.200 www.bing.com" >> /etc/hosts
    echo "13.107.42.14 rewards.bing.com" >> /etc/hosts
    echo "204.79.197.200 account.microsoft.com" >> /etc/hosts
    echo "Host entries added to /etc/hosts"
else
    echo "Warning: /etc/hosts is read-only, using Chrome host-rules instead"
    export CHROME_HOST_RULES="MAP rewards.bing.com 204.79.197.200,MAP www.bing.com 204.79.197.200,MAP account.microsoft.com 204.79.197.200"
fi

# Try to resolve rewards.bing.com and add to hosts if needed
echo "Testing DNS resolution for rewards.bing.com..."
REWARDS_IP=$(nslookup rewards.bing.com 8.8.8.8 2>/dev/null | grep 'Address:' | tail -1 | awk '{print $2}' 2>/dev/null || echo "")
if [ ! -z "$REWARDS_IP" ] && [ "$REWARDS_IP" != "8.8.8.8" ]; then
    if [ -w /etc/hosts ]; then
        echo "$REWARDS_IP rewards.bing.com" >> /etc/hosts
        echo "Added resolved IP $REWARDS_IP for rewards.bing.com to hosts file"
    else
        export CHROME_HOST_RULES="${CHROME_HOST_RULES},MAP rewards.bing.com $REWARDS_IP"
        echo "Will use Chrome host-rules for $REWARDS_IP"
    fi
else
    echo "Could not resolve rewards.bing.com, using fallback IPs"
fi


# Setup runtime directory
mkdir -p "${XDG_RUNTIME_DIR}"
chmod 0700 "${XDG_RUNTIME_DIR}"

# Create Weston config file with specific resolution
mkdir -p /home/user/.config/weston
cat > /home/user/.config/weston/weston.ini << EOF
[core]
idle-time=0
require-input=false
cursor-theme=default
cursor-size=24

[shell]
size=1920x1080
EOF

# Start Weston with headless backend and specific resolution
nohup /usr/bin/weston --backend=headless-backend.so --width=1920 --height=1080 &

# Wait for Weston to start
TIMEOUT=10
COUNTER=0
while [ ! -e "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ] && [ $COUNTER -lt $TIMEOUT ]; do
	echo "Waiting for Wayland socket... ($COUNTER/$TIMEOUT)"
	sleep 1
	COUNTER=$((COUNTER + 1))
done

if [ ! -e "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ]; then
	echo "Error: Wayland socket not found after $TIMEOUT seconds"
	exit 1
fi

# Print environment variables for debugging
echo "XDG_RUNTIME_DIR: ${XDG_RUNTIME_DIR}"
echo "WAYLAND_DISPLAY: ${WAYLAND_DISPLAY}"
echo "Wayland socket path: ${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}"
echo "Socket exists: $([ -e "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ] && echo "Yes" || echo "No")"

# Verify Weston is running
if pgrep -f weston > /dev/null; then
	echo "Weston process is running"
else
	echo "ERROR: Weston process is not running"
	exit 1
fi

# Try to run weston-info if available
if command -v weston-info > /dev/null; then
	echo "Running weston-info:"
	WAYLAND_DEBUG=1 weston-info || echo "weston-info failed"
fi

echo "Weston is ready"

# Execute the main command (main.py)
exec "$@"
