# TC²-BBS Mesh Docker Documentation

This Docker image provides a "plug-and-play" experience for running the TC²-BBS system on Meshtastic devices.

## Quick Start

The easiest way to get started is with Docker Compose.

### Docker Compose Example

```yaml
services:
  tc2-bbs-mesh:
    image: thealhu/tc2-bbs-mesh:latest
    restart: always
    volumes:
      - ./config:/home/mesh/bbs/config
    container_name: tc2-bbs-mesh
    # Uncomment the devices section if using a USB-connected Meshtastic node
    # devices:
    #   - /dev/ttyUSB0:/dev/ttyUSB0
```

### Docker Run Example

You can also run the BBS server with a single `docker run` command:

```bash
docker run -d \
  --name tc2-bbs-mesh \
  --restart always \
  -v $(pwd)/config:/home/mesh/bbs/config \
  thealhu/tc2-bbs-mesh:latest
```

If you need to include USB devices, add them with the `--device` flag:

```bash
docker run -d \
  --name tc2-bbs-mesh \
  --restart always \
  -v $(pwd)/config:/home/mesh/bbs/config \
  --device /dev/ttyUSB0:/dev/ttyUSB0 \
  thealhu/tc2-bbs-mesh:latest
```

### First Run
When you first run the container, it will automatically detect if your `./config` directory is empty. It will initialize it with:
- `config.ini`: The main configuration file (copied from `example_config.ini`).
- `fortunes.txt`: The data file for the Fortune Teller feature.
- `bulletins.db`: The SQLite database file (automatically created on startup).

## Configuration

After the first run, you should edit `./config/config.ini` to set your interface type (Serial or TCP) and other preferences. The container will automatically see these changes when restarted.

## Persistence

All your data is stored in the volume you mount to `/home/mesh/bbs/config`. This includes:
- **Settings**: `config.ini`
- **Messages & Bulletins**: `bulletins.db`
- **Fortunes**: `fortunes.txt`

## Permission Issues (Proxmox / Linux Hosts)

If the container starts but crashes with a `Permission denied` error, or if you see a warning that "Volume not writable," it is likely because the host machine's directory is owned by root.

The container runs as a non-root user (`mesh`, UID 1000). To fix permission issues on your host machine, run:

```bash
sudo chown -R 1000:1000 ./config
```

## Legacy Support

If you were previously using the volume mapping `-v ./config:/config`, this version still supports it for backward compatibility. However, the new standard is `-v ./config:/home/mesh/bbs/config`.
