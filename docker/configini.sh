#!/bin/sh
set -e

CONFIG_VOL="/home/mesh/bbs/config"
APP_DIR="/home/mesh/bbs"
DB_NAME="bulletins.db"

# 1. Initialize config in volume if it doesn't exist
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

# 2. Link config files from volume to the application directory
ln -sf "$CONFIG_VOL/config.ini" "$APP_DIR/config.ini"
if [ -f "$CONFIG_VOL/fortunes.txt" ]; then
    ln -sf "$CONFIG_VOL/fortunes.txt" "$APP_DIR/fortunes.txt"
fi

# 3. Handle database persistence via symlink
# We check if the DB exists in the volume. If it doesn't, we touch it 
# to ensure the symlink has a target, but we only do this if we can write to the volume.
if [ ! -f "$CONFIG_VOL/$DB_NAME" ]; then
    touch "$CONFIG_VOL/$DB_NAME" 2>/dev/null || echo "Warning: Volume not writable, DB persistence may fail."
fi

# Create the symlink in the writable APP_DIR pointing to the (potentially) persistent volume
if [ -f "$CONFIG_VOL/$DB_NAME" ]; then
    ln -sf "$CONFIG_VOL/$DB_NAME" "$APP_DIR/$DB_NAME"
    echo "Database persistence enabled via symlink to volume."
else
    echo "Falling back to non-persistent database in application root."
fi

cd "$APP_DIR"

# Execute the application
exec python3 "server.py" "$@"
