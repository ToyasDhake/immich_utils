# immich_utils
Some scripts to manage data backups on Immich server

## Immich Asset Downloader

A Python script to download images and videos from an Immich server, excluding assets from the network drive (deviceId: "Library Import").

### Features

- Fetches all assets from Immich server using pagination
- Filters out assets from network drive (deviceId: "Library Import")
- Saves filtered assets list to JSON file
- Downloads assets with original filenames
- Stores all files in a single data folder
- Skips already downloaded files
- Progress tracking and error handling

### Installation

```bash
pip install -r requirements.txt
```

### Usage

#### Download all non-network drive assets:
```bash
python downloader.py https://your-immich-server.com YOUR_API_KEY
```

#### Specify output directory:
```bash
python downloader.py https://your-immich-server.com YOUR_API_KEY -o /path/to/output
```

#### Only fetch and save assets list (don't download):
```bash
python downloader.py https://your-immich-server.com YOUR_API_KEY --list-only
```

### API Key

You need an API key with full access to your Immich server. You can generate one in your Immich admin panel under Settings > API Keys.

### Output

- Downloaded files are stored in `download/data/` folder
- Assets list is saved as `assets_to_download.json` in the `download/` folder
- Original filenames are preserved
