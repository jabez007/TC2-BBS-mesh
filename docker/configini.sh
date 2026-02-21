#!/bin/sh
set -e

CONFIG_VOL="/home/mesh/bbs/config"
APP_DIR="/home/mesh/bbs"
DB_NAME="bulletins.db"

# 1. Compatibility check: If user mounted to /config (legacy), use that instead.
if [ -f "/config/config.ini" ] && [ ! -f "$CONFIG_VOL/config.ini" ]; then
    echo "Found config.ini in legacy /config mount, using it."
    CONFIG_VOL="/config"
fi

# 2. Initialize config in volume if it doesn't exist
if [ ! -f "$CONFIG_VOL/config.ini" ]; then
    echo "Initializing config.ini from example..."
    cp "$APP_DIR/example_config.ini" "$CONFIG_VOL/config.ini"
fi

if [ ! -f "$CONFIG_VOL/fortunes.txt" ]; then
    echo "Initializing fortunes.txt from example..."
    if [ -f "$APP_DIR/examples/example_RulesOfAcquisition_fortunes.txt" ]; then
        cp "$APP_DIR/examples/example_RulesOfAcquisition_fortunes.txt" "$CONFIG_VOL/fortunes.txt"
    fi
fi

# 3. Link config files from volume to the application directory
ln -sf "$CONFIG_VOL/config.ini" "$APP_DIR/config.ini"
if [ -f "$CONFIG_VOL/fortunes.txt" ]; then
    ln -sf "$CONFIG_VOL/fortunes.txt" "$APP_DIR/fortunes.txt"
fi

# 4. Handle database persistence via symlink
if [ ! -f "$CONFIG_VOL/$DB_NAME" ]; then
    touch "$CONFIG_VOL/$DB_NAME" 2>/dev/null || echo "Warning: Volume not writable, DB persistence may fail."
fi

if [ -f "$CONFIG_VOL/$DB_NAME" ]; then
    ln -sf "$CONFIG_VOL/$DB_NAME" "$APP_DIR/$DB_NAME"
    echo "Database persistence enabled via symlink to $CONFIG_VOL."
else
    echo "Falling back to non-persistent database in application root."
fi

cd "$APP_DIR"

# Execute the application
exec python3 "server.py" "$@"
